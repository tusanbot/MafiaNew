from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Final

import aiohttp

from app.config import get_settings

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTION_URL: Final = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL: Final = "whisper-large-v3-turbo"
MAX_AUDIO_BYTES: Final = 25 * 1024 * 1024
DEFAULT_KEY_COOLDOWN_SECONDS: Final = 60.0
MAX_KEY_COOLDOWN_SECONDS: Final = 15 * 60.0


class SpeechToTextError(RuntimeError):
    """Raised when speech-to-text cannot be completed."""


_key_lock = asyncio.Lock()
_key_index = 0
_key_cooldowns: dict[str, float] = {}


def _get_api_keys() -> list[str]:
    """Return configured Groq keys, preserving the legacy single-key setting."""
    settings = get_settings()
    raw_keys = getattr(settings, "groq_api_keys", "") or ""
    legacy_key = getattr(settings, "groq_api_key", "") or ""

    keys: list[str] = []
    for raw in raw_keys.split(","):
        key = raw.strip()
        if key and key not in keys:
            keys.append(key)

    if legacy_key.strip() and legacy_key.strip() not in keys:
        keys.append(legacy_key.strip())

    return keys


def _retry_after_seconds(response: aiohttp.ClientResponse) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return max(1.0, min(float(value), MAX_KEY_COOLDOWN_SECONDS))
        except ValueError:
            pass
    return DEFAULT_KEY_COOLDOWN_SECONDS


async def _next_available_key(keys: list[str]) -> tuple[int, str] | None:
    """Pick the next non-cooled-down key in round-robin order."""
    global _key_index

    async with _key_lock:
        now = time.monotonic()
        start = _key_index % len(keys)

        for offset in range(len(keys)):
            index = (start + offset) % len(keys)
            key = keys[index]
            if _key_cooldowns.get(key, 0.0) <= now:
                _key_index = (index + 1) % len(keys)
                return index, key

    return None


async def _cooldown_key(key: str, seconds: float) -> None:
    async with _key_lock:
        _key_cooldowns[key] = max(
            _key_cooldowns.get(key, 0.0),
            time.monotonic() + seconds,
        )


def _key_label(index: int) -> str:
    return f"key #{index + 1}"


def _build_form(
    audio: bytes,
    *,
    filename: str,
    model: str,
    language: str,
) -> aiohttp.FormData:
    form = aiohttp.FormData()
    form.add_field(
        "file",
        audio,
        filename=filename,
        content_type="audio/ogg",
    )
    form.add_field("model", model)
    form.add_field("language", language)
    form.add_field("response_format", "json")
    form.add_field("temperature", "0")
    return form


async def transcribe_voice(
    audio: bytes,
    *,
    filename: str = "voice.ogg",
    language: str = "fa",
) -> str:
    """Transcribe Telegram voice/audio bytes with Groq Whisper.

    Multiple Groq API keys are supported through GROQ_API_KEYS. Keys are used
    in round-robin order; a key receiving HTTP 429 is temporarily cooled down
    and the same request is retried with another available key.

    GROQ_API_KEY remains supported for backward compatibility.
    """
    if not audio:
        raise SpeechToTextError("فایل صوتی خالی است.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise SpeechToTextError("حجم فایل صوتی بیشتر از سقف مجاز است.")

    settings = get_settings()
    keys = _get_api_keys()
    if not keys:
        raise SpeechToTextError("کلید سرویس تبدیل صدا تنظیم نشده است.")

    model = getattr(settings, "stt_model", "") or DEFAULT_MODEL
    timeout = aiohttp.ClientTimeout(total=120)

    attempted: set[str] = set()

    try:
        async with aiohttp.ClientSession(timeout=timeout) as http:
            while len(attempted) < len(keys):
                selected = await _next_available_key(keys)
                if selected is None:
                    break

                key_index, api_key = selected
                if api_key in attempted:
                    break
                attempted.add(api_key)

                form = _build_form(
                    audio,
                    filename=filename,
                    model=model,
                    language=language,
                )

                try:
                    async with http.post(
                        GROQ_TRANSCRIPTION_URL,
                        headers={"Authorization": f"Bearer {api_key}"},
                        data=form,
                    ) as response:
                        raw = await response.text()

                        if response.status == 429:
                            cooldown = _retry_after_seconds(response)
                            await _cooldown_key(api_key, cooldown)
                            logger.warning(
                                "Groq STT %s is rate-limited; cooling down for %.0fs",
                                _key_label(key_index),
                                cooldown,
                            )
                            continue

                        if response.status >= 400:
                            logger.warning(
                                "Groq STT %s request failed: status=%s body=%s",
                                _key_label(key_index),
                                response.status,
                                raw[:1000],
                            )
                            raise SpeechToTextError(
                                "سرویس تبدیل صدا در دسترس نیست یا درخواست رد شد."
                            )

                except asyncio.TimeoutError as exc:
                    raise SpeechToTextError("زمان پردازش پیام صوتی تمام شد.") from exc
                except aiohttp.ClientError as exc:
                    logger.warning(
                        "Groq STT %s network error: %s",
                        _key_label(key_index),
                        exc,
                    )
                    raise SpeechToTextError(
                        "ارتباط با سرویس تبدیل صدا برقرار نشد."
                    ) from exc

                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Groq STT returned invalid JSON: %s",
                        raw[:500],
                    )
                    raise SpeechToTextError(
                        "پاسخ سرویس تبدیل صدا نامعتبر بود."
                    ) from exc

                text = str(payload.get("text") or "").strip()
                if not text:
                    raise SpeechToTextError(
                        "از این پیام صوتی متنی قابل تشخیص پیدا نشد."
                    )
                return text

    except SpeechToTextError:
        raise

    if attempted and all(
        _key_cooldowns.get(key, 0.0) > time.monotonic()
        for key in attempted
    ):
        raise SpeechToTextError(
            "همه کلیدهای سرویس تبدیل صدا موقتاً به محدودیت خورده‌اند. "
            "لطفاً کمی بعد دوباره تلاش کنید."
        )

    raise SpeechToTextError(
        "سرویس تبدیل صدا در حال حاضر در دسترس نیست. لطفاً دوباره تلاش کنید."
    )
