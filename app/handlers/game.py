from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.db.models import Group, Scenario, User
from app.db.session import session_factory
from app.repositories.games import GameRepository
from app.repositories.users import UserRepository
from app.services.game import render_lobby, role_messages
from app.services.roles import assign_roles
from app.handlers.keyboards import lobby_keyboard_v2

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
        ),
    )


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
        await callback.answer(f"رزرو شما ثبت شد؛ جایگاه رزرو {player.reserve_position}.")


@router.callback_query(lambda c: c.data and c.data.startswith("lobby:seat:"))
async def change_or_take_seat(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    _, _, game_key, seat_raw = callback.data.split(":")
    seat = int(seat_raw)
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
        current = await session.execute(
            select(__import__("app.db.models", fromlist=["GamePlayer"]).GamePlayer)
            .where(
                __import__("app.db.models", fromlist=["GamePlayer"]).GamePlayer.game_id == game.id,
                __import__("app.db.models", fromlist=["GamePlayer"]).GamePlayer.user_id == user.id,
            )
        )
        player = current.scalar_one_or_none()
        if player is None:
            joined = await GameRepository.join(session, game, user)
            if joined is None:
                await callback.answer("ابتدا وارد بازی شوید یا از رزرو استفاده کنید.", show_alert=True)
                return
            player = joined
        if player.is_reserved:
            await callback.answer("بازیکن رزروی تا زمان جایگزینی صندلی ندارد.", show_alert=True)
            return
        if player.seat == seat:
            await callback.answer("این صندلی همین حالا برای شماست.")
            return
        if not await GameRepository.change_seat(session, game, user, seat):
            await callback.answer("این صندلی اشغال است یا قابل انتخاب نیست.", show_alert=True)
            return
        await _render(callback, session, game, user.id)
        await callback.answer(f"صندلی {seat} برای شما ثبت شد.")


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
        await callback.bot.send_message(callback.message.chat.id, group_list)
        if failed:
            await callback.message.answer(
                f"نقش‌ها برای {sent} بازیکن ارسال شد. ارسال خصوصی برای {len(failed)} نفر ناموفق بود؛ آن افراد باید ابتدا ربات را در PV /start کنند."
            )
        else:
            await callback.message.answer("نقش همه بازیکنان در PV ارسال شد.")
    await callback.answer("نقش‌ها پخش شدند.")


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
        await callback.message.edit_text("مدیریت گروه", reply_markup=group_management_menu())
    await callback.answer()
