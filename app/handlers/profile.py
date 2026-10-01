from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from app.db.models import User
from app.db.session import session_factory
from app.handlers.keyboards import main_menu, ranking_menu
from app.services.profile import sync_telegram_user
from app.services.stats import leaderboard, rank_for_score, user_achievements
from app.utils.text import tg_name

router = Router(name="profile")

async def _profile_text(session, user: User) -> str:
    position = (await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True), User.score > user.score)) or 0) + 1
    rank = rank_for_score(user.score)
    win_rate = (user.games_won / user.games_played * 100) if user.games_played else 0
    return (
        "👤 پروفایل بازیکن\n\n"
        f"نام: {tg_name(user.display_name or user.first_name or 'بازیکن')}\n"
        f"رتبه: {rank}  •  جایگاه: #{position}\n"
        f"امتیاز: {user.score}\n\n"
        f"🎮 بازی‌ها: {user.games_played}\n"
        f"🏆 بردها: {user.games_won}\n"
        f"📈 نرخ برد: {win_rate:.1f}%\n"
        f"🔴 برد مافیا: {user.mafia_wins}\n"
        f"🔵 برد شهروند: {user.citizen_wins}\n"
        f"⚔️ چالش‌ها: {user.challenges}\n"
        f"🏅 دستاوردها: {user.achievements_count}"
    )

@router.message(Command("profile"))
async def profile_handler(message: Message) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    tg = message.from_user
    async with session_factory() as session:
        db_user = await sync_telegram_user(session, tg.id, tg.username, tg.first_name or "", tg.last_name)
        await session.commit()
        await message.answer(await _profile_text(session, db_user))

@router.callback_query(lambda c: c.data == "menu:profile")
async def profile_menu(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        tg = callback.from_user
        user = await sync_telegram_user(session, tg.id, tg.username, tg.first_name or "", tg.last_name)
        await session.commit()
        await callback.message.edit_text(await _profile_text(session, user))
    await callback.answer()

@router.message(Command("ranking"))
async def ranking_command(message: Message) -> None:
    if message.chat.type != "private":
        return
    async with session_factory() as session:
        await _render_ranking(message, session, "all")

async def _render_ranking(target, session, kind: str):
    team = kind if kind in {"mafia", "citizen"} else None
    rows = await leaderboard(session, 10, team)
    title = {"all": "🏆 رتبه‌بندی بازیکنان", "mafia": "🔴 برترین‌های مافیا", "citizen": "🔵 برترین‌های شهروند"}.get(kind, "🏆 رتبه‌بندی")
    if not rows:
        text = title + "\n\nهنوز بازی کاملی برای رتبه‌بندی ثبت نشده است."
    else:
        lines = [title, ""]
        for i, user in enumerate(rows, 1):
            lines.append(f"{i}. {tg_name(user.display_name or user.first_name or 'بازیکن')} — {user.score} امتیاز — {rank_for_score(user.score)}")
        text = "\n".join(lines)
    await target.answer(text, reply_markup=ranking_menu()) if isinstance(target, Message) else await target.message.edit_text(text, reply_markup=ranking_menu())

@router.callback_query(lambda c: c.data == "menu:ranking")
async def ranking_menu_handler(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    async with session_factory() as session:
        await _render_ranking(callback, session, "all")
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("ranking:"))
async def ranking_callback(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    kind = callback.data.split(":", 1)[1]
    if kind not in {"players", "mafia", "citizen"}:
        await callback.answer()
        return
    kind = {"players": "all"}.get(kind, kind)
    async with session_factory() as session:
        await _render_ranking(callback, session, kind)
    await callback.answer()

@router.message(Command("achievements"))
async def achievements_command(message: Message) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            await message.answer("هنوز پروفایلی برای شما ثبت نشده است.")
            return
        achievements = await user_achievements(session, user.id)
        if not achievements:
            await message.answer("🏅 هنوز دستاوردی کسب نکرده‌اید.")
            return
        await message.answer("🏅 دستاوردهای شما\n\n" + "\n".join(f"{a.icon} {a.name_fa} — +{a.points}" for a in achievements))

@router.callback_query(lambda c: c.data == "profile:achievements")
async def achievements_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        achievements = await user_achievements(session, user.id) if user else []
        text = "🏅 دستاوردهای شما\n\n" + ("\n".join(f"{a.icon} {a.name_fa} — +{a.points}\n{a.description}" for a in achievements) if achievements else "هنوز دستاوردی کسب نکرده‌اید.")
        await callback.message.edit_text(text, reply_markup=main_menu())
    await callback.answer()
