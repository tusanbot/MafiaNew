import json
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Game, GameEvent, GamePlayer, Role, User, Vote
from app.core.game.engine import GameEngine, GameEnginePhase, GameState
from app.services.roles import assign_roles

def _payload(event: GameEvent) -> dict:
    try:
        return json.loads(event.payload or "{}")
    except json.JSONDecodeError:
        return {}

async def _event(session, game, event_type, payload, actor_user_id=None):
    item = GameEvent(game_id=game.id, actor_user_id=actor_user_id, event_type=event_type,
                     payload=json.dumps(payload, ensure_ascii=False))
    session.add(item)
    await session.flush()
    return item

async def current_round(session, game_id: int) -> int:
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game_id, GameEvent.event_type == "round_started"
    ).order_by(GameEvent.id.desc()))
    event = result.scalars().first()
    return int(_payload(event).get("round_no", 1)) if event else 1

async def alive_players(session, game_id: int):
    result = await session.execute(select(GamePlayer, User, Role)
        .join(User, User.id == GamePlayer.user_id)
        .outerjoin(Role, Role.id == GamePlayer.role_id)
        .where(GamePlayer.game_id == game_id, GamePlayer.alive.is_(True))
        .order_by(GamePlayer.seat))
    return list(result.all())

async def all_players(session, game_id: int):
    result = await session.execute(select(GamePlayer, User, Role)
        .join(User, User.id == GamePlayer.user_id)
        .outerjoin(Role, Role.id == GamePlayer.role_id)
        .where(GamePlayer.game_id == game_id).order_by(GamePlayer.seat))
    return list(result.all())

async def start_match(session: AsyncSession, game: Game):
    assignments = await assign_roles(session, game)
    game.status = "running"
    game.phase = GameEnginePhase.NIGHT.value
    await _event(session, game, "round_started", {"round_no": 1})
    await session.commit()
    return assignments

async def set_phase(session: AsyncSession, game: Game, target: GameEnginePhase):
    round_no = await current_round(session, game.id)
    state = GameState(GameEnginePhase(game.phase), round_no)
    GameEngine.transition(state, target)
    game.phase = target.value
    await _event(session, game, "phase_changed", {"to": target.value, "round_no": round_no})
    await session.commit()

async def submit_night_action(session, game, actor, action_type, target_user_id):
    if game.status != "running" or game.phase != "night":
        raise ValueError("الان زمان اقدام شب نیست.")
    round_no = await current_round(session, game.id)
    row = (await session.execute(select(GamePlayer, Role).join(Role, Role.id == GamePlayer.role_id)
        .where(GamePlayer.game_id == game.id, GamePlayer.user_id == actor.id))).first()
    if not row or not row[0].alive:
        raise ValueError("شما عضو زنده این بازی نیستید.")
    player, role = row
    expected = {"godfather": "mafia_kill", "mafia": "mafia_kill", "doctor": "doctor_save", "detective": "detective_check"}
    if expected.get(role.key) != action_type:
        raise ValueError("این اقدام برای نقش شما مجاز نیست.")
    target = (await session.execute(select(GamePlayer).where(
        GamePlayer.game_id == game.id, GamePlayer.user_id == target_user_id, GamePlayer.alive.is_(True)
    ))).scalar_one_or_none()
    if target is None:
        raise ValueError("هدف انتخاب‌شده زنده نیست.")
    events = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "night_action"
    ).order_by(GameEvent.id.desc()))
    for event in events.scalars():
        data = _payload(event)
        if data.get("round_no") == round_no and data.get("action_type") == action_type:
            raise ValueError("این اقدام قبلاً ثبت شده است.")
    await _event(session, game, "night_action",
                 {"round_no": round_no, "action_type": action_type, "target_user_id": target_user_id}, actor.id)
    detective_result = None
    if action_type == "detective_check":
        target_role = (await session.execute(select(Role).join(GamePlayer, GamePlayer.role_id == Role.id)
            .where(GamePlayer.game_id == game.id, GamePlayer.user_id == target_user_id))).scalar_one()
        detective_result = "مافیا" if target_role.team == "mafia" else "شهروند"
    await session.commit()
    return {"round_no": round_no, "resolved": await night_ready(session, game), "detective_result": detective_result}

async def night_ready(session, game):
    alive = await alive_players(session, game.id)
    required = set()
    for _, _, role in alive:
        if not role: continue
        if role.team == "mafia": required.add("mafia_kill")
        elif role.key == "doctor": required.add("doctor_save")
        elif role.key == "detective": required.add("detective_check")
    round_no = await current_round(session, game.id)
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "night_action"
    ))
    submitted = {_payload(e).get("action_type") for e in result.scalars() if _payload(e).get("round_no") == round_no}
    return required.issubset(submitted)

async def resolve_night(session, game):
    if game.phase != "night" or not await night_ready(session, game):
        raise ValueError("شب هنوز آماده حل شدن نیست.")
    round_no = await current_round(session, game.id)
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "night_action"
    ).order_by(GameEvent.id.desc()))
    actions = {}
    for event in result.scalars():
        data = _payload(event)
        if data.get("round_no") == round_no and data.get("action_type") not in actions:
            actions[data["action_type"]] = data.get("target_user_id")
    killed_id, saved_id = actions.get("mafia_kill"), actions.get("doctor_save")
    eliminated = None
    if killed_id and killed_id != saved_id:
        row = (await session.execute(select(GamePlayer, User).join(User, User.id == GamePlayer.user_id).where(
            GamePlayer.game_id == game.id, GamePlayer.user_id == killed_id, GamePlayer.alive.is_(True)
        ))).first()
        if row:
            row[0].alive = False
            eliminated = row[1]
    await _event(session, game, "night_resolved",
                 {"round_no": round_no, "killed_user_id": eliminated.id if eliminated else None,
                  "saved": bool(killed_id and killed_id == saved_id)})
    winner = await check_winner(session, game.id)
    if winner:
        await finalize_game(session, game, winner)
        await session.commit()
        return {"winner": winner, "eliminated": eliminated, "saved": bool(killed_id and killed_id == saved_id)}
    game.phase = "day"
    await _event(session, game, "phase_changed", {"to": "day", "round_no": round_no})
    await session.commit()
    return {"winner": None, "eliminated": eliminated, "saved": bool(killed_id and killed_id == saved_id)}

async def start_voting(session, game):
    if game.phase != "day": raise ValueError("الان مرحله روز نیست.")
    round_no = await current_round(session, game.id)
    game.phase = "voting"
    await _event(session, game, "phase_changed", {"to": "voting", "round_no": round_no})
    await session.commit()

async def submit_vote(session, game, voter, target_user_id):
    if game.status != "running" or game.phase != "voting": raise ValueError("الان زمان رأی‌گیری نیست.")
    round_no = await current_round(session, game.id)
    if (await session.execute(select(GamePlayer).where(
        GamePlayer.game_id == game.id, GamePlayer.user_id == voter.id, GamePlayer.alive.is_(True)
    ))).scalar_one_or_none() is None:
        raise ValueError("فقط بازیکن زنده می‌تواند رأی بدهد.")
    if (await session.execute(select(GamePlayer).where(
        GamePlayer.game_id == game.id, GamePlayer.user_id == target_user_id, GamePlayer.alive.is_(True)
    ))).scalar_one_or_none() is None:
        raise ValueError("هدف انتخاب‌شده زنده نیست.")
    existing = await session.execute(select(Vote).where(
        Vote.game_id == game.id, Vote.round_no == round_no, Vote.voter_user_id == voter.id))
    if existing.scalar_one_or_none(): raise ValueError("رأی شما قبلاً ثبت شده است.")
    session.add(Vote(game_id=game.id, voter_user_id=voter.id, target_user_id=target_user_id, round_no=round_no))
    await session.flush()
    alive_count = len(await alive_players(session, game.id))
    vote_count = await session.scalar(select(func.count(Vote.id)).where(Vote.game_id == game.id, Vote.round_no == round_no))
    if vote_count < alive_count:
        await session.commit()
        return {"resolved": False}
    result = await session.execute(select(Vote.target_user_id, func.count(Vote.id))
        .where(Vote.game_id == game.id, Vote.round_no == round_no)
        .group_by(Vote.target_user_id).order_by(func.count(Vote.id).desc()))
    rows = list(result.all())
    top = rows[0][1] if rows else 0
    leaders = [target for target, count in rows if count == top]
    eliminated = None
    if len(leaders) == 1:
        row = (await session.execute(select(GamePlayer, User).join(User, User.id == GamePlayer.user_id).where(
            GamePlayer.game_id == game.id, GamePlayer.user_id == leaders[0], GamePlayer.alive.is_(True)
        ))).first()
        if row:
            row[0].alive = False
            eliminated = row[1]
    await _event(session, game, "voting_resolved",
                 {"round_no": round_no, "eliminated_user_id": eliminated.id if eliminated else None, "tie": len(leaders) != 1})
    winner = await check_winner(session, game.id)
    if winner:
        await finalize_game(session, game, winner)
        await session.commit()
        return {"resolved": True, "winner": winner, "eliminated": eliminated, "tie": len(leaders) != 1}
    game.phase = "night"
    await _event(session, game, "round_started", {"round_no": round_no + 1})
    await session.commit()
    return {"resolved": True, "winner": None, "eliminated": eliminated, "tie": len(leaders) != 1}

async def check_winner(session, game_id):
    alive = await alive_players(session, game_id)
    mafia = sum(1 for _, _, role in alive if role and role.team == "mafia")
    citizens = sum(1 for _, _, role in alive if role and role.team == "citizen")
    if mafia == 0: return "citizen"
    if mafia >= citizens: return "mafia"
    return None

async def finalize_game(session, game, winner):
    if game.status == "finished": return
    existing = await session.execute(select(GameEvent).where(GameEvent.game_id == game.id, GameEvent.event_type == "stats_recorded"))
    if existing.scalars().first(): return
    game.status, game.phase, game.finished_at = "finished", "result", datetime.now(timezone.utc)
    for player, user, role in await all_players(session, game.id):
        user.games_played += 1
        if role and role.team == winner:
            user.games_won += 1
            if winner == "mafia": user.mafia_wins += 1
            elif winner == "citizen": user.citizen_wins += 1
    await _event(session, game, "stats_recorded", {"winner": winner})

async def submit_challenge(session, game, challenger: User, target_user_id: int):
    if game.status != "running" or game.phase != "day":
        raise ValueError("چالش فقط در مرحله روز امکان‌پذیر است.")
    challenger_row = (await session.execute(select(GamePlayer).where(
        GamePlayer.game_id == game.id, GamePlayer.user_id == challenger.id, GamePlayer.alive.is_(True)
    ))).scalar_one_or_none()
    if challenger_row is None:
        raise ValueError("فقط بازیکن زنده می‌تواند چالش ثبت کند.")
    target_row = (await session.execute(select(GamePlayer).where(
        GamePlayer.game_id == game.id, GamePlayer.user_id == target_user_id, GamePlayer.alive.is_(True)
    ))).scalar_one_or_none()
    if target_row is None or target_user_id == challenger.id:
        raise ValueError("هدف چالش معتبر نیست.")
    round_no = await current_round(session, game.id)
    recent = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "challenge"
    ).order_by(GameEvent.id.desc()))
    for event in recent.scalars():
        data = _payload(event)
        if data.get("round_no") == round_no and data.get("challenger_id") == challenger.id:
            raise ValueError("در این دور قبلاً چالش ثبت کرده‌اید.")
    await _event(session, game, "challenge", {
        "round_no": round_no, "challenger_id": challenger.id,
        "target_user_id": target_user_id, "status": "pending",
    }, challenger.id)
    challenger.challenges += 1
    await session.commit()
    return {"round_no": round_no}

async def resolve_challenge(session, game, challenge_event_id: int, accepted: bool):
    event = await session.get(GameEvent, challenge_event_id)
    if not event or event.game_id != game.id or event.event_type != "challenge":
        raise ValueError("چالش پیدا نشد.")
    data = _payload(event)
    if data.get("status") != "pending":
        raise ValueError("این چالش قبلاً تعیین تکلیف شده است.")
    data["status"] = "accepted" if accepted else "rejected"
    event.payload = json.dumps(data, ensure_ascii=False)
    await session.commit()
    return data
