from types import SimpleNamespace

from app.utils.custom_emoji import (
    DEFAULT_EMOJIS,
    dump_emoji_map,
    emoji_html,
    extract_custom_emoji_id,
    normalize_emoji_map,
)


def test_custom_emoji_html_uses_configured_id():
    rendered = emoji_html("challenge", custom_emoji_ids={"challenge": "123456789"}, enabled=True)
    assert 'emoji-id="123456789"' in rendered
    assert "🤏🏻" in rendered


def test_custom_emoji_html_falls_back_for_invalid_id():
    rendered = emoji_html("challenge", custom_emoji_ids={"challenge": "bad"}, enabled=True)
    assert rendered == DEFAULT_EMOJIS["challenge"]


def test_custom_emoji_html_respects_disabled_flag():
    assert emoji_html("challenge", custom_emoji_ids={"challenge": "123"}, enabled=False) == ""


def test_custom_emoji_map_round_trip():
    value = dump_emoji_map({"challenge": "123", "vote": "456", "unknown": "789"})
    assert normalize_emoji_map(value) == {"challenge": "123", "vote": "456"}


def test_extract_custom_emoji_id_from_message_entities():
    message = SimpleNamespace(
        text="🤏",
        entities=[
            SimpleNamespace(type="bold", custom_emoji_id=None),
            SimpleNamespace(type="custom_emoji", custom_emoji_id="987654321"),
        ],
        caption=None,
        caption_entities=None,
    )
    assert extract_custom_emoji_id(message) == "987654321"


def test_extract_custom_emoji_id_returns_none_without_custom_entity():
    message = SimpleNamespace(
        text="🤏🏻",
        entities=[],
        caption=None,
        caption_entities=None,
    )
    assert extract_custom_emoji_id(message) is None
