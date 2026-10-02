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


def _send_rich_payload(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    rich_message = {
        **_rich_content(kwargs.get("text"), kwargs.get("parse_mode")),
        "is_rtl": True,
    }
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
        "reply_markup",
    )))
    return {k: v for k, v in payload.items() if v is not None}


def _edit_rich_payload(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rich_message": {
            **_rich_content(kwargs.get("text"), kwargs.get("parse_mode")),
            "is_rtl": True,
        }
    }
    for name in (
        "business_connection_id",
        "chat_id",
        "message_id",
        "inline_message_id",
        "reply_markup",
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


def install_rich_message_transport() -> None:
    """Install one global, transparent Rich Message transport on aiogram Bot.

    All normal text sends/edits in the bot pass through this layer. Menus,
    profiles, admin panels, lobby/game messages, voting, challenges,
    notifications, results and text commands therefore use the same transport.
    The original aiogram methods remain the authoritative fallback.
    """
    global _patch_installed
    if _patch_installed:
        return

    from aiogram import Bot

    original_send_message = Bot.send_message
    original_edit_message_text = Bot.edit_message_text

    async def send_message(self, *args: Any, **kwargs: Any):
        original_args = args
        normalized = dict(kwargs)
        if args:
            if len(args) >= 1:
                normalized.setdefault("chat_id", args[0])
            if len(args) >= 2:
                normalized.setdefault("text", args[1])

        if not _enabled() or not _healthy() or normalized.get("text") is None:
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

        if not _enabled() or not _healthy() or normalized.get("text") is None:
            return await original_edit_message_text(self, *original_args, **kwargs)

        try:
            payload = _edit_rich_payload(normalized)
            return await _try_rich("editMessageText", self.token, payload)
        except Exception:
            return await original_edit_message_text(self, *original_args, **kwargs)

    Bot.send_message = send_message
    Bot.edit_message_text = edit_message_text
    _patch_installed = True
    logger.info("Global Telegram Rich Message transport installed")
