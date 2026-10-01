from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.db.session import session_factory
from app.db.models import Group
from app.handlers.keyboards import (
    group_start_menu,
    main_menu,
    registration_keyboard,
)
from app.repositories.groups import GroupRepository
from app.services.profile import sync_telegram_user
from app.services.group_registration import check_group_registration, register_group

router = Router(name="common")


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    if not message.from_user:
        return

    if message.chat.type in ("group", "supergroup"):
        async with session_factory() as session:
            group = await GroupRepository.upsert_from_chat(session, message.chat)
            member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
            if member.status not in ("creator", "administrator"):
                await message.answer("منوی مدیریت ربات فقط برای مدیران گروه در دسترس است.")
                return
            if not group.is_active or group.registered_at is None:
                await message.answer(
                    "این گروه هنوز در ربات ثبت نشده است.\n\n"
                    "برای ثبت، ابتدا مطمئن شوید ربات مدیر گروه است و دسترسی‌های لازم را دارد.",
                    reply_markup=registration_keyboard(),
                )
            else:
                await message.answer(
                    f"مدیریت ربات در گروه «{group.title or message.chat.id}»",
                    reply_markup=group_start_menu(group.id),
                )
        return

    async with session_factory() as session:
        user = await sync_telegram_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name or "",
            message.from_user.last_name,
        )
    await message.answer(
        f"سلام {user.display_name or 'دوست'}\n\n"
        "به ربات مافیا خوش آمدی.\n"
        "از منوی زیر بخش موردنظر را انتخاب کن.",
        reply_markup=main_menu(),
    )


@router.callback_query(lambda c: c.data == "groupreg:register")
async def register_group_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    # The callback message itself is the authoritative source for the Telegram
    # chat ID. Never trust an ID embedded in callback_data: old keyboards can
    # survive database resets and may contain an internal groups.id.
    if callback.message.chat.type not in ("group", "supergroup"):
        await callback.answer("ثبت گروه باید از داخل همان گروه انجام شود.", show_alert=True)
        return
    chat_id = callback.message.chat.id

    member = await callback.bot.get_chat_member(chat_id, callback.from_user.id)
    if member.status not in ("creator", "administrator"):
        await callback.answer("ثبت گروه فقط توسط مدیر گروه انجام می‌شود.", show_alert=True)
        return

    check = await check_group_registration(callback.bot, chat_id)
    if not check.ok:
        lines = ["ثبت گروه انجام نشد.", "", "موارد زیر را اصلاح کنید:"]
        lines.extend(f"• {item}" for item in check.problems)
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=registration_keyboard(),
        )
        await callback.answer("شرایط ثبت کامل نیست.", show_alert=True)
        return

    # Resolve the actual Telegram chat from the callback message chat ID.
    # This also makes stale registration keyboards safe after DB resets.
    try:
        chat = await callback.bot.get_chat(chat_id)
    except Exception:
        await callback.answer("اطلاعات گروه از تلگرام قابل دریافت نیست.", show_alert=True)
        return

    if chat.type not in ("group", "supergroup"):
        await callback.answer("شناسه ثبت‌شده مربوط به یک گروه نیست.", show_alert=True)
        return

    async with session_factory() as session:
        # Resolve strictly by Telegram chat ID so a stale/incorrect Chat object
        # can never create a second group row for another ID.
        group = await GroupRepository.get_by_telegram_id(session, chat_id)
        if group is None:
            group = await GroupRepository.upsert_from_chat(session, chat)

        # registered_by_user_id is an internal users.id FK, not a Telegram ID.
        # Sync the Telegram user first and persist the internal PK in groups.
        user = await sync_telegram_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name or "",
            callback.from_user.last_name,
        )
        await register_group(session, group, user.id)
        await callback.message.edit_text(
            f"گروه «{group.title or chat_id}» با موفقیت در ربات ثبت شد.",
            reply_markup=group_start_menu(group.id),
        )
    await callback.answer("گروه ثبت شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("groupstart:"))
async def group_start_menu_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    action = parts[1]
    group_id = int(parts[2])
    async with session_factory() as session:
        group = await session.get(Group, group_id)
        if not group or not group.is_active or group.registered_at is None:
            await callback.answer("این گروه هنوز ثبت نشده است.", show_alert=True)
            return
        member = await callback.bot.get_chat_member(group.telegram_id, callback.from_user.id)
        if member.status not in ("creator", "administrator"):
            await callback.answer("این بخش فقط برای مدیران گروه است.", show_alert=True)
            return
        if action == "root":
            await callback.message.edit_text(
                f"مدیریت ربات در گروه «{group.title}»",
                reply_markup=group_start_menu(group.id),
            )
        elif action == "close":
            await callback.message.delete()
        elif action == "help":
            await callback.message.edit_text(
                "راهنمای مدیریت ربات\n\n"
                "از «بازی جدید» برای ساخت لابی استفاده کنید.\n"
                "بازی‌ها بر اساس ظرفیت سناریو مدیریت می‌شوند.",
                reply_markup=group_start_menu(group.id),
            )
        elif action == "history":
            from app.handlers.menu import game_history_text
            await callback.message.edit_text(
                await game_history_text(session, group),
                reply_markup=group_start_menu(group.id),
            )
        elif action == "new":
            from app.handlers.menu import render_new_game_menu
            await callback.message.edit_text(
                await render_new_game_menu(session, group, callback.from_user.id),
                reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_menu"]).new_game_menu(group.id),
            )
    await callback.answer()
