"""Telegram Rich Message transport with a hard fallback to ordinary Bot API messages.

The rest of the bot continues to call aiogram's normal send_message /
edit_message_text APIs. This module transparently upgrades text messages to
Bot API Rich Messages and falls back to the original API whenever Rich
Messages are unavailable, rejected, malformed, or temporarily unhealthy.
"""

from __future__ import annotations

import html
import logging
import os
import time
from collections.abc import Mapping
from typing import Any

import aiohttp
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

_RICH_FAILURE_LIMIT = 3
_RICH_COOLDOWN_SECONDS = 60.0
_rich_failures = 0
_rich_disabled_until = 0.0
_patch_installed = False


def _enabled() -> bool:
    return os.getenv("RICH_MESSAGES_ENABLED", "true").strip().lower() not in {
        "0", "false", "no", "off"
    }


def _healthy() -> bool:
    return time.monotonic() >= _rich_disabled_until


def _mark_success() -> None:
    global _rich_failures, _rich_disabled_until
    _rich_failures = 0
    _rich_disabled_until = 0.0


def _mark_failure(exc: Exception) -> None:
    global _rich_failures, _rich_disabled_until
    _rich_failures += 1
    if _rich_failures >= _RICH_FAILURE_LIMIT:
        _rich_disabled_until = time.monotonic() + _RICH_COOLDOWN_SECONDS
        logger.warning(
            "Rich Messages temporarily disabled for %.0fs after repeated failures: %s",
            _RICH_COOLDOWN_SECONDS,
            exc,
        )


def _model_dump(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(by_alias=True, exclude_none=True)
    return value


def _rich_content(text: str | None, parse_mode: str | None) -> dict[str, Any]:
    value = text or ""
    mode = (parse_mode or "").upper().replace("_", "")
    if mode in {"MARKDOWN", "MARKDOWNV2"}:
        return {"markdown": value}
    if mode == "HTML":
        return {"html": value}
    return {"html": html.escape(value)}


def _pick(payload: Mapping[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {
        name: _model_dump(payload[name])
        for name in names
        if payload.get(name) is not None
    }


def _rich_inline_keyboard(markup: Any) -> str | None:
    """Convert an aiogram InlineKeyboardMarkup to Rich HTML buttons.

    Rich Messages support interactive buttons directly in rich HTML. Using
    them here avoids depending on the legacy reply_markup rendering path and
    keeps every existing callback_data/url keyboard usable.
    """
    data = _model_dump(markup)
    if not isinstance(data, Mapping) or not data.get("inline_keyboard"):
        return None

    rows: list[str] = []
    for row in data["inline_keyboard"]:
        buttons: list[str] = []
        for button in row:
            if not isinstance(button, Mapping):
                return None
            label = html.escape(str(button.get("text") or ""), quote=False)
            style = str(button.get("style") or "").strip()
            style_attr = f' style="{html.escape(style, quote=True)}"' if style in {"danger", "success", "primary", "link"} else ""
            if button.get("callback_data") is not None:
                callback_data = html.escape(str(button["callback_data"]), quote=True)
                buttons.append(
                    f'<tg-button type="callback_data" data="{callback_data}"{style_attr}>{label}</tg-button>'
                )
            elif button.get("url") is not None:
                url = html.escape(str(button["url"]), quote=True)
                buttons.append(
                    f'<tg-button type="url" url="{url}"{style_attr}>{label}</tg-button>'
                )
            elif button.get("web_app") is not None:
                web_app = _model_dump(button["web_app"])
                if not isinstance(web_app, Mapping) or not web_app.get("url"):
                    return None
                url = html.escape(str(web_app["url"]), quote=True)
                buttons.append(
                    f'<tg-button type="web_app" url="{url}"{style_attr}>{label}</tg-button>'
                )
            elif button.get("login_url") is not None:
                login = _model_dump(button["login_url"])
                if not isinstance(login, Mapping) or not login.get("url"):
                    return None
                url = html.escape(str(login["url"]), quote=True)
                buttons.append(
                    f'<tg-button type="login_url" url="{url}"{style_attr}>{label}</tg-button>'
                )
            else:
                # Unknown button types must never silently disappear.
                return None
        rows.append('<tg-button-row align="center">' + "".join(buttons) + "</tg-button-row>")
    return "".join(rows)


def _is_inline_keyboard(markup: Any) -> bool:
    data = _model_dump(markup)
    return isinstance(data, Mapping) and bool(data.get("inline_keyboard"))


def _rich_content_with_markup(
    text: str | None,
    parse_mode: str | None,
    reply_markup: Any = None,
) -> dict[str, Any]:
    content = _rich_content(text, parse_mode)
    if reply_markup is None:
        return content
    keyboard = _rich_inline_keyboard(reply_markup)
    if keyboard is None:
        return content
    key = next(iter(content))
    content[key] = f"{content[key]}{keyboard}"
    return content


def _send_rich_payload(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    content = _rich_content_with_markup(
        kwargs.get("text"),
        kwargs.get("parse_mode"),
        kwargs.get("reply_markup"),
    )
    rich_message = {**content, "is_rtl": True}
    payload: dict[str, Any] = {
        "chat_id": kwargs.get("chat_id"),
        "rich_message": rich_message,
    }
    if kwargs.get("message_thread_id") is not None:
        payload["message_thread_id"] = kwargs["message_thread_id"]
    if kwargs.get("direct_messages_topic_id") is not None:
        payload["direct_messages_topic_id"] = kwargs["direct_messages_topic_id"]

    payload.update(_pick(kwargs, (
        "business_connection_id",
        "disable_notification",
        "protect_content",
        "allow_paid_broadcast",
        "message_effect_id",
        "suggested_post_parameters",
        "reply_parameters",
    )))
    if kwargs.get("reply_markup") is not None and not _is_inline_keyboard(kwargs["reply_markup"]):
        payload["reply_markup"] = _model_dump(kwargs["reply_markup"])
    return {k: v for k, v in payload.items() if v is not None}


def _edit_rich_payload(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    content = _rich_content_with_markup(
        kwargs.get("text"),
        kwargs.get("parse_mode"),
        kwargs.get("reply_markup"),
    )
    payload: dict[str, Any] = {
        "rich_message": {**content, "is_rtl": True}
    }
    if kwargs.get("reply_markup") is not None and not _is_inline_keyboard(kwargs["reply_markup"]):
        payload["reply_markup"] = _model_dump(kwargs["reply_markup"])
    for name in (
        "business_connection_id",
        "chat_id",
        "message_id",
        "inline_message_id",
    ):
        if kwargs.get(name) is not None:
            payload[name] = _model_dump(kwargs[name])
    return payload


async def _call(method: str, token: str, payload: dict[str, Any]) -> Any:
    url = f"https://api.telegram.org/bot{token}/{method}"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(url, json=payload) as response:
            data = await response.json(content_type=None)
            if not response.ok or not data.get("ok"):
                raise RuntimeError(
                    data.get("description") or f"Telegram API {response.status}"
                )
            return data.get("result")


async def _try_rich(method: str, token: str, payload: dict[str, Any]) -> Any:
    if not _enabled() or not _healthy():
        raise RuntimeError("rich transport unavailable")
    try:
        result = await _call(method, token, payload)
        _mark_success()
        if isinstance(result, dict) and result.get("message_id") is not None:
            try:
                return Message.model_validate(result)
            except Exception:
                # Keep the raw result only as a last resort; callers that need
                # Message attributes will otherwise trigger the normal fallback.
                pass
        return result
    except Exception as exc:
        _mark_failure(exc)
        raise


async def send_rich_message(bot: Any, chat_id: int | str, html_content: str, *, reply_markup: Any = None, is_rtl: bool = True, **extra: Any) -> Any:
    """Explicitly send a Telegram Rich Message without changing normal messages."""
    if not _enabled():
        raise RuntimeError("Rich Messages are disabled")
    payload = {
        "chat_id": chat_id,
        "rich_message": {"html": html_content, "is_rtl": is_rtl},
    }
    if reply_markup is not None:
        keyboard = _rich_inline_keyboard(reply_markup)
        if keyboard:
            payload["rich_message"]["html"] += keyboard
        elif not _is_inline_keyboard(reply_markup):
            payload["reply_markup"] = _model_dump(reply_markup)
    payload.update(_pick(extra, (
        "message_thread_id", "direct_messages_topic_id", "business_connection_id",
        "disable_notification", "protect_content", "allow_paid_broadcast",
        "message_effect_id", "suggested_post_parameters", "reply_parameters",
    )))
    return await _try_rich("sendRichMessage", bot.token, {k: v for k, v in payload.items() if v is not None})


async def edit_rich_message(bot: Any, chat_id: int | str, message_id: int, html_content: str, *, reply_markup: Any = None, is_rtl: bool = True, **extra: Any) -> Any:
    """Explicitly edit a message into a Telegram Rich Message."""
    if not _enabled():
        raise RuntimeError("Rich Messages are disabled")
    rich_html = html_content
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "rich_message": {"html": rich_html, "is_rtl": is_rtl},
    }
    if reply_markup is not None:
        keyboard = _rich_inline_keyboard(reply_markup)
        if keyboard:
            payload["rich_message"]["html"] += keyboard
        elif not _is_inline_keyboard(reply_markup):
            payload["reply_markup"] = _model_dump(reply_markup)
    payload.update(_pick(extra, ("business_connection_id", "inline_message_id")))
    return await _try_rich("editMessageText", bot.token, {k: v for k, v in payload.items() if v is not None})


def install_rich_message_transport() -> None:
    """Install one global, transparent Rich Message transport on aiogram Bot.

    Normal text messages remain on the stable aiogram transport by default. Structured
    screens can opt into Rich explicitly through send_rich_message/edit_rich_message;
    setting RICH_MESSAGES_AUTO=true restores transparent Rich conversion for all text.
    The original aiogram methods remain the authoritative fallback.
    """
    global _patch_installed
    if _patch_installed:
        return

    from aiogram import Bot

    original_send_message = Bot.send_message
    original_edit_message_text = Bot.edit_message_text

    async def _safe_original_edit(*args: Any, **kwargs: Any):
        try:
            return await original_edit_message_text(*args, **kwargs)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                logger.debug("Ignoring Telegram message-not-modified edit")
                return None
            raise

    async def send_message(self, *args: Any, **kwargs: Any):
        original_args = args
        normalized = dict(kwargs)
        if args:
            if len(args) >= 1:
                normalized.setdefault("chat_id", args[0])
            if len(args) >= 2:
                normalized.setdefault("text", args[1])

        if os.getenv("RICH_MESSAGES_AUTO", "false").strip().lower() not in {"1", "true", "yes", "on"} or not _enabled() or not _healthy() or normalized.get("text") is None:
            return await original_send_message(self, *original_args, **kwargs)

        try:
            payload = _send_rich_payload(normalized)
            return await _try_rich("sendRichMessage", self.token, payload)
        except Exception:
            return await original_send_message(self, *original_args, **kwargs)

    async def edit_message_text(self, *args: Any, **kwargs: Any):
        original_args = args
        normalized = dict(kwargs)
        if args:
            if len(args) >= 1:
                normalized.setdefault("chat_id", args[0])
            if len(args) >= 2:
                normalized.setdefault("message_id", args[1])
            if len(args) >= 3:
                normalized.setdefault("text", args[2])

        if os.getenv("RICH_MESSAGES_AUTO", "false").strip().lower() not in {"1", "true", "yes", "on"} or not _enabled() or not _healthy() or normalized.get("text") is None:
            return await _safe_original_edit(self, *original_args, **kwargs)

        try:
            payload = _edit_rich_payload(normalized)
            return await _try_rich("editMessageText", self.token, payload)
        except Exception:
            return await _safe_original_edit(self, *original_args, **kwargs)

    Bot.send_message = send_message
    Bot.edit_message_text = edit_message_text
    _patch_installed = True
    logger.info("Global Telegram Rich Message transport installed")
