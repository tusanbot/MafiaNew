from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import desc, func, select
import json

from app.db.models import Game, GameEvent, GamePlayer, Group, GroupSettings, Role, Scenario, User, Vote
from app.db.session import session_factory
from app.handlers.keyboards import (
    active_game_menu,
    bot_settings_menu,
    game_extras_menu,
    game_features_menu,
    group_game_menu,
    group_list_keyboard,
    group_lock_keyboard,
    group_management_menu,
    main_menu,
    player_management_menu,
    player_target_management_keyboard,
    ranking_menu,
    scenario_keyboard,
)
from app.repositories.games import GameRepository
from app.repositories.users import UserRepository
from app.services.game import create_game
from app.services.profile import sync_telegram_user
from app.services.gameplay import current_round

router = Router(name="menu")


async def _is_group_admin(bot, group: Group, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(group.telegram_id, user_id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


async def _bot_is_active(bot, group: Group) -> bool:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(group.telegram_id, me.id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False


async def _manageable_groups(session, bot, user_id: int) -> list[Group]:
    result = await session.execute(
        select(Group).where(Group.is_active.is_(True), Group.registered_at.is_not(None)).order_by(Group.title)
    )
    groups = []
    for group in result.scalars().all():
        if await _is_group_admin(bot, group, user_id) and await _bot_is_active(bot, group):
            groups.append(group)
    return groups


async def _selected_group(session, bot, user_id: int, group_id: int) -> Group | None:
    group = await session.get(Group, group_id)
    if not group or not group.is_active or group.registered_at is None:
        return None
    if not await _is_group_admin(bot, group, user_id):
        return None
    if not await _bot_is_active(bot, group):
        return None
    return group


def _emoji_settings(game) -> dict:
    defaults = {"death": True, "kick": True, "challenge": True, "silence": True, "extra_turn": True, "warning": True}
    try:
        value = json.loads(game.emoji_settings or "{}")
        defaults.update({k: bool(v) for k, v in value.items() if k in defaults})
    except (TypeError, ValueError):
        pass
    return defaults


def _player_label(player, user, emojis: dict) -> str:
    name = user.display_name or user.first_name or user.username or str(user.telegram_id)
    marks = []
    if not player.is_reserved:
        if not player.alive and player.exit_type == "death" and emojis.get("death", True):
            marks.append("💀")
        elif not player.alive and player.exit_type == "kick" and emojis.get("kick", True):
            marks.append("⛔")
        elif not player.alive and player.exit_type == "faceoff" and emojis.get("death", True):
            marks.append("🎭")
        elif not player.alive and player.exit_type == "slaughter" and emojis.get("death", True):
            marks.append("🩸")
        if player.alive and player.silence_until_round is not None and emojis.get("silence", True):
            marks.append("🔇")
        if player.alive and player.extra_turn_round is not None and emojis.get("extra_turn", True):
            marks.append("➕")
        if player.warning_count and emojis.get("warning", True):
            marks.append(f"⚠️{player.warning_count}")
    return f"{' '.join(marks)} {name}".strip()


@router.callback_query(lambda c: c.data == "menu:root")
async def menu_root(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.edit_text("منوی اصلی", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:group_management")
async def menu_group_management(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.edit_text(
        "مدیریت گروه\n\nبخش موردنظر را انتخاب کنید.",
        reply_markup=group_management_menu(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "groupmgmt:games")
async def group_management_games(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        groups = await _manageable_groups(session, callback.bot, callback.from_user.id)
        if not groups:
            text = "هیچ گروه فعالی پیدا نشد که هم شما مدیر آن باشید و هم ربات در آن فعال باشد."
            await callback.message.edit_text(text, reply_markup=group_management_menu())
        else:
            await callback.message.edit_text(
                "گروه موردنظر را برای مدیریت بازی انتخاب کنید:",
                reply_markup=group_list_keyboard(groups, "games"),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data == "groupmgmt:locks")
async def group_management_locks(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        groups = await _manageable_groups(session, callback.bot, callback.from_user.id)
        if not groups:
            await callback.message.edit_text(
                "گروه فعالی برای مدیریت قفل‌ها پیدا نشد.",
                reply_markup=group_management_menu(),
            )
        else:
            await callback.message.edit_text(
                "گروه موردنظر را برای تنظیم قفل‌ها انتخاب کنید:",
                reply_markup=group_list_keyboard(groups, "locks"),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("groupmgmt:select:"))
async def select_group(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    purpose = parts[2] if len(parts) == 4 else "games"
    group_id = int(parts[-1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت این گروه تأیید نشد.", show_alert=True)
            return
        if purpose == "locks":
            settings = (await session.execute(
                select(GroupSettings).where(GroupSettings.group_id == group.id)
            )).scalar_one_or_none()
            if settings is None:
                settings = GroupSettings(group_id=group.id)
                session.add(settings)
                await session.commit()
            await callback.message.edit_text(
                f"قفل‌های گروه «{group.title or group.telegram_id}»",
                reply_markup=group_lock_keyboard(group.id, settings),
            )
        else:
            await callback.message.edit_text(
                f"گروه: {group.title or group.telegram_id}\n\nبخش موردنظر را انتخاب کنید.",
                reply_markup=group_game_menu(group.id),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("groupmgmt:locks:"))
async def legacy_group_locks(callback: CallbackQuery) -> None:
    await callback.answer("این بخش در نسخه جدید از منوی قفل گروه قابل دسترسی است.", show_alert=True)


@router.callback_query(lambda c: c.data.startswith("groupgame:active:"))
async def active_game(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.message.edit_text(
                f"گروه: {group.title}\n\nدر حال حاضر بازی فعالی وجود ندارد.",
                reply_markup=group_game_menu(group.id),
            )
        else:
            scenario = await session.get(Scenario, game.scenario_id)
            await callback.message.edit_text(
                f"گروه: {group.title}\n\nبازی فعال\n"
                f"سناریو: {scenario.name_fa if scenario else 'نامشخص'}\n"
                f"وضعیت: {game.status}\nمرحله: {game.phase}",
                reply_markup=active_game_menu(group.id, f"gameadmin:lobby:{game.game_key}" if callback.message.chat.type in ("group", "supergroup") else f"gameadmin:active:{group.id}"),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("groupgame:history:"))
async def game_history(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        result = await session.execute(
            select(Game, Scenario)
            .join(Scenario, Scenario.id == Game.scenario_id)
            .where(Game.group_id == group.id)
            .order_by(desc(Game.id))
            .limit(10)
        )
        rows = list(result.all())
        if not rows:
            text = f"تاریخچه بازی‌های «{group.title}»\n\nهنوز بازی‌ای ثبت نشده است."
        else:
            lines = [f"تاریخچه بازی‌های «{group.title}»", ""]
            for game, scenario in rows:
                lines.append(
                    f"#{game.id} — {scenario.name_fa} — {game.status} — {game.phase}"
                )
            text = "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=group_game_menu(group.id))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("grouplock:toggle:"))
async def toggle_group_lock(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    _, _, group_id_raw, field = callback.data.split(":", 3)
    group_id = int(group_id_raw)
    if field not in {"chat_lock", "night_lock", "turn_lock"}:
        await callback.answer("تنظیم نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        settings = (await session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group.id)
        )).scalar_one_or_none()
        if settings is None:
            settings = GroupSettings(group_id=group.id)
            session.add(settings)
        setattr(settings, field, not bool(getattr(settings, field)))
        await session.commit()
        await callback.message.edit_text(
            f"قفل‌های گروه «{group.title}»",
            reply_markup=group_lock_keyboard(group.id, settings),
        )
    await callback.answer("تنظیم قفل به‌روزرسانی شد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:active:"))
async def active_game_menu_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        await callback.message.edit_text(
            f"مدیریت بازی فعال\nگروه: {group.title}",
            reply_markup=active_game_menu(group.id),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:info:"))
async def game_info(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.message.edit_text("بازی فعالی وجود ندارد.", reply_markup=active_game_menu(group.id))
        else:
            scenario = await session.get(Scenario, game.scenario_id)
            players = await GameRepository.players(session, game.id)
            host = await session.get(User, game.host_user_id) if game.host_user_id else None
            player_lines = "\n".join(
                f"{p.seat}. {u.display_name or u.first_name}" for p, u in players
            ) or "بدون بازیکن"
            await callback.message.edit_text(
                f"اطلاعات بازی\n\n"
                f"شناسه: {game.game_key}\n"
                f"سناریو: {scenario.name_fa if scenario else 'نامشخص'}\n"
                f"وضعیت: {game.status}\nمرحله: {game.phase}\n"
                f"گرداننده: {host.display_name if host else 'نامشخص'}\n\n"
                f"بازیکنان:\n{player_lines}",
                reply_markup=active_game_menu(group.id, f"gameadmin:lobby:{game.game_key}" if callback.message.chat.type in ("group", "supergroup") else f"gameadmin:active:{group.id}"),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:players:"))
async def player_management(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.message.edit_text("بازی فعالی وجود ندارد.", reply_markup=group_game_menu(group.id))
            return
        players = await GameRepository.players(session, game.id, include_reserve=True)
        emojis = _emoji_settings(game)
        lines = []
        for player, user in players:
            if player.is_reserved:
                lines.append(f"رزرو {player.reserve_position}. {user.display_name or user.first_name} — رزرو")
            else:
                status = "زنده" if player.alive else (player.exit_type or "حذف‌شده")
                lines.append(f"{player.seat}. {_player_label(player, user, emojis)} — {status}")
        await callback.message.edit_text(
            "مدیریت بازیکنان\n\n" + ("\n".join(lines) if lines else "بازیکنی در بازی نیست.") +
            "\n\nعملیات موردنظر را انتخاب کنید.",
            reply_markup=player_management_menu(group.id, f"gameadmin:lobby:{game.game_key}" if callback.message.chat.type in ("group", "supergroup") else f"gameadmin:active:{group.id}"),
        )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("gameadmin:features:"))
async def game_features(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.message.edit_text("بازی فعالی وجود ندارد.", reply_markup=active_game_menu(group.id))
            return
        await callback.message.edit_text(
            "تنظیمات بازی\n\n"
            "وضعیت تنظیمات واقعی بازی از دکمه‌های زیر قابل تغییر است.",
            reply_markup=game_features_menu(
                group.id,
                game.challenge_enabled,
                game.challenge_mode,
                game.next_host_enabled,
                game.next_player_enabled,
                game.next_auto_enabled,
                game.auto_silence_warnings,
                game.auto_kick_warnings,
                back_callback=f"gameadmin:lobby:{game.game_key}" if callback.message.chat.type in ("group", "supergroup") else f"gameadmin:active:{group.id}",
            ),
        )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("gameadmin:extras:"))
async def game_extras(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.message.edit_text("بازی فعالی وجود ندارد.", reply_markup=group_game_menu(group.id))
            await callback.answer()
            return
        await callback.message.edit_text(
            "امکانات اضافی بازی\n\n"
            f"بازی خودکار: {'فعال' if game.auto_play else 'غیرفعال'}\n"
            f"رنگ نوبت: {game.turn_color}\n"
            f"رنگ چالش: {game.challenge_color}",
            reply_markup=game_extras_menu(
                group.id,
                game.auto_play,
                game.turn_color,
                game.challenge_color,
                back_callback=f"gameadmin:lobby:{game.game_key}" if callback.message.chat.type in ("group", "supergroup") else f"gameadmin:active:{group.id}",
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:player_action:"))
async def player_action(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("درخواست مدیریت بازیکن نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, action = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        players = await GameRepository.players(session, game.id, include_reserve=True)
        if action == "replace":
            players = [row for row in players if not row[0].is_reserved and row[0].alive]
        elif action == "birthday":
            players = [row for row in players if not row[0].is_reserved and not row[0].alive and row[0].exit_type == "death"]
        else:
            players = [row for row in players if not row[0].is_reserved and row[0].alive]
        if action == "remove" and game.status == "waiting":
            players = [row for row in players if row[0].alive]
        labels = {
            "remove": "حذف بازیکن", "replace": "جایگزین — بازیکن مبدا",
            "silence": "سکوت", "extra_turn": "ترن اضافه", "kick": "کیک از بازی",
            "warning": "ثبت تذکر", "birthday": "تولد", "faceoff": "فیس آف — بازیکن مبدا", "slaughter": "سلاخی",
        }
        if action == "remove" and game.status == "running":
            labels["remove"] = "حذف / کشتن بازیکن"
        await callback.message.edit_text(
            f"{labels.get(action, action)}\n\nبازیکن موردنظر را انتخاب کنید:",
            reply_markup=player_target_management_keyboard(group.id, action, players),
        )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("gameadmin:player_target:"))
async def player_target_action(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("درخواست بازیکن نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, action, user_raw = parts
    group_id, target_id = int(group_raw), int(user_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        target = (await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == target_id))).scalar_one_or_none() if game else None
        target_user = await session.get(User, target_id)
        actor = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
        if not game or not target or not target_user:
            await callback.answer("بازیکن پیدا نشد.", show_alert=True)
            return

        if action == "replace":
            if game.status not in ("waiting", "running"):
                await callback.answer("جایگزینی در این وضعیت بازی ممکن نیست.", show_alert=True)
                return
            if not target.alive:
                await callback.answer("بازیکن مبدا باید زنده باشد.", show_alert=True)
                return
            reserves = await GameRepository.reserves(session, game.id)
            await callback.message.edit_text(
                f"بازیکن مبدا: {target_user.display_name or target_user.first_name}\n\nبازیکن مقصد از لیست رزرو را انتخاب کنید:",
                reply_markup=__import__("app.handlers.keyboards", fromlist=["player_replace_destination_keyboard"]).player_replace_destination_keyboard(group.id, target_id, reserves),
            )
            await callback.answer()
            return

        if action == "remove":
            if game.status == "waiting":
                await session.delete(target)
                await session.commit()
                message = "بازیکن از لیست بازی حذف شد."
            elif game.status == "running" and target.alive:
                target.alive = False
                target.exit_type = "death"
                await session.commit()
                message = "بازیکن به لیست کشته‌شده‌ها منتقل شد."
            else:
                await callback.answer("این بازیکن قابل حذف نیست.", show_alert=True)
                return
        elif action == "birthday":
            if game.status != "running" or target.alive or target.exit_type != "death":
                await callback.answer("فقط بازیکنانی که با حذف/مرگ از بازی خارج شده‌اند قابل تولد هستند.", show_alert=True)
                return
            target.alive = True
            target.exit_type = None
            target.silence_until_round = None
            target.extra_turn_round = None
            await session.commit()
            message = "بازیکن با صندلی و نقش قبلی به بازی برگشت."
        elif game.status != "running":
            await callback.answer("این عملیات فقط در بازی در حال اجرا قابل استفاده است.", show_alert=True)
            return
        else:
            round_no = await current_round(session, game.id)
            if action == "silence":
                target.silence_until_round = round_no
                event_type, message = "silence", "بازیکن تا پایان این دور سکوت شد."
            elif action == "extra_turn":
                target.extra_turn_round = round_no
                queue_event = (await session.execute(
                    select(GameEvent).where(GameEvent.game_id == game.id, GameEvent.event_type == "turn_queue").order_by(GameEvent.id.desc())
                )).scalars().first()
                if queue_event:
                    queue_data = json.loads(queue_event.payload or "{}")
                    queue_data.setdefault("queue", [])
                    queue_data.setdefault("extra_turn_users", [])
                    if target_id not in queue_data["extra_turn_users"]:
                        queue_data["queue"].append(target_id)
                        queue_data["extra_turn_users"].append(target_id)
                    queue_event.payload = json.dumps(queue_data, ensure_ascii=False)
                event_type, message = "extra_turn_granted", "ترن اضافه برای پایان این دور ثبت شد."
            elif action == "kick":
                target.alive, target.exit_type = False, "kick"
                event_type, message = "player_kicked", "بازیکن کیک شد و امکان تولد ندارد."
            elif action == "slaughter":
                target.alive, target.exit_type = False, "slaughter"
                event_type, message = "slaughter", "بازیکن سلاخی شد و امکان تولد ندارد."
            elif action == "faceoff":
                await callback.message.edit_text(
                    f"بازیکن مبدا: {target_user.display_name or target_user.first_name}\n\nبازیکن مقصد را انتخاب کنید:",
                    reply_markup=__import__("app.handlers.keyboards", fromlist=["player_faceoff_destination_keyboard"]).player_faceoff_destination_keyboard(group.id, target_id, [
                        row for row in await GameRepository.players(session, game.id) if row[0].alive and row[0].user_id != target_id
                    ]),
                )
                await callback.answer()
                return
            elif action == "warning":
                target.warning_count += 1
                penalty = min(target.warning_count, 5)
                target_user.score -= penalty
                event_type, message = "warning", f"تذکر {target.warning_count} ثبت شد؛ {penalty}- امتیاز."
                if target.warning_count >= 3:
                    target_vote = {"vote_blocked": True}
                    if game.auto_silence_warnings and target.warning_count >= 4:
                        target.silence_until_round = round_no + 1
                        target_vote["auto_silence"] = True
                    if game.auto_kick_warnings and target.warning_count >= 5:
                        target.alive, target.exit_type = False, "kick"
                        target_vote["auto_kick"] = True
                else:
                    target_vote = {}
            else:
                await callback.answer("عملیات نامعتبر است.", show_alert=True)
                return
            payload = {"user_id": target_id, "round_no": round_no, "active": True, "warning_count": target.warning_count}
            if action == "warning":
                payload.update(target_vote)
            session.add(GameEvent(game_id=game.id, actor_user_id=actor.id if actor else None, event_type=event_type, payload=json.dumps(payload, ensure_ascii=False)))
            await session.commit()
        await callback.message.edit_text(f"مدیریت بازیکنان\n\n{message}", reply_markup=player_management_menu(group.id))
    await callback.answer(message)



@router.callback_query(lambda c: c.data.startswith("gameadmin:faceoff_to:"))
async def faceoff_to(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("درخواست فیس‌آف نامعتبر است.", show_alert=True)
        return
    _, _, _, group_raw, dest_raw = parts
    # callback shape: gameadmin:faceoff_to:group:source:destination
    source_raw = parts[3]
    group_id, source_id, dest_id = int(parts[2]), int(source_raw), int(dest_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.status != "running":
            await callback.answer("فیس‌آف فقط در بازی در حال اجرا انجام می‌شود.", show_alert=True)
            return
        source = (await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == source_id))).scalar_one_or_none()
        dest = (await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == dest_id))).scalar_one_or_none()
        if not source or not dest or not source.alive or not dest.alive:
            await callback.answer("بازیکن مبدا یا مقصد معتبر نیست.", show_alert=True)
            return
        source_role, dest_role = source.role_id, dest.role_id
        source.role_id = dest_role
        dest.role_id = source_role
        source.alive, source.exit_type = False, "faceoff"
        round_no = await current_round(session, game.id)
        actor = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
        session.add(GameEvent(game_id=game.id, actor_user_id=actor.id if actor else None, event_type="faceoff", payload=json.dumps({"source_user_id": source_id, "destination_user_id": dest_id, "round_no": round_no}, ensure_ascii=False)))
        await session.commit()
        source_user, dest_user = await session.get(User, source_id), await session.get(User, dest_id)
        await callback.bot.send_message(group.telegram_id, f"فیس‌آف انجام شد: نقش {source_user.display_name or source_user.first_name} و {dest_user.display_name or dest_user.first_name} جابه‌جا شد.")
        await callback.message.edit_text("فیس‌آف با موفقیت انجام شد.", reply_markup=player_management_menu(group.id))
    await callback.answer("فیس‌آف انجام شد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:player_replace_to:"))
async def player_replace_to(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("درخواست جایگزینی نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, source_raw, dest_raw = parts
    group_id, source_id, dest_id = int(group_raw), int(source_raw), int(dest_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.status != "waiting":
            await callback.answer("جایگزینی در این وضعیت بازی ممکن نیست.", show_alert=True)
            return
        source = (await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == source_id))).scalar_one_or_none()
        dest = (await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == dest_id))).scalar_one_or_none()
        source_user, dest_user = await session.get(User, source_id), await session.get(User, dest_id)
        if not source or not dest or not dest.is_reserved:
            await callback.answer("بازیکن مبدا یا مقصد معتبر نیست.", show_alert=True)
            return
        seat = source.seat
        ok = await GameRepository.replace_player(session, game, source, dest)
        if not ok:
            await callback.answer("عملیات جایگزینی انجام نشد.", show_alert=True)
            return
        chat_id = group.telegram_id
        await callback.bot.send_message(chat_id, f"جایگزینی انجام شد: {source_user.display_name or source_user.first_name} ← {dest_user.display_name or dest_user.first_name}\nصندلی: {seat}")
        await callback.message.edit_text("جایگزینی با موفقیت انجام شد.", reply_markup=player_management_menu(group.id))
    await callback.answer("جایگزینی انجام شد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:cancel_confirm:"))
async def cancel_game_confirm(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        await session.execute(Vote.__table__.delete().where(Vote.game_id == game.id))
        await session.execute(GameEvent.__table__.delete().where(GameEvent.game_id == game.id))
        await session.execute(GamePlayer.__table__.delete().where(GamePlayer.game_id == game.id))
        await session.delete(game)
        await session.commit()
        await callback.message.edit_text("بازی به‌طور کامل لغو و اطلاعات آن پاک شد.", reply_markup=group_game_menu(group.id))
    await callback.answer("بازی لغو شد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:finish_result:"))
async def finish_game_result(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("نتیجه نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, winner = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.status != "running":
            await callback.answer("بازی در حال اجرا پیدا نشد.", show_alert=True)
            return
        from app.services.gameplay import finalize_game
        try:
            await finalize_game(session, game, winner)
            await session.commit()
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        rows = await session.execute(
            select(GamePlayer, User, Role)
            .outerjoin(Role, Role.id == GamePlayer.role_id)
            .join(User, User.id == GamePlayer.user_id)
            .where(GamePlayer.game_id == game.id)
            .order_by(GamePlayer.seat)
        )
        labels = {"citizen": "برد شهروند", "mafia": "برد مافیا", "independent": "برد مستقل", "citizen_independent": "برد شهروند/مستقل", "draw": "مساوی"}
        lines = [f"پایان بازی — {labels.get(winner, winner)}", ""]
        for player, user, role in rows.all():
            state = "زنده" if player.alive else player.exit_type or "حذف‌شده"
            lines.append(f"{player.seat}. {user.display_name or user.first_name} — {role.name_fa if role else 'بدون نقش'} — {state}")
        await callback.message.edit_text("\n".join(lines), reply_markup=group_game_menu(group.id))
    await callback.answer("نتیجه بازی ثبت شد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:emoji:"))
async def emoji_management(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        from app.handlers.keyboards import emoji_management_menu
        await callback.message.edit_text("مدیریت اموجی‌های وضعیت بازیکنان و بازی", reply_markup=emoji_management_menu(group.id, _emoji_settings(game)))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:emoji_toggle:"))
async def emoji_toggle(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("تنظیم اموجی نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, key = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        settings = _emoji_settings(game)
        if key not in settings:
            await callback.answer("اموجی نامعتبر است.", show_alert=True)
            return
        settings[key] = not settings[key]
        game.emoji_settings = json.dumps(settings, ensure_ascii=False)
        await session.commit()
        from app.handlers.keyboards import emoji_management_menu
        await callback.message.edit_text("مدیریت اموجی‌های وضعیت بازیکنان و بازی", reply_markup=emoji_management_menu(group.id, settings))
    await callback.answer("تنظیم اموجی ذخیره شد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:feature:"))
async def game_feature_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("تنظیم بازی نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, action = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        if action == "cancel":
            await callback.message.edit_text("آیا از لغو واقعی بازی مطمئن هستید؟", reply_markup=__import__("app.handlers.keyboards", fromlist=["cancel_game_keyboard"]).cancel_game_keyboard(group.id))
            await callback.answer()
            return
        if action == "finish":
            await callback.message.edit_text("نتیجه نهایی را انتخاب کنید:", reply_markup=__import__("app.handlers.keyboards", fromlist=["finish_game_keyboard"]).finish_game_keyboard(group.id))
            await callback.answer()
            return
        if action == "challenge":
            if not game.challenge_enabled:
                game.challenge_enabled = True
                game.challenge_mode = "limited"
            elif game.challenge_mode == "limited":
                game.challenge_mode = "free"
            else:
                game.challenge_enabled = False
        elif action == "next_host":
            game.next_host_enabled = not game.next_host_enabled
        elif action == "next_player":
            game.next_player_enabled = not game.next_player_enabled
        elif action == "next_auto":
            game.next_auto_enabled = not game.next_auto_enabled
        elif action == "auto_silence":
            game.auto_silence_warnings = not game.auto_silence_warnings
        elif action == "auto_kick":
            game.auto_kick_warnings = not game.auto_kick_warnings
        else:
            await callback.answer("تنظیم نامعتبر است.", show_alert=True)
            return
        await session.commit()
        await callback.message.edit_text(
            "تنظیمات بازی",
            reply_markup=game_features_menu(
                group.id, game.challenge_enabled, game.challenge_mode, game.next_host_enabled, game.next_player_enabled,
                game.next_auto_enabled, game.auto_silence_warnings, game.auto_kick_warnings
            ),
        )
    await callback.answer("تنظیم ذخیره شد.")

@router.callback_query(lambda c: c.data.startswith("gameadmin:extra:"))
async def game_extra_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("تنظیم اضافی نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, action = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        colors = ["پیش‌فرض", "سبز", "آبی", "بنفش", "قرمز", "طلایی"]
        if action == "auto_play":
            game.auto_play = not game.auto_play
        elif action == "turn_color_enabled":
            game.turn_color_enabled = not game.turn_color_enabled
        elif action == "turn_color":
            game.turn_color = colors[(colors.index(game.turn_color) + 1) % len(colors)] if game.turn_color in colors else colors[0]
        elif action == "challenge_color":
            game.challenge_color = colors[(colors.index(game.challenge_color) + 1) % len(colors)] if game.challenge_color in colors else colors[0]
        else:
            await callback.answer("امکان اضافی نامعتبر است.", show_alert=True)
            return
        await session.commit()
        await callback.message.edit_text(
            "امکانات اضافی بازی",
            reply_markup=game_extras_menu(group.id, game.auto_play, game.turn_color, game.challenge_color, game.turn_color_enabled),
        )
    await callback.answer("تنظیم ذخیره شد.")

@router.callback_query(lambda c: c.data == "menu:profile")
async def menu_profile(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    if callback.message.chat.type != "private":
        await callback.answer("پروفایل فقط در PV قابل استفاده است.", show_alert=True)
        return
    async with session_factory() as session:
        user = await sync_telegram_user(session, callback.from_user)
        username = f"@{user.username}" if user.username else "بدون نام کاربری"
        await callback.message.edit_text(
            f"پروفایل\n\nنام: {user.display_name}\n"
            f"نام کاربری: {username}\n\n"
            f"بازی‌ها: {user.games_played}\n"
            f"بردها: {user.games_won}\n"
            f"چالش‌ها: {user.challenges}",
            reply_markup=main_menu(),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:scenarios")
async def menu_scenarios(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.edit_text("سناریوهای فعال را انتخاب کنید.", reply_markup=scenario_keyboard())
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:bot_settings")
async def bot_settings(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.edit_text(
        "تنظیمات ربات\n\nتنظیمات عمومی و اعلان‌ها از این بخش مدیریت می‌شوند.",
        reply_markup=bot_settings_menu(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("botsettings:"))
async def bot_settings_placeholder(callback: CallbackQuery) -> None:
    await callback.answer("این بخش برای اتصال تنظیمات واقعی آماده شده و گزینه‌های آن در نسخه بعدی تکمیل می‌شوند.", show_alert=True)


@router.callback_query(lambda c: c.data == "menu:ranking")
async def ranking(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    if callback.message.chat.type != "private":
        await callback.answer("رتبه‌بندی فقط در PV قابل استفاده است.", show_alert=True)
        return
    await callback.message.edit_text("رتبه بندی", reply_markup=ranking_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("ranking:"))
async def ranking_list(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    if callback.message.chat.type != "private":
        await callback.answer("رتبه‌بندی فقط در PV قابل استفاده است.", show_alert=True)
        return
    kind = callback.data.rsplit(":", 1)[1]
    async with session_factory() as session:
        if kind == "mafia":
            order_column = User.mafia_wins
            title = "برترین مافیا"
        elif kind == "citizen":
            order_column = User.citizen_wins
            title = "برترین شهروند"
        else:
            order_column = User.games_won
            title = "بازیکنان برتر"
        result = await session.execute(
            select(User).where(User.is_active.is_(True)).order_by(desc(order_column), desc(User.games_played)).limit(10)
        )
        users = result.scalars().all()
        lines = [title, ""]
        if not users:
            lines.append("هنوز داده‌ای برای رتبه‌بندی ثبت نشده است.")
        else:
            for i, user in enumerate(users, 1):
                score = getattr(user, "games_won" if kind == "players" else f"{kind}_wins")
                lines.append(f"{i}. {user.display_name or user.first_name} — {score}")
        await callback.message.edit_text("\n".join(lines), reply_markup=ranking_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:help")
async def menu_help(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.edit_text(
        "راهنما\n\n/newgame — ساخت بازی در گروه\n/profile — مشاهده پروفایل",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "game:create")
async def menu_create_game(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.answer("ساخت بازی باید داخل گروه انجام شود.\nاز /newgame در گروه استفاده کنید.")
    await callback.answer()


async def game_history_text(session, group) -> str:
    result = await session.execute(
        select(Game, Scenario)
        .join(Scenario, Scenario.id == Game.scenario_id)
        .where(Game.group_id == group.id)
        .order_by(desc(Game.id))
        .limit(10)
    )
    rows = list(result.all())
    if not rows:
        return f"تاریخچه بازی‌های «{group.title}»\n\nهنوز بازی‌ای ثبت نشده است."
    lines = [f"تاریخچه بازی‌های «{group.title}»", ""]
    for game, scenario in rows:
        lines.append(f"#{game.id} — {scenario.name_fa} — {game.status} — {game.phase}")
    return "\n".join(lines)


async def _ensure_draft(session, group, telegram_user_id: int):
    # Handler callbacks provide Telegram user IDs, while Game.user_id /
    # Game.host_user_id are foreign keys to the internal users.id INTEGER.
    # Never use a Telegram ID as a users.id lookup.
    user = await UserRepository(session).get_by_telegram_id(telegram_user_id)
    if user is None:
        return None

    draft = await GameRepository.get_draft(session, group.id, user.id)
    if draft:
        return draft

    scenario = (await session.execute(
        select(Scenario).where(Scenario.enabled.is_(True)).order_by(Scenario.id)
    )).scalars().first()
    if not scenario:
        return None
    return await create_game(session, group, scenario, user, status="draft", reserve_enabled=True)


async def render_new_game_menu(session, group, user_id: int | None = None):
    if user_id is not None:
        await _ensure_draft(session, group, user_id)
    internal_user_id = None
    if user_id is not None:
        user = await UserRepository(session).get_by_telegram_id(user_id)
        internal_user_id = user.id if user else None
    draft = await GameRepository.get_draft(session, group.id, internal_user_id)
    if not draft:
        return "امکان ایجاد پیش‌نویس بازی وجود ندارد."
    scenario = await session.get(Scenario, draft.scenario_id)
    host = await session.get(User, draft.host_user_id) if draft.host_user_id else None
    return (
        "ایجاد بازی\n\n"
        f"سناریو: {scenario.name_fa if scenario else 'انتخاب نشده'}\n"
        f"گرداننده: {host.display_name if host else 'انتخاب نشده'}\n"
        f"رزرو: {'فعال' if draft.reserve_enabled else 'غیرفعال'}\n"
        f"بازی خودکار: {'فعال' if draft.auto_play else 'غیرفعال'}"
    )


async def _require_group_admin(callback: CallbackQuery, session, group_id: int):
    if not callback.from_user:
        return None
    group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
    if not group:
        await callback.answer("دسترسی مدیریت گروه تأیید نشد.", show_alert=True)
        return None
    return group


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:menu:"))
async def new_game_menu_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        text = await render_new_game_menu(session, group, callback.from_user.id)
        from app.handlers.keyboards import new_game_menu
        await callback.message.edit_text(text, reply_markup=new_game_menu(group.id))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:scenario:"))
async def new_game_scenario(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        result = await session.execute(select(Scenario).where(Scenario.enabled.is_(True)).order_by(Scenario.id))
        scenarios = result.scalars().all()
        await callback.message.edit_text("انتخاب سناریو", reply_markup=__import__("app.handlers.keyboards", fromlist=["scenario_select_keyboard"]).scenario_select_keyboard(group.id, scenarios))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:setscenario:"))
async def new_game_set_scenario(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4 or parts[0] != "newgame" or parts[1] != "setscenario":
        await callback.answer("درخواست انتخاب سناریو نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, scenario_raw = parts
    try:
        group_id, scenario_id = int(group_raw), int(scenario_raw)
    except ValueError:
        await callback.answer("شناسه سناریو نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        scenario = await session.get(Scenario, scenario_id)
        if not draft or not scenario or not scenario.enabled:
            await callback.answer("سناریو قابل انتخاب نیست.", show_alert=True)
            return
        draft.scenario_id = scenario.id
        await session.commit()
        text = await render_new_game_menu(session, group, callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_menu"]).new_game_menu(group.id))
    await callback.answer("سناریو انتخاب شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:host:"))
async def new_game_host(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        admins = await callback.bot.get_chat_administrators(group.telegram_id)
        await callback.message.edit_text("انتخاب گرداننده", reply_markup=__import__("app.handlers.keyboards", fromlist=["host_select_keyboard"]).host_select_keyboard(group.id, admins))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:sethost:"))
async def new_game_set_host(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4 or parts[0] != "newgame" or parts[1] != "sethost":
        await callback.answer("درخواست انتخاب گرداننده نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, user_raw = parts
    try:
        group_id, host_tid = int(group_raw), int(user_raw)
    except ValueError:
        await callback.answer("شناسه گرداننده نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        try:
            member = await callback.bot.get_chat_member(group.telegram_id, host_tid)
        except Exception:
            await callback.answer("اطلاعات گرداننده از تلگرام قابل دریافت نیست.", show_alert=True)
            return
        if member.status not in ("creator", "administrator"):
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            return
        tg_user = member.user
        host = await UserRepository(session).upsert_from_telegram(
            tg_user.id,
            tg_user.username,
            tg_user.first_name or "",
            tg_user.last_name,
        )
        draft.host_user_id = host.id
        await session.commit()
        text = await render_new_game_menu(session, group, callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_menu"]).new_game_menu(group.id))
    await callback.answer("گرداننده انتخاب شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:settings:"))
async def new_game_settings(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        await callback.message.edit_text(
            "تنظیمات بازی",
            reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_settings_keyboard"]).new_game_settings_keyboard(group.id, draft.reserve_enabled if draft else True),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:toggle_reserve:"))
async def toggle_draft_reserve(callback: CallbackQuery) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        draft.reserve_enabled = not draft.reserve_enabled
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_settings_keyboard"]).new_game_settings_keyboard(group.id, draft.reserve_enabled))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:extras:"))
async def new_game_extras_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        await callback.message.edit_text(
            "امکانات اضافه",
            reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_extras_keyboard"]).new_game_extras_keyboard(group.id, draft.auto_play, draft.turn_color, draft.challenge_color),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:toggle_auto:"))
async def toggle_draft_auto(callback: CallbackQuery) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        draft.auto_play = not draft.auto_play
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_extras_keyboard"]).new_game_extras_keyboard(group.id, draft.auto_play, draft.turn_color, draft.challenge_color))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:turn_color:"))
async def new_game_turn_color(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        from app.handlers.keyboards import new_game_color_keyboard
        await callback.message.edit_text(
            "انتخاب رنگ نوبت",
            reply_markup=new_game_color_keyboard(group.id, "turn", draft.turn_color),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:challenge_color:"))
async def new_game_challenge_color(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        from app.handlers.keyboards import new_game_color_keyboard
        await callback.message.edit_text(
            "انتخاب رنگ چالش",
            reply_markup=new_game_color_keyboard(group.id, "challenge", draft.challenge_color),
        )
    await callback.answer()


async def _set_new_game_color(callback: CallbackQuery, kind: str) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":", 3)
    if len(parts) != 4 or parts[0] != "newgame" or parts[1] not in {"set_turn_color", "set_challenge_color"}:
        await callback.answer("تنظیم رنگ نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, value = parts
    try:
        group_id = int(group_raw)
    except ValueError:
        await callback.answer("شناسه گروه نامعتبر است.", show_alert=True)
        return
    allowed = {"پیش‌فرض", "قرمز", "آبی", "سبز", "زرد", "بنفش"}
    if value not in allowed:
        await callback.answer("رنگ نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        if kind == "turn":
            draft.turn_color = value
        else:
            draft.challenge_color = value
        await session.commit()
        from app.handlers.keyboards import new_game_extras_keyboard
        await callback.message.edit_text(
            "امکانات اضافه",
            reply_markup=new_game_extras_keyboard(
                group.id, draft.auto_play, draft.turn_color, draft.challenge_color
            ),
        )
    await callback.answer("تنظیم ذخیره شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:set_turn_color:"))
async def new_game_set_turn_color(callback: CallbackQuery) -> None:
    await _set_new_game_color(callback, "turn")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:set_challenge_color:"))
async def new_game_set_challenge_color(callback: CallbackQuery) -> None:
    await _set_new_game_color(callback, "challenge")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:create:"))
async def new_game_create(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        active = await GameRepository.get_active(session, group.id)
        if active:
            await callback.answer("این گروه در حال حاضر بازی فعالی دارد.", show_alert=True)
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        scenario = await session.get(Scenario, draft.scenario_id)
        if not scenario:
            await callback.answer("سناریو انتخاب نشده است.", show_alert=True)
            return
        host = await session.get(User, draft.host_user_id)
        if not host:
            await callback.answer("گرداننده انتخاب نشده است.", show_alert=True)
            return
        draft.status = "waiting"
        draft.phase = "lobby"
        await session.commit()
        from app.handlers.keyboards import lobby_keyboard_v2
        text, _ = await __import__("app.services.game", fromlist=["render_lobby"]).render_lobby(session, draft)
        await callback.message.edit_text(text, reply_markup=lobby_keyboard_v2(draft.game_key, scenario, await GameRepository.players(session, draft.id), await GameRepository.reserves(session, draft.id), is_host=callback.from_user.id == host.telegram_id, can_deal=False, reserve_enabled=draft.reserve_enabled))
    await callback.answer("لابی بازی ایجاد شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("groupstart:history:"))
async def group_start_history(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        await callback.message.edit_text(await game_history_text(session, group), reply_markup=__import__("app.handlers.keyboards", fromlist=["group_start_menu"]).group_start_menu(group.id))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:turn_color:"))
async def draft_turn_color(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    colors = ["پیش‌فرض", "سبز", "آبی", "بنفش", "قرمز", "طلایی"]
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        draft.turn_color = colors[(colors.index(draft.turn_color) + 1) % len(colors)] if draft.turn_color in colors else colors[0]
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_extras_keyboard"]).new_game_extras_keyboard(group.id, draft.auto_play, draft.turn_color, draft.challenge_color))
    await callback.answer("رنگ نوبت تغییر کرد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:challenge_color:"))
async def draft_challenge_color(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    colors = ["پیش‌فرض", "سبز", "آبی", "بنفش", "قرمز", "طلایی"]
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        draft.challenge_color = colors[(colors.index(draft.challenge_color) + 1) % len(colors)] if draft.challenge_color in colors else colors[0]
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_extras_keyboard"]).new_game_extras_keyboard(group.id, draft.auto_play, draft.turn_color, draft.challenge_color))
    await callback.answer("رنگ چالش تغییر کرد.")
