from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select, func

from app.db.models import Game, GamePlayer, Role, User
from app.db.session import session_factory
from app.handlers.keyboards import leader_choice_keyboard, leader_settings_keyboard, main_menu
from app.repositories.games import GameRepository
from app.repositories.users import UserRepository
from app.services.game import render_lobby
from app.services.gameplay import choose_leader, start_round
from app.services.profile import sync_telegram_user
from app.services.stats import leaderboard, rank_for_score, rank_progress
from app.utils.text import tg_name

router = Router(name="text_commands")


def _exact(*values: str):
    """Exact text only. Never use startswith/contains for public commands."""
    return F.text.in_(values)


async def _user(session, message: Message):
    tg = message.from_user
    return await UserRepository(session).upsert_from_telegram(
        tg.id, tg.username, tg.first_name or "", tg.last_name
    )


async def _active_game(session, message: Message):
    if message.chat.type not in {"group", "supergroup"}:
        return None
    return await GameRepository.get_active(session, int(message.chat.id))


async def _is_host(session, game, user) -> bool:
    return bool(game and user and game.host_user_id == user.id)


@router.message(_exact("پیوی", "پی وی", "پنل"))
async def text_private_panel(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or await state.get_state():
        return
    await message.answer("👤 پنل شخصی", reply_markup=main_menu())


@router.message(_exact("پروفایل", "profile"))
async def text_profile(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user or await state.get_state():
        return
    async with session_factory() as session:
        user = await sync_telegram_user(
            session, message.from_user.id, message.from_user.username,
            message.from_user.first_name or "", message.from_user.last_name
        )
        position = (await session.scalar(
            select(func.count(User.id)).where(User.is_active.is_(True), User.score > user.score)
        ) or 0) + 1
        rank, next_score, remaining = rank_progress(user.score)
        await session.commit()
    next_text = f"تا رتبه بعد: {remaining} امتیاز" if next_score is not None else "بالاترین رتبه"
    await message.answer(
        "👤 پروفایل بازیکن\n\n"
        f"نام: {tg_name(user.display_name or user.first_name or 'بازیکن')}\n"
        f"رتبه: {rank} • جایگاه: #{position}\n"
        f"امتیاز: {user.score}\n"
        f"بازی‌ها: {user.games_played} • بردها: {user.games_won}\n"
        f"نرخ برد: {(user.games_won / user.games_played * 100) if user.games_played else 0:.1f}%\n"
        f"مافیا: {user.mafia_wins} • شهروند: {user.citizen_wins} • مستقل: {user.independent_wins}\n"
        f"چالش‌ها: {user.challenges} • کیک: {user.kicks}\n"
        f"📊 {next_text}"
    )


@router.message(_exact("رتبه", "رتبه بندی", "رتبه‌بندی", "rank", "ranking"))
async def text_ranking(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or await state.get_state():
        return
    async with session_factory() as session:
        rows = await leaderboard(session, 10, None)
        if not rows:
            await message.answer("🏆 هنوز بازی کاملی برای رتبه‌بندی ثبت نشده است.")
            return
        lines = ["🏆 رتبه‌بندی بازیکنان", ""]
        for i, user in enumerate(rows, 1):
            lines.append(
                f"{i}. {tg_name(user.display_name or user.first_name or 'بازیکن')} — "
                f"{user.score} امتیاز — {rank_for_score(user.score)}"
            )
    await message.answer("\n".join(lines))


@router.message(_exact("نقش", "نقش من", "role", "myrole"))
async def text_role(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user or await state.get_state():
        return
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not user:
            await message.answer("هنوز پروفایلی برای شما ثبت نشده است.")
            return
        player_row = (await session.execute(
            select(GamePlayer).where(
                GamePlayer.user_id == user.id,
                GamePlayer.is_reserved.is_(False),
                GamePlayer.alive.is_(True),
            ).order_by(GamePlayer.id.desc()).limit(1)
        )).scalar_one_or_none()
        if not player_row:
            await message.answer("در حال حاضر در بازی فعالی نیستید.")
            return
        game = await session.get(Game, player_row.game_id)
        role = await session.get(Role, player_row.role_id) if player_row.role_id else None
        if not game or game.status != "running":
            await message.answer("در حال حاضر در بازی فعالی نیستید.")
            return
        if not role:
            await message.answer("نقش شما هنوز برای این بازی ثبت نشده است.")
            return
        side = {"mafia": "مافیا", "citizen": "شهروند", "independent": "مستقل"}.get(role.team, role.team)
    await message.answer(f"🎭 نقش شما\n\nنقش: {role.name_fa}\nساید: {side}")


@router.message(_exact("حاضری", "بازیکنان"))
async def text_players(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or await state.get_state():
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        if not game:
            await message.answer("بازی فعالی وجود ندارد.")
            return
        players = await GameRepository.players(session, game.id)
        reserves = await GameRepository.reserves(session, game.id)
        lines = ["👥 بازیکنان حاضر", ""]
        for player, user in players:
            lines.append(f"{player.seat}. {tg_name(user.display_name or user.first_name or 'بازیکن')}")
        if reserves:
            lines += ["", "🔁 جایگزین‌ها"]
            for player, user in reserves:
                lines.append(f"{player.reserve_position}. {tg_name(user.display_name or user.first_name or 'بازیکن')}")
    await message.answer("\n".join(lines))


@router.message(_exact("لابی"))
async def text_lobby(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or await state.get_state():
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        if not game or game.status != "waiting":
            await message.answer("لابی فعالی وجود ندارد.")
            return
        text, _ = await render_lobby(session, game)
    await message.answer(text)


@router.message(_exact("انتخاب سردست", "سردست"))
async def text_leader_menu(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user or await state.get_state():
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not await _is_host(session, game, user) or game.phase != "setup":
            await message.answer("فقط گرداننده و فقط در مرحله آماده‌سازی می‌تواند سردست را انتخاب کند.")
            return
    await message.answer("👑 انتخاب سردست\n\nروش انتخاب را مشخص کنید:", reply_markup=leader_choice_keyboard(game.game_key, []))


@router.message(_exact("تنظیمات بازی"))
async def text_game_settings(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user or await state.get_state():
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not await _is_host(session, game, user):
            await message.answer("فقط گرداننده می‌تواند تنظیمات بازی را باز کند.")
            return
        from app.handlers.keyboards import game_features_menu
        markup = game_features_menu(
            game.group_id, game.challenge_enabled, game.challenge_mode,
            game.next_host_enabled, game.next_player_enabled, game.next_auto_enabled,
            game.auto_silence_warnings, game.auto_kick_warnings,
            game.turn_seconds, game.challenge_seconds, game.extra_challenge_seconds,
        )
    await message.answer("⚙️ تنظیمات بازی", reply_markup=markup)


@router.message(_exact("شروع دور"))
async def text_start_round(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user or await state.get_state():
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not await _is_host(session, game, user):
            await message.answer("فقط گرداننده می‌تواند دور را شروع کند.")
            return
        try:
            result = await start_round(session, game)
        except ValueError as exc:
            await message.answer(str(exc))
            return
    await message.answer(f"▶️ دور {result['round_no']} شروع شد.")


@router.message(_exact("لغو بازی"))
async def text_cancel_game(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user or await state.get_state():
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not await _is_host(session, game, user):
            await message.answer("فقط گرداننده می‌تواند بازی را لغو کند.")
            return
        await GameRepository.cancel(session, game)
    await message.answer("❌ بازی توسط گرداننده لغو شد.")


@router.message(_exact("دستورات", "دستورها"))
async def text_commands(message: Message, state: FSMContext) -> None:
    if await state.get_state():
        return
    await message.answer(
        "📚 دستورات متنی\n\n"
        "پیوی: پروفایل، نقش من، رتبه\n"
        "گروه: لابی، جایگزین، انتخاب سردست، تنظیمات بازی، شروع دور، لغو بازی\n\n"
        "دستور فقط وقتی اجرا می‌شود که متن پیام دقیقاً برابر خود دستور باشد؛ "
        "مثلاً «جایگزین میخوایم» هیچ دستوری را اجرا نمی‌کند."
    )
