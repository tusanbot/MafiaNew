from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Scenario, User
from app.repositories.games import GameRepository
from app.utils.text import tg_name


def gregorian_to_jalali(year: int, month: int, day: int) -> tuple[int, int, int]:
    # Compact Gregorian -> Jalali conversion for display only.
    g_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gy, gm, gd = year, month, day
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd
    for i in range(1, gm):
        days += g_days[i - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
    else:
        jm = 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return jy, jm, jd


async def create_game(
    session: AsyncSession,
    group,
    scenario: Scenario,
    host: User,
    status: str = "waiting",
    *,
    auto_play: bool = False,
    turn_color: str = "پیش‌فرض",
    challenge_color: str = "پیش‌فرض",
    reserve_enabled: bool = True,
    turn_seconds: int | None = None,
    challenge_seconds: int | None = None,
    extra_challenge_seconds: int | None = None,
):
    key = uuid4().hex[:12]
    return await GameRepository.create(
        session,
        group,
        scenario,
        host,
        key,
        status=status,
        auto_play=auto_play,
        turn_color=turn_color,
        challenge_color=challenge_color,
        reserve_enabled=reserve_enabled,
        turn_seconds=turn_seconds if turn_seconds is not None else getattr(scenario, "turn_seconds", 120),
        challenge_seconds=challenge_seconds if challenge_seconds is not None else getattr(scenario, "challenge_seconds", 60),
        extra_challenge_seconds=extra_challenge_seconds if extra_challenge_seconds is not None else getattr(scenario, "extra_challenge_seconds", 60),
    )


async def render_lobby(session: AsyncSession, game) -> tuple[str, bool]:
    players = await GameRepository.players(session, game.id)
    reserves = await GameRepository.reserves(session, game.id)
    scenario = await session.get(Scenario, game.scenario_id)
    min_players = scenario.min_players if scenario else 999
    max_players = scenario.max_players if scenario else 0

    now = datetime.now(ZoneInfo("Asia/Tehran"))
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    lines = [
        "\u200f༄",
        f"\u200f📓 بازی شماره : {game.id}",
        "",
        f"\u200f⏱ زمان : {now:%H:%M}",
        f"\u200f📆 تاریخ : {jy:04d}/{jm:02d}/{jd:02d}",
        f"\u200f🗓 سناریو : {scenario.name_fa if scenario else 'نامشخص'}",
        "",
        f"\u200fبازیکنان اصلی : {len(players)}/{max_players}",
        "",
    ]
    for seat in range(1, max_players + 1):
        item = next(((p, u) for p, u in players if p.seat == seat), None)
        if item:
            _, user = item
            name = tg_name(user.display_name or user.first_name or str(user.telegram_id))
            lines.append(f'{seat:02d}. <a href="tg://user?id={user.telegram_id}">{name}</a>')
        else:
            lines.append(f"\u200f{seat:02d}. — خالی —")
    if reserves:
        lines.extend(["", "\u200fلیست رزرو:"])
        for p, u in reserves:
            name = tg_name(u.display_name or u.first_name or str(u.telegram_id))
            lines.append(f'{p.reserve_position}. <a href="tg://user?id={u.telegram_id}">{name}</a>')
    lines.extend([
        "",
        f"حداقل نفرات شروع: {min_players}",
        "با انتخاب صندلی می‌توانید صندلی خود را تغییر دهید.",
    ])
    return "\n".join(lines), len(players) >= max_players


async def role_messages(session: AsyncSession, game, assignments):
    scenario = await session.get(Scenario, game.scenario_id)
    host = await session.get(User, game.host_user_id) if game.host_user_id else None
    now = datetime.now(ZoneInfo("Asia/Tehran"))
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    scenario_name = scenario.name_fa if scenario else "نامشخص"
    host_name = tg_name(host.display_name if host else "نامشخص")

    team_names = {"mafia": "مافیا", "citizen": "شهروند", "independent": "مستقل"}
    rows = []
    for player, role, user in assignments:
        rows.append((player.seat, user.display_name or user.first_name or "بازیکن", role.name_fa, team_names.get(role.team, role.team), role.description, user.telegram_id))

    header = (
        f"༄\n"
        f"📓 بازی شماره : {game.id}\n\n"
        f"⏱ زمان : {now:%H:%M}\n"
        f"📆 تاریخ : {jy:04d}/{jm:02d}/{jd:02d}\n"
        f"🗓 سناریو : {scenario_name}\n"
        f"👮‍♂ گرداننده : {host_name}\n\n"
        f"~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n"
        f"👥 لیست بازیکنان حاضر در بازی\n"
        f"◤◢◣◥◤◢◣◥◤◢◣◥\n"
    )
    list_lines = []
    for seat, name, role_name, team, description, telegram_id in rows:
        list_lines.append(f'<a href="tg://user?id={telegram_id}">{tg_name(name)}</a> — {escape(role_name)} --------- {escape(team)}')
    group_list = header + "\n".join(list_lines) + "\n◤◢◣◥◤◢◣◥◤◢◣◥\n\n༄"

    player_messages = []
    for seat, name, role_name, team, description, telegram_id in rows:
        explanation = description or "توضیح این نقش در سناریو ثبت نشده است."
        player_messages.append(
            (telegram_id,
             f"༄\n"
             f"📓 بازی شماره : {game.id}\n\n"
             f"⏱ زمان : {now:%H:%M}\n"
             f"📆 تاریخ : {jy:04d}/{jm:02d}/{jd:02d}\n"
             f"🗓 سناریو : {scenario_name}\n"
             f"👮‍♂ گرداننده : {host_name}\n\n"
             f"~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n"
             f"نقش شما: {role_name}\n\n"
             f"ساید: {team}\n\n"
             f"توضیح نقش:\n{explanation}\n\n"
             f"~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n\n"
             f"༄")
        )
    return group_list, player_messages
