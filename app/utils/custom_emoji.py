"""Telegram Custom Emoji helpers with safe Unicode fallback.

Admins can configure custom emoji IDs by sending an emoji from a Telegram
custom-emoji pack. The bot receives the stable custom_emoji_id in MessageEntity.
All rendering is centralized here so an invalid/missing ID never breaks a game.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

DEFAULT_EMOJIS: dict[str, str] = {
    "turn": "⏩",
    "challenge": "🤏🏻",
    "vote": "🗳️",
    "defense": "🛡️",
    "silence": "🔇",
    "extra_turn": "➕",
    "warning": "⚠️",
    "death": "💀",
    "kick": "⛔",
    "slaughter": "🩸",
    "night": "🌙",
    "day": "☀️",
    "win": "🏆",
    "lose": "💔",
    "leader": "👑",
    "game": "🎮",
    "role": "🎭",
}

def normalize_emoji_map(value: str | Mapping[str, Any] | None) -> dict[str, str]:
    try:
        raw = json.loads(value or "{}") if isinstance(value, str) else dict(value or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        raw = {}
    return {
        str(key): str(item)
        for key, item in raw.items()
        if str(key) in DEFAULT_EMOJIS and str(item).strip()
    }


def normalize_custom_emoji_map(value: str | Mapping[str, Any] | None) -> dict[str, str]:
    """Normalize an arbitrary key -> custom emoji ID mapping."""
    try:
        raw = json.loads(value or "{}") if isinstance(value, str) else dict(value or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        raw = {}
    return {
        str(key): str(item).strip()
        for key, item in raw.items()
        if str(key).strip() and str(item).strip().isdigit()
    }


def custom_emoji_html(
    custom_emoji_id: str | None,
    fallback: str,
    *,
    enabled: bool = True,
) -> str:
    """Render a single custom emoji with a safe Unicode fallback."""
    if not enabled or not str(custom_emoji_id or "").strip().isdigit():
        return fallback
    return f'<tg-emoji emoji-id="{str(custom_emoji_id).strip()}">{fallback}</tg-emoji>'

def dump_emoji_map(value: Mapping[str, Any] | None) -> str:
    return json.dumps(normalize_emoji_map(value), ensure_ascii=False, separators=(",", ":"))

def extract_custom_emoji_id(message: Any) -> str | None:
    """Return the first Telegram custom_emoji_id from a message or caption."""
    for entities_name, text_name in (("entities", "text"), ("caption_entities", "caption")):
        entities = getattr(message, entities_name, None) or []
        text = getattr(message, text_name, None) or ""
        for entity in entities:
            if getattr(entity, "type", None) != "custom_emoji":
                continue
            custom_id = getattr(entity, "custom_emoji_id", None)
            if custom_id:
                return str(custom_id)
    return None

def emoji_html(
    key: str,
    *,
    custom_emoji_ids: str | Mapping[str, Any] | None = None,
    enabled: bool = True,
    fallback: str | None = None,
) -> str:
    """Render one emoji as Telegram HTML custom emoji when configured."""
    plain = fallback or DEFAULT_EMOJIS.get(key, "✨")
    if not enabled:
        return ""
    mapping = normalize_emoji_map(custom_emoji_ids)
    custom_id = mapping.get(key)
    if not custom_id:
        return plain
    safe_id = custom_id.strip()
    if not safe_id.isdigit():
        return plain
    return f'<tg-emoji emoji-id="{safe_id}">{plain}</tg-emoji>'

def emoji_map_from_game(game: Any) -> dict[str, str]:
    return normalize_emoji_map(getattr(game, "custom_emoji_ids", None))

def game_emoji(game: Any, key: str, fallback: str | None = None) -> str:
    enabled = bool(getattr(game, "custom_emoji_enabled", True))
    return emoji_html(
        key,
        custom_emoji_ids=emoji_map_from_game(game),
        enabled=enabled,
        fallback=fallback,
    )

def group_emoji(settings: Any, key: str, fallback: str | None = None) -> str:
    enabled = bool(getattr(settings, "custom_emoji", False))
    return emoji_html(
        key,
        custom_emoji_ids=getattr(settings, "custom_emoji_ids", None),
        enabled=enabled,
        fallback=fallback,
    )
