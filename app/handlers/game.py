from aiogram import Router
from datetime import datetime
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
from app.handlers.keyboards import leader_selection_keyboard
from app.handlers.keyboards import group_management_menu, lobby_keyboard_v2

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
            await callback.bot.send_message(group.telegram_id, f"بازیکن {user.display_name or user.first_name} وارد لیست جایگزین شد؛ جایگاه رزرو {player.reserve_position}.")
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
        assignments = await assign_roles(session, game)
        game.status = "running"
        game.phase = "setup"
        await session.commit()
        group_list, private_messages = await role_messages(session, game, assignments)
        sent = 0
        failed = []
        for telegram_id, text in private_messages:
            try:
                await callback.bot.send_message(telegram_id, text)
                sent += 1
            except Exception:
                failed.append(telegram_id)
        try:
            players_now = await GameRepository.players(session, game.id)
            await callback.bot.send_message(
                host.telegram_id,
                group_list + "\n\n👑 انتخاب سردست\nسردست به‌صورت دستی یا خودکار انتخاب می‌شود:",
                reply_markup=leader_selection_keyboard(game.game_key, players_now),
            )
        except Exception:
            failed.append(host.telegram_id)
        failed = list(dict.fromkeys(failed))
        if failed:
            await callback.message.answer(
                f"نقش‌ها برای {sent} بازیکن ارسال شد. ارسال خصوصی برای {len(failed)} نفر ناموفق بود؛ آن افراد باید ابتدا ربات را در PV /start کنند."
            )
        else:
            await callback.message.answer("نقش همه بازیکنان در PV ارسال شد.")
    await callback.answer("نقش‌ها پخش شدند.")


@router.callback_query(lambda c: c.data and c.data.startswith("leader:"))
async def leader_selection_handler(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) < 3 or not callback.from_user:
        return
    key = parts[2]
    async with session_factory() as session:
        game = await _load_game(session, key)
        if not game or game.status != "running" or game.phase != "setup":
            await callback.answer("مرحله انتخاب سردست تمام شده است.", show_alert=True)
            return
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        if not host or host.telegram_id != callback.from_user.id:
            await callback.answer("فقط گرداننده می‌تواند سردست را انتخاب کند.", show_alert=True)
            return
        leader_id = None
        if parts[1] == "manual":
            if len(parts) != 4:
                await callback.answer("انتخاب سردست نامعتبر است.", show_alert=True)
                return
            try:
                leader_id = int(parts[3])
            except ValueError:
                await callback.answer("بازیکن نامعتبر است.", show_alert=True)
                return
        elif parts[1] != "auto":
            await callback.answer("نوع انتخاب سردست نامعتبر است.", show_alert=True)
            return
        try:
            result = await choose_leader(session, game, leader_id)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        group = await session.get(Group, game.group_id)
        leader = await session.get(User, result["leader_user_id"])
        if group and leader:
            players = await GameRepository.players(session, game.id)
            names = []
            for player, user in players:
                marker = "👑" if user.id == leader.id else ("🔇" if player.silence_until_round == result["round_no"] else "•")
                names.append(f"{marker} {player.seat:02d}. {user.display_name or user.first_name or 'بازیکن'}")
            from app.handlers.keyboards import leader_settings_keyboard
            await callback.bot.send_message(
                group.telegram_id,
                f"👑 سردست انتخاب شد: {leader.display_name or leader.first_name or 'بازیکن'}\n\n"
                f"👥 لیست بازیکنان حاضر در بازی\n" + "\n".join(names) +
                "\n\nتنظیمات چالش و نکست را بررسی کنید و سپس «شروع دور» را بزنید.",
                reply_markup=leader_settings_keyboard(game.game_key, game),
            )
        await callback.answer("سردست انتخاب شد و دور آغاز شد.")

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
        await callback.message.edit_reply_markup(reply_markup=leader_settings_keyboard(game.game_key, game))
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
        group = await session.get(Group, game.group_id)
        scenario = await session.get(Scenario, game.scenario_id)
        from app.services.gameplay import all_players
        team_names = {"mafia": "مافیا", "citizen": "شهروند", "independent": "مستقل"}
        roster_lines = []
        for player, user, role in await all_players(session, game.id):
            roster_lines.append(
                f"{player.seat:02d} **{user.display_name or user.first_name or 'بازیکن'}** — "
                f"{role.name_fa if role else 'نامشخص'} --------- "
                f"{team_names.get(role.team, role.team) if role else 'نامشخص'}"
            )
        now_tehran = datetime.now(ZoneInfo("Asia/Tehran"))
        jy, jm, jd = gregorian_to_jalali(now_tehran.year, now_tehran.month, now_tehran.day)
        roster = (
            f"༄\n📓 بازی شماره : {game.id}\n\n"
            f"⏱ زمان : {now_tehran:%H:%M}\n"
            f"📆 تاریخ : {jy:04d}/{jm:02d}/{jd:02d}\n"
            f"🗓 سناریو : {scenario.name_fa if scenario else 'نامشخص'}\n"
            f"👮‍♂ گرداننده : {leader.display_name if leader else 'بازیکن'}\n\n"
            "~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n"
            "👥 لیست بازیکنان حاضر در بازی\n"
            "◤◢◣◥◤◢◣◥◤◢◣◥\n" + "\n".join(roster_lines) +
            "\n◤◢◣◥◤◢◣◥◤◢◣◥\n༄"
        )
        from app.handlers.keyboards import day_turn_keyboard
        turn = await __import__("app.services.gameplay", fromlist=["current_turn"]).current_turn(session, game.id)
        try:
            await callback.bot.send_message(
                callback.from_user.id,
                roster + "\n\n▶️ دور شروع شد؛ نوبت صحبت‌ها آغاز شد.",
                reply_markup=day_turn_keyboard(
                    game.game_key, True, game.challenge_enabled, game.turn_color_enabled,
                    game.turn_color, game.challenge_color, True,
                    bool(turn and turn.get("kind") != "extra"),
                ),
            )
        except Exception:
            pass
        if group:
            from app.handlers.keyboards import day_turn_keyboard
            await callback.bot.send_message(
                group.telegram_id,
                f"▶️ دور {result['round_no']} شروع شد.\n"
                f"👑 سردست: {leader.display_name if leader else 'بازیکن'}\n\n"
                "🗣 نوبت صحبت‌ها آغاز شد.",
                reply_markup=day_turn_keyboard(
                    game.game_key, True, game.challenge_enabled, game.turn_color_enabled,
                    game.turn_color, game.challenge_color, True,
                    bool(turn and turn.get("kind") != "extra"),
                ),
            )
            if game.next_auto_enabled:
                from app.handlers.gameplay import _schedule_auto_next
                await _schedule_auto_next(callback.bot, game.game_key)
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
        await callback.message.edit_text(
            f"مدیریت بازی فعال\nگروه: {group.title}",
            reply_markup=active_game_menu(group.id),
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
