from aiogram import Router
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.db.models import Group, Scenario, User
from app.db.session import session_factory
from app.repositories.games import GameRepository
from app.repositories.users import UserRepository
from app.services.game import render_lobby, role_messages, gregorian_to_jalali
from app.services.roles import assign_roles
from app.services.gameplay import choose_leader, start_round
from app.handlers.keyboards import group_management_menu, lobby_keyboard_v2, leader_settings_keyboard, leader_choice_keyboard, leader_players_keyboard
from app.utils.text import tg_name, tg_plain_name

router = Router(name="game")


async def _load_game(session, game_key: str):
    return await GameRepository.get_by_key(session, game_key)


async def _render(callback: CallbackQuery, session, game, user_id: int):
    scenario = await session.get(Scenario, game.scenario_id)
    players = await GameRepository.players(session, game.id)
    reserves = await GameRepository.reserves(session, game.id)
    host = await session.get(User, game.host_user_id) if game.host_user_id else None
    text, full = await render_lobby(session, game)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=lobby_keyboard_v2(
            game.game_key,
            scenario,
            players,
            reserves,
            is_host=bool(host and host.id == user_id),
            can_deal=full,
            reserve_enabled=game.reserve_enabled,
            training_url=scenario.training_url,
            telegram_training_url=scenario.telegram_training_url,
        ),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("groupadmin:lobby:"))
async def group_management_from_lobby(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    game_key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        group = await session.get(Group, game.group_id)
        if not group:
            await callback.answer("گروه بازی پیدا نشد.", show_alert=True)
            return
        try:
            member = await callback.bot.get_chat_member(group.telegram_id, callback.from_user.id)
            if member.status not in ("creator", "administrator"):
                await callback.answer("فقط مدیر گروه می‌تواند وارد مدیریت گروه شود.", show_alert=True)
                return
        except Exception:
            await callback.answer("دسترسی مدیریت گروه تأیید نشد.", show_alert=True)
            return
        await callback.message.edit_text(
            f"مدیریت گروه «{group.title or group.telegram_id}»\n\nبخش موردنظر را انتخاب کنید.",
            reply_markup=group_management_menu(f"groupadmin:lobby:{game.game_key}"),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("game:join:"))
async def join_game(callback: CallbackQuery) -> None:
    game_key = callback.data.split(":", 2)[2]
    if not callback.from_user or not callback.message:
        return
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game or game.status != "waiting":
            await callback.answer("این بازی دیگر قابل پیوستن نیست.", show_alert=True)
            return
        user = await UserRepository(session).upsert_from_telegram(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name or "",
            callback.from_user.last_name,
        )
        player = await GameRepository.join(session, game, user)
        if player is None:
            await callback.answer("ظرفیت اصلی پر است؛ از گزینه «رزرو» استفاده کنید.", show_alert=True)
            return
        await _render(callback, session, game, user.id)
        await callback.answer(f"صندلی {player.seat} برای شما ثبت شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("lobby:reserve:"))
async def reserve_game(callback: CallbackQuery) -> None:
    game_key = callback.data.split(":", 2)[2]
    if not callback.from_user or not callback.message:
        return
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        user = await UserRepository(session).upsert_from_telegram(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name or "",
            callback.from_user.last_name,
        )
        player = await GameRepository.join_reserve(session, game, user)
        if player is None:
            await callback.answer("در حال حاضر امکان ثبت رزرو وجود ندارد.", show_alert=True)
            return
        await _render(callback, session, game, user.id)
        group = await session.get(Group, game.group_id)
        if group:
            await callback.bot.send_message(group.telegram_id, f"بازیکن {tg_name(user.display_name or user.first_name)} وارد لیست جایگزین شد؛ جایگاه رزرو {player.reserve_position}.")
        await callback.answer(f"رزرو شما ثبت شد؛ جایگاه رزرو {player.reserve_position}.")


@router.callback_query(lambda c: c.data and c.data.startswith("lobby:seat:"))
async def change_or_take_seat(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("درخواست صندلی نامعتبر است.", show_alert=True)
        return
    _, _, game_key, seat_raw = parts
    try:
        seat = int(seat_raw)
    except ValueError:
        await callback.answer("شماره صندلی نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game or game.status != "waiting":
            await callback.answer("تغییر صندلی در این مرحله ممکن نیست.", show_alert=True)
            return
        user = await UserRepository(session).upsert_from_telegram(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name or "",
            callback.from_user.last_name,
        )
        player = await GameRepository.join_at_seat(session, game, user, seat)
        if player is None:
            await callback.answer("این صندلی اشغال است، یا برای شما قابل انتخاب نیست.", show_alert=True)
            return
        await _render(callback, session, game, user.id)
        await callback.answer(f"صندلی {player.seat} برای شما ثبت شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("game:leave:"))
async def leave_game(callback: CallbackQuery) -> None:
    game_key = callback.data.split(":", 2)[2]
    if not callback.from_user or not callback.message:
        return
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        user = await UserRepository(session).upsert_from_telegram(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name or "",
            callback.from_user.last_name,
        )
        ok, promoted = await GameRepository.leave(session, game, user)
        if not ok:
            await callback.answer("شما در این بازی نیستید.", show_alert=True)
            return
        await _render(callback, session, game, user.id)
        if promoted:
            await callback.message.answer(
                f"بازیکن رزرو {promoted.reserve_position or ''} به دلیل خالی شدن صندلی، وارد لیست اصلی بازی شد."
            )
        await callback.answer("از بازی خارج شدید.")


@router.callback_query(lambda c: c.data and c.data.startswith("lobby:deal:"))
async def deal_roles(callback: CallbackQuery) -> None:
    game_key = callback.data.split(":", 2)[2]
    if not callback.from_user or not callback.message:
        return
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game or game.status != "waiting":
            await callback.answer("پخش نقش در این مرحله ممکن نیست.", show_alert=True)
            return
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        if not host or host.telegram_id != callback.from_user.id:
            await callback.answer("فقط گرداننده می‌تواند نقش‌ها را پخش کند.", show_alert=True)
            return
        scenario = await session.get(Scenario, game.scenario_id)
        players = await GameRepository.players(session, game.id)
        if not scenario or len(players) != scenario.max_players:
            await callback.answer(f"برای پخش نقش باید {scenario.max_players if scenario else 'تعداد کامل'} صندلی تکمیل باشد.", show_alert=True)
            return
        # پاسخ callback را زود ارسال می‌کنیم تا دکمه در حالت loading گیر نکند؛
        # ادامه‌ی پخش نقش مستقل از acknowledgement تلگرام انجام می‌شود.
        await callback.answer("در حال پخش نقش‌ها…")

        try:
            assignments = await assign_roles(session, game)
            # role_messages فقط داده‌های انتساب را می‌خواند و قبل از تغییر وضعیت بازی
            # ساخته می‌شود تا در صورت خطا، بازی ناخواسته وارد مرحله running نشود.
            group_list, private_messages = await role_messages(session, game, assignments)
        except Exception:
            await session.rollback()
            await callback.message.answer(
                "پخش نقش انجام نشد. لطفاً دوباره تلاش کنید؛ وضعیت بازی به مرحله انتظار باقی ماند."
            )
            raise

        game.status = "running"
        game.phase = "setup"
        await session.commit()

        sent = 0
        failed = []
        for telegram_id, text in private_messages:
            try:
                await callback.bot.send_message(telegram_id, text)
                sent += 1
            except Exception:
                failed.append(telegram_id)

        try:
            await callback.message.delete()
        except Exception:
            pass
        failed = list(dict.fromkeys(failed))
        try:
            await callback.bot.send_message(
                callback.message.chat.id,
                "🎭 نقش‌ها پخش شد.\n\nمرحله آماده‌سازی دور آغاز شد.",
                reply_markup=leader_settings_keyboard(game.game_key, game),
            )
        except Exception:
            pass
        if failed:
            try:
                await callback.bot.send_message(
                    callback.message.chat.id,
                    f"ارسال نقش برای {sent} بازیکن موفق بود؛ PV {len(failed)} بازیکن در دسترس نبود.",
                )
            except Exception:
                pass


@router.callback_query(lambda c: c.data and c.data.startswith("leader:menu:"))
async def leader_menu_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load_game(session, key)
        host = await session.get(User, game.host_user_id) if game else None
        if not game or game.status != "running" or game.phase != "setup" or not host or host.telegram_id != callback.from_user.id:
            await callback.answer("دسترسی ندارید یا مرحله انتخاب سردست تمام شده است.", show_alert=True)
            return
        players = await GameRepository.players(session, game.id)
        await callback.message.edit_text("👑 انتخاب سردست\n\nروش انتخاب را مشخص کنید:", reply_markup=leader_choice_keyboard(game.game_key, players))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("leader:manual:"))
async def leader_manual_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load_game(session, key)
        host = await session.get(User, game.host_user_id) if game else None
        if not game or game.status != "running" or game.phase != "setup" or not host or host.telegram_id != callback.from_user.id:
            await callback.answer("دسترسی ندارید یا مرحله انتخاب سردست تمام شده است.", show_alert=True)
            return
        players = await GameRepository.players(session, game.id)
        await callback.message.edit_text("✋ انتخاب دستی سردست\n\nبازیکن موردنظر را انتخاب کنید:", reply_markup=leader_players_keyboard(game.game_key, players))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("leader:pick:"))
async def leader_pick_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    key, user_id_raw = parts[2], parts[3]
    try:
        leader_user_id = int(user_id_raw)
    except ValueError:
        await callback.answer("بازیکن نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        game = await _load_game(session, key)
        host = await session.get(User, game.host_user_id) if game else None
        if not game or game.status != "running" or game.phase != "setup" or not host or host.telegram_id != callback.from_user.id:
            await callback.answer("دسترسی ندارید یا مرحله انتخاب سردست تمام شده است.", show_alert=True)
            return
        try:
            result = await choose_leader(session, game, leader_user_id)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        leader = await session.get(User, result["leader_user_id"])
        name = tg_name(leader.display_name or leader.first_name or "بازیکن") if leader else "بازیکن"
        await callback.message.edit_text(
            f"👑 سردست انتخاب شد: {name}\n\nتنظیمات را بررسی کنید و سپس «شروع دور» را بزنید.",
            reply_markup=leader_settings_keyboard(game.game_key, game, True),
        )
    await callback.answer("سردست انتخاب شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("leader:back:"))
async def leader_back_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load_game(session, key)
        host = await session.get(User, game.host_user_id) if game else None
        if not game or not host or host.telegram_id != callback.from_user.id:
            await callback.answer("دسترسی ندارید.", show_alert=True)
            return
        await callback.message.edit_text("🎭 آماده شروع دور است.", reply_markup=leader_settings_keyboard(game.game_key, game, True))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("leader:auto:"))
async def leader_selection_handler(callback: CallbackQuery) -> None:
    if not callback.from_user:
        return
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load_game(session, key)
        if not game or game.status != "running" or game.phase != "setup":
            await callback.answer("مرحله انتخاب سردست تمام شده است.", show_alert=True)
            return
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        if not host or host.telegram_id != callback.from_user.id:
            await callback.answer("فقط گرداننده می‌تواند سردست را انتخاب کند.", show_alert=True)
            return
        try:
            result = await choose_leader(session, game, None)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        leader = await session.get(User, result["leader_user_id"])
        await callback.message.edit_text(
            f"👑 سردست به‌صورت خودکار انتخاب شد: {tg_name(leader.display_name or leader.first_name or 'بازیکن') if leader else 'بازیکن'}\n\n"
            "تنظیمات را بررسی کنید و سپس «شروع دور» را بزنید.",
            reply_markup=leader_settings_keyboard(game.game_key, game, True),
        )
        await callback.answer("سردست انتخاب شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("round:back:"))
async def round_back_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load_game(session, key)
        host = await session.get(User, game.host_user_id) if game else None
        if not game or not host or host.telegram_id != callback.from_user.id:
            await callback.answer("دسترسی ندارید.", show_alert=True)
            return
        await callback.message.edit_text(
            "👑 سردست انتخاب شده است.\n\nتنظیمات را بررسی کنید و سپس «شروع دور» را بزنید.",
            reply_markup=leader_settings_keyboard(game.game_key, game, True),
        )
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("round:settings:"))
async def round_settings_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load_game(session, key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        if not host or host.telegram_id != callback.from_user.id:
            await callback.answer("فقط گرداننده می‌تواند تنظیمات بازی را تغییر دهد.", show_alert=True)
            return
        from app.handlers.keyboards import game_features_menu
        await callback.message.edit_text(
            "⚙️ تنظیمات بازی",
            reply_markup=game_features_menu(
                game.group_id,
                game.challenge_enabled,
                game.challenge_mode,
                game.next_host_enabled,
                game.next_player_enabled,
                game.next_auto_enabled,
                game.auto_silence_warnings,
                game.auto_kick_warnings,
                game.turn_seconds,
                game.challenge_seconds,
                game.extra_challenge_seconds,
                back_callback=f"round:back:{game.game_key}",
            ),
        )
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("round:toggle_"))
async def round_toggle_handler(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3 or not callback.from_user:
        return
    action, key = parts[1], parts[2]
    async with session_factory() as session:
        game = await _load_game(session, key)
        host = await session.get(User, game.host_user_id) if game and game.host_user_id else None
        if not game or game.status != "running" or game.phase != "setup":
            await callback.answer("تنظیمات این مرحله دیگر قابل تغییر نیست.", show_alert=True)
            return
        if not host or host.telegram_id != callback.from_user.id:
            await callback.answer("فقط گرداننده می‌تواند تنظیمات شروع دور را تغییر دهد.", show_alert=True)
            return
        if action == "toggle_challenge":
            game.challenge_enabled = not game.challenge_enabled
        elif action == "toggle_host_next":
            game.next_host_enabled = not game.next_host_enabled
        elif action == "toggle_player_next":
            game.next_player_enabled = not game.next_player_enabled
        elif action == "toggle_auto_next":
            game.next_auto_enabled = not game.next_auto_enabled
        else:
            await callback.answer("تنظیم نامعتبر است.", show_alert=True)
            return
        await session.commit()
        from app.handlers.keyboards import leader_settings_keyboard
        await callback.message.edit_reply_markup(reply_markup=leader_settings_keyboard(game.game_key, game, True))
    await callback.answer("تنظیم ذخیره شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("round:start:"))
async def round_start_handler(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load_game(session, key)
        host = await session.get(User, game.host_user_id) if game and game.host_user_id else None
        if not game or game.status != "running":
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        if not host or host.telegram_id != callback.from_user.id:
            await callback.answer("فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True)
            return
        try:
            result = await start_round(session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return

        leader = await session.get(User, result["leader_user_id"])
        turn = await __import__("app.services.gameplay", fromlist=["current_turn"]).current_turn(
            session, game.id
        )
        try:
            await callback.message.edit_text(
                f"▶️ دور {result['round_no']} شروع شد.\n"
                f"👑 سردست: {tg_name(leader.display_name if leader else 'بازیکن')}\n\n"
                "🗣 نوبت صحبت‌ها آغاز شد.",
                reply_markup=None,
            )
        except Exception:
            pass

        group = await session.get(Group, game.group_id)
        if group:
            from app.handlers.gameplay import update_round_roster, update_main_roster, _send_turn_message, _schedule_auto_next
            await update_main_roster(callback.bot, session, game, group.telegram_id)
            await update_round_roster(callback.bot, session, game, group.telegram_id)
            if turn:
                await _send_turn_message(callback.bot, session, game, group.telegram_id, turn)
                await _schedule_auto_next(callback.bot, game.game_key, group.telegram_id)
    await callback.answer("دور شروع شد.")
@router.callback_query(lambda c: c.data and c.data.startswith("gameadmin:lobby:"))
async def lobby_game_management(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    game_key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        group = await session.get(Group, game.group_id)
        if not group:
            await callback.answer("گروه پیدا نشد.", show_alert=True)
            return
        member = await callback.bot.get_chat_member(group.telegram_id, callback.from_user.id)
        if member.status not in ("creator", "administrator"):
            await callback.answer("این بخش فقط برای مدیران گروه است.", show_alert=True)
            return
        from app.handlers.keyboards import active_game_menu
        waiting = game.status == "waiting"
        await callback.message.edit_text(
            f"مدیریت بازی فعال\nگروه: {group.title}",
            reply_markup=active_game_menu(
                group.id,
                back_callback=f"groupmgmt:select:games:{group.id}",
                game_key=game.game_key,
                lobby_editable=waiting,
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("groupadmin:lobby:"))
async def lobby_group_management(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    game_key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        group = await session.get(Group, game.group_id)
        if not group:
            await callback.answer("گروه پیدا نشد.", show_alert=True)
            return
        member = await callback.bot.get_chat_member(group.telegram_id, callback.from_user.id)
        if member.status not in ("creator", "administrator"):
            await callback.answer("این بخش فقط برای مدیران گروه است.", show_alert=True)
            return
        from app.handlers.keyboards import group_management_menu
        await callback.message.edit_text(
            "مدیریت گروه",
            reply_markup=group_management_menu(f"groupadmin:lobby:{game.game_key}"),
        )
    await callback.answer()
