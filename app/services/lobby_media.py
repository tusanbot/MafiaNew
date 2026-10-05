from aiogram.types import InlineKeyboardMarkup
from app.db.models import Group, GroupSettings
from sqlalchemy import select


async def _settings(session, group: Group):
    return await session.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))


async def resolve_lobby_media(session, bot, group: Group):
    settings = await _settings(session, group)
    if settings is not None and not bool(getattr(settings, "lobby_media_enabled", True)):
        return None
    if settings is not None and settings.lobby_media_file_id and settings.lobby_media_type in {"photo", "video"}:
        return settings.lobby_media_type, settings.lobby_media_file_id
    settings = settings or await _settings(session, group)
    cached_profile_id = getattr(settings, "lobby_profile_file_id", None) if settings else None
    if cached_profile_id:
        return "photo", cached_profile_id
    try:
        chat = await bot.get_chat(group.telegram_id)
        photo = getattr(chat, "photo", None)
        file_id = getattr(photo, "big_file_id", None) if photo else None
        if file_id:
            if settings is not None:
                settings.lobby_profile_file_id = file_id
                await session.commit()
            return "photo", file_id
    except Exception:
        pass
    return None


async def send_lobby_message(bot, session, group: Group, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    media = await resolve_lobby_media(session, bot, group)
    if media:
        kind, file_id = media
        if kind == "video":
            return await bot.send_video(
                group.telegram_id, file_id, caption=text, parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return await bot.send_photo(
            group.telegram_id, file_id, caption=text, parse_mode="HTML",
            reply_markup=reply_markup,
        )
    return await bot.send_message(
        group.telegram_id, text, parse_mode="HTML", reply_markup=reply_markup
    )


async def edit_lobby_message(
    bot, session, group: Group, message_id: int, text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    media = await resolve_lobby_media(session, bot, group)
    if media:
        try:
            return await bot.edit_message_caption(
                chat_id=group.telegram_id,
                message_id=message_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except Exception:
            # A changed media setting or an externally deleted message may require
            # a one-time recreation. Normal lobby updates never resend the media.
            try:
                await bot.delete_message(group.telegram_id, message_id)
            except Exception:
                pass
            return await send_lobby_message(bot, session, group, text, reply_markup)

    try:
        return await bot.edit_message_text(
            text,
            chat_id=group.telegram_id,
            message_id=message_id,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception:
        try:
            await bot.delete_message(group.telegram_id, message_id)
        except Exception:
            pass
        return await bot.send_message(
            group.telegram_id, text, parse_mode="HTML", reply_markup=reply_markup
        )
