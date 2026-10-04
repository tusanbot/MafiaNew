from __future__ import annotations

import asyncio
import json
import logging
from typing import Final

import aiohttp

from app.config import get_settings

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTION_URL: Final = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL: Final = "whisper-large-v3-turbo"
MAX_AUDIO_BYTES: Final = 25 * 1024 * 1024


class SpeechToTextError(RuntimeError):
    """Raised when speech-to-text cannot be completed."""


async def transcribe_voice(
    audio: bytes,
    *,
    filename: str = "voice.ogg",
    language: str = "fa",
) -> str:
    """Transcribe Telegram voice/audio bytes with Groq Whisper.

    Telegram voice messages are OGG/Opus, which Groq accepts directly.
    The language is explicitly set to Persian to improve accuracy/latency.
    """
    if not audio:
        raise SpeechToTextError("فایل صوتی خالی است.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise SpeechToTextError("حجم فایل صوتی بیشتر از سقف مجاز است.")

    settings = get_settings()
    api_key = getattr(settings, "groq_api_key", "") or ""
    if not api_key:
        raise SpeechToTextError("کلید سرویس تبدیل صدا تنظیم نشده است.")

    model = getattr(settings, "stt_model", "") or DEFAULT_MODEL
    timeout = aiohttp.ClientTimeout(total=120)

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

    try:
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.post(
                GROQ_TRANSCRIPTION_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                data=form,
            ) as response:
                raw = await response.text()
                if response.status >= 400:
                    logger.warning(
                        "Groq STT request failed: status=%s body=%s",
                        response.status,
                        raw[:1000],
                    )
                    raise SpeechToTextError(
                        "سرویس تبدیل صدا در دسترس نیست یا درخواست رد شد."
                    )
    except asyncio.TimeoutError as exc:
        raise SpeechToTextError("زمان پردازش پیام صوتی تمام شد.") from exc
    except aiohttp.ClientError as exc:
        logger.warning("Groq STT network error: %s", exc)
        raise SpeechToTextError("ارتباط با سرویس تبدیل صدا برقرار نشد.") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Groq STT returned invalid JSON: %s", raw[:500])
        raise SpeechToTextError("پاسخ سرویس تبدیل صدا نامعتبر بود.") from exc

    text = str(payload.get("text") or "").strip()
    if not text:
        raise SpeechToTextError("از این پیام صوتی متنی قابل تشخیص پیدا نشد.")
    return text
