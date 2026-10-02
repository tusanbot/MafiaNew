import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Game, GameEvent, GamePlayer, Role, User, Vote, Scenario, Achievement
from app.core.game.engine import GameEngine, GameEnginePhase, GameState
from app.services.roles import assign_roles
from app.services.stats import record_game_result

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
    """Deal roles and enter the explicit setup phase.

    Leader selection is deliberately a separate step.  The old implementation
    jumped directly to NIGHT, which bypassed the configured leader/start-round
    flow and made the first day inconsistent with later rounds.
    """
    if game.status != "waiting":
        raise ValueError("بازی در وضعیت شروع نیست.")
    assignments = await assign_roles(session, game)
    game.status = "running"
    game.phase = GameEnginePhase.SETUP.value
    game.started_at = game.started_at or datetime.now(timezone.utc)
    await _event(session, game, "round_started", {"round_no": 1})
    await _event(session, game, "setup_started", {"round_no": 1})
    await session.commit()
    return assignments

async def set_phase(session: AsyncSession, game: Game, target: GameEnginePhase):
    round_no = await current_round(session, game.id)
    state = GameState(GameEnginePhase(game.phase), round_no)
    GameEngine.transition(state, target)
    game.phase = target.value
    await _event(session, game, "phase_changed", {"to": target.value, "round_no": round_no})
    await session.commit()

async def queue_pending_status_action(session, game, action: str, target_user_id: int, round_no: int, actor_user_id: int | None = None, warning_count: int | None = None):
    """Queue a night status change so players only see it when the new day list is created."""
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id,
        GameEvent.event_type == "pending_status_action",
    ).order_by(GameEvent.id.desc()))
    for event in result.scalars():
        data = _payload(event)
        if (
            data.get("round_no") == round_no
            and data.get("action") == action
            and data.get("target_user_id") == target_user_id
            and not data.get("applied")
        ):
            return event
    payload = {
        "round_no": round_no,
        "action": action,
        "target_user_id": target_user_id,
        "applied": False,
    }
    if warning_count is not None:
        payload["warning_count"] = warning_count
    return await _event(session, game, "pending_status_action", payload, actor_user_id)


async def apply_pending_status_actions(session, game, round_no: int | None = None):
    """Apply status changes queued during night, immediately before the new day list."""
    if round_no is None:
        round_no = await current_round(session, game.id)
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id,
        GameEvent.event_type == "pending_status_action",
    ).order_by(GameEvent.id.asc()))
    applied = []
    for event in result.scalars():
        data = _payload(event)
        if data.get("round_no") != round_no or data.get("applied"):
            continue
        target_id = int(data.get("target_user_id", 0))
        target = (await session.execute(select(GamePlayer).where(
            GamePlayer.game_id == game.id, GamePlayer.user_id == target_id
        ))).scalar_one_or_none()
        if not target:
            data["applied"] = True
            event.payload = json.dumps(data, ensure_ascii=False)
            continue
        action = data.get("action")
        if action == "silence":
            target.silence_until_round = round_no
        elif action in {"death", "kick", "slaughter"}:
            target.alive = False
            target.exit_type = action
        elif action == "warning":
            target.warning_count += 1
            penalty = min(target.warning_count, 5)
            target_user = await session.get(User, target_id)
            if target_user:
                target_user.score -= penalty
            if target.warning_count >= 3:
                if game.auto_silence_warnings and target.warning_count >= 4:
                    target.silence_until_round = round_no + 1
                if game.auto_kick_warnings and target.warning_count >= 5:
                    target.alive = False
                    target.exit_type = "kick"
        else:
            data["applied"] = True
            event.payload = json.dumps(data, ensure_ascii=False)
            continue
        data["applied"] = True
        data["applied_at"] = datetime.now(timezone.utc).isoformat()
        event.payload = json.dumps(data, ensure_ascii=False)
        applied.append({"action": action, "target_user_id": target_id})
    await session.flush()
    return applied


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
            await queue_pending_status_action(
                session, game, "death", killed_id, round_no,
            )
    await _event(session, game, "night_resolved",
                 {"round_no": round_no, "killed_user_id": killed_id if killed_id and killed_id != saved_id else None,
                  "saved": bool(killed_id and killed_id == saved_id)})
    await apply_pending_status_actions(session, game, round_no)
    if killed_id and killed_id != saved_id:
        eliminated = await session.get(User, killed_id)
    winner = await check_winner(session, game.id)
    if winner:
        await finalize_game(session, game, winner)
        await session.commit()
        return {"winner": winner, "eliminated": eliminated, "saved": bool(killed_id and killed_id == saved_id)}
    game.phase = "day"
    await _event(session, game, "phase_changed", {"to": "day", "round_no": round_no})
    await session.commit()
    return {"winner": None, "eliminated": eliminated, "saved": bool(killed_id and killed_id == saved_id)}

async def start_new_day_round(session, game, first_user_id: int | None = None):
    """Create a durable round boundary and reset temporary per-round state."""
    if game.status != "running" or game.phase != "day":
        raise ValueError("روز آماده شروع دور جدید نیست.")
    old_round = await current_round(session, game.id)
    new_round = old_round + 1
    players = (await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id))).scalars().all()
    for player in players:
        if player.silence_until_round == old_round:
            player.silence_until_round = None
        if player.extra_turn_round == old_round:
            player.extra_turn_round = None
    await _event(session, game, "round_ended", {"round_no": old_round, "next_round_no": new_round})
    await _event(session, game, "round_started", {"round_no": new_round, "previous_round_no": old_round, "started_after_night": True})
    await session.commit()
    await start_day_turns(session, game, first_user_id)
    return new_round

async def start_voting(session, game):
    if game.phase != "day":
        raise ValueError("الان مرحله روز نیست.")
    turn = await current_turn(session, game.id)
    if not turn or turn.get("status") != "finished":
        raise ValueError("تا پایان تمام نوبت‌های این دور امکان رأی‌گیری وجود ندارد.")
    round_no = await current_round(session, game.id)
    queue = await _latest_turn_queue(session, game.id, round_no)
    if not queue:
        raise ValueError("صف نوبت‌های این دور پیدا نشد.")
    queue_ids = list(queue.get("queue", []))
    index = int(queue.get("index", -1))
    alive_ids = {user.id for _, user, _ in await alive_players(session, game.id)}
    remaining = [uid for uid in queue_ids[index + 1:] if uid in alive_ids]
    if remaining:
        raise ValueError("هنوز نوبت همه بازیکنان زنده تمام نشده است.")
    pending_after = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id,
        GameEvent.event_type == "pending_after_challenge",
    ))
    if any(
        _payload(event).get("round_no") == round_no
        and _payload(event).get("status") in {"pending", "started"}
        for event in pending_after.scalars()
    ):
        raise ValueError("هنوز چالش این دور اجرا نشده است.")
    game.phase = "voting"
    await _event(session, game, "phase_changed", {"to": "voting", "round_no": round_no})
    await session.commit()

async def _latest_vote_state(session, game_id: int) -> dict | None:
    result = await session.execute(
        select(GameEvent).where(
            GameEvent.game_id == game_id,
            GameEvent.event_type == "vote_state",
        ).order_by(GameEvent.id.desc())
    )
    event = result.scalars().first()
    return _payload(event) if event else None


async def _revoked_vote_ids(session, game_id: int, round_no: int) -> set[int]:
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game_id,
        GameEvent.event_type == "vote_right_revoked",
    ).order_by(GameEvent.id.desc()))
    revoked = set()
    for event in result.scalars():
        data = _payload(event)
        if int(data.get("round_no", -1)) != round_no:
            continue
        uid = int(data.get("user_id", -1))
        if data.get("active", True):
            revoked.add(uid)
        else:
            revoked.discard(uid)
    return revoked


async def vote1_start(session, game):
    if game.phase not in {"day", "vote_setup"}:
        raise ValueError("الان زمان آماده‌سازی رای گیری نیست.")
    round_no = await current_round(session, game.id)
    queue = await _latest_turn_queue(session, game.id, round_no)
    if not queue:
        raise ValueError("صف نوبت‌های این دور پیدا نشد.")
    ordered = [int(uid) for uid in queue.get("queue", [])]
    alive_ids = {user.id for _, user, _ in await alive_players(session, game.id)}
    ordered = [uid for uid in ordered if uid in alive_ids]
    if not ordered:
        raise ValueError("بازیکن زنده‌ای برای رای گیری وجود ندارد.")
    game.phase = "voting1"
    await _event(session, game, "vote_state", {
        "round_no": round_no,
        "phase": "vote1",
        "index": 0,
        "queue": ordered,
        "target_user_id": ordered[0],
        "status": "active",
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    await _event(session, game, "voting_started", {
        "round_no": round_no, "phase": "vote1",
        "pre_delay_seconds": int(game.voting_pre_delay_seconds or 0),
        "vote_seconds": int(game.vote_seconds or 10),
        "mode": game.voting_mode,
    })
    await session.commit()
    return ordered[0]


async def vote1_current_target(session, game):
    state = await _latest_vote_state(session, game.id)
    if not state or state.get("phase") != "vote1" or state.get("status") != "active":
        return None
    return int(state["target_user_id"])


async def _vote_records_for_target(session, game, round_no: int, phase: str, target_id: int):
    result = await session.execute(
        select(Vote, User).join(User, User.id == Vote.voter_user_id).where(
            Vote.game_id == game.id,
            Vote.round_no == round_no,
            Vote.phase == phase,
            Vote.target_user_id == target_id,
        ).order_by(Vote.id.asc())
    )
    return list(result.all())


async def cast_vote_phase(session, game, voter: User, target_user_id: int, phase: str):
    if game.status != "running" or game.phase not in {"voting1", "voting2"}:
        raise ValueError("الان زمان رای گیری نیست.")
    state = await _latest_vote_state(session, game.id)
    if not state or state.get("phase") != phase or state.get("status") != "active":
        raise ValueError("این رای گیری فعال نیست.")
    current_target = int(state["target_user_id"])
    if current_target != int(target_user_id):
        raise ValueError("این بازیکن الان در حال رای گیری نیست.")
    round_no = int(state["round_no"])
    player = await session.scalar(select(GamePlayer).where(
        GamePlayer.game_id == game.id, GamePlayer.user_id == voter.id, GamePlayer.alive.is_(True)
    ))
    if not player:
        raise ValueError("فقط بازیکن زنده می‌تواند رای بدهد.")
    if voter.id == current_target:
        raise ValueError("بازیکن مورد رای خودش نمی‌تواند رای بدهد.")
    if voter.id in await _revoked_vote_ids(session, game.id, round_no):
        raise ValueError("حق رای شما تا پایان این دور گرفته شده است.")
    existing = await session.scalar(select(Vote).where(
        Vote.game_id == game.id, Vote.voter_user_id == voter.id,
        Vote.round_no == round_no, Vote.phase == phase,
    ))
    if existing:
        raise ValueError("رای شما قبلاً ثبت شده است.")
    now = datetime.now(timezone.utc)
    session.add(Vote(
        game_id=game.id, voter_user_id=voter.id, target_user_id=current_target,
        round_no=round_no, phase=phase, created_at=now,
    ))
    await session.flush()
    records = await _vote_records_for_target(session, game, round_no, phase, current_target)
    await session.commit()
    return {
        "target_user_id": current_target,
        "records": records,
        "count": len(records),
        "voted_at": now,
    }


async def finish_vote1_target(session, game):
    state = await _latest_vote_state(session, game.id)
    if not state or state.get("phase") != "vote1" or state.get("status") != "active":
        raise ValueError("رای اول فعالی وجود ندارد.")
    round_no = int(state["round_no"])
    target_id = int(state["target_user_id"])
    records = await _vote_records_for_target(session, game, round_no, "vote1", target_id)
    scenario = await _current_scenario(session, game)
    threshold = int(getattr(scenario, "vote_defense_threshold", 2) or 2)
    qualified = len(records) >= threshold
    state["status"] = "finished"
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    state["vote_count"] = len(records)
    state["qualified_for_defense"] = qualified
    await _event(session, game, "vote1_target_finished", {
        "round_no": round_no, "target_user_id": target_id,
        "vote_count": len(records), "threshold": threshold, "qualified": qualified,
    })
    await session.commit()
    return {
        "target_user_id": target_id,
        "records": records,
        "count": len(records),
        "threshold": threshold,
        "qualified": qualified,
    }


async def advance_vote1(session, game):
    result = await finish_vote1_target(session, game)
    state = await _latest_vote_state(session, game.id)
    queue = list(state.get("queue", []))
    next_index = int(state.get("index", 0)) + 1
    if next_index >= len(queue):
        candidates = []
        events = await session.execute(select(GameEvent).where(
            GameEvent.game_id == game.id,
            GameEvent.event_type == "vote1_target_finished",
        ).order_by(GameEvent.id.asc()))
        for event in events.scalars():
            data = _payload(event)
            if int(data.get("round_no", -1)) == int(state["round_no"]) and data.get("qualified"):
                uid = int(data["target_user_id"])
                if uid not in candidates:
                    candidates.append(uid)
        state["phase"] = "vote1_complete"
        state["status"] = "finished"
        state["qualified_candidates"] = candidates
        game.phase = "vote1_complete"
        await _event(session, game, "vote1_completed", {
            "round_no": int(state["round_no"]), "qualified_candidates": candidates,
        })
        await session.commit()
        return {"finished": True, "candidates": candidates, "result": result}
    target = int(queue[next_index])
    state["index"] = next_index
    state["target_user_id"] = target
    state["status"] = "active"
    state["started_at"] = datetime.now(timezone.utc).isoformat()
    await _event(session, game, "vote_state", state)
    await session.commit()
    return {"finished": False, "target_user_id": target, "result": result}


async def toggle_vote2_candidate(session, game, user_id: int):
    state = await _latest_vote_state(session, game.id)
    if not state or state.get("phase") != "vote1_complete":
        raise ValueError("مرحله انتخاب دفاع فعال نیست.")
    candidates = {int(x) for x in state.get("qualified_candidates", [])}
    if int(user_id) not in candidates:
        raise ValueError("این بازیکن به حدنصاب دفاع نرسیده است.")
    selected = {int(x) for x in state.get("defense_candidates", [])}
    if int(user_id) in selected:
        selected.remove(int(user_id))
    else:
        selected.add(int(user_id))
    state["defense_candidates"] = list(selected)
    await _event(session, game, "vote2_candidate_selection", {
        "round_no": int(state["round_no"]), "user_id": int(user_id),
        "selected": int(user_id) in selected,
    })
    await session.commit()
    return sorted(selected)


async def start_vote2(session, game):
    state = await _latest_vote_state(session, game.id)
    if not state or state.get("phase") != "vote1_complete":
        raise ValueError("ابتدا باید رای اول تمام شود.")
    candidates = [int(x) for x in state.get("defense_candidates", [])]
    if game.voting_mode == "auto" and not candidates:
        candidates = [int(x) for x in state.get("qualified_candidates", [])]
    if not candidates:
        raise ValueError("حداقل یک بازیکن باید برای دفاع انتخاب شود.")
    round_no = int(state["round_no"])
    game.phase = "defense"
    await _event(session, game, "vote2_started", {
        "round_no": round_no, "candidates": candidates, "selection_mode": game.vote2_selection_mode,
    })
    await _event(session, game, "vote2_state", {
        "round_no": round_no, "phase": "defense",
        "index": 0, "queue": candidates, "target_user_id": candidates[0],
        "status": "active", "started_at": datetime.now(timezone.utc).isoformat(),
    })
    await session.commit()
    return candidates[0]


async def advance_defense_turn(session, game):
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "vote2_state"
    ).order_by(GameEvent.id.desc()))
    event = result.scalars().first()
    if not event:
        raise ValueError("نوبت دفاع پیدا نشد.")
    state = _payload(event)
    if state.get("status") != "active":
        raise ValueError("نوبت دفاع فعال نیست.")
    state["status"] = "finished"
    idx = int(state.get("index", 0))
    queue = [int(x) for x in state.get("queue", [])]
    if idx + 1 >= len(queue):
        game.phase = "voting2"
        await _event(session, game, "vote_state", {
            "round_no": int(state["round_no"]), "phase": "vote2",
            "index": 0, "queue": queue, "target_user_id": queue[0],
            "status": "active", "started_at": datetime.now(timezone.utc).isoformat(),
        })
        await session.commit()
        return {"finished": True, "target_user_id": queue[0], "candidates": queue}
    state["index"] = idx + 1
    state["target_user_id"] = queue[idx + 1]
    state["started_at"] = datetime.now(timezone.utc).isoformat()
    state["status"] = "active"
    await _event(session, game, "vote2_state", state)
    await session.commit()
    return {"finished": False, "target_user_id": queue[idx + 1]}


async def finish_vote2(session, game):
    state = await _latest_vote_state(session, game.id)
    if not state or state.get("phase") != "vote2" or state.get("status") != "active":
        raise ValueError("رای دوم فعال نیست.")
    round_no = int(state["round_no"])
    target_id = int(state["target_user_id"])
    records = await _vote_records_for_target(session, game, round_no, "vote2", target_id)
    state["status"] = "finished"
    await _event(session, game, "vote2_target_finished", {
        "round_no": round_no, "target_user_id": target_id, "vote_count": len(records),
    })
    queue = [int(x) for x in state.get("queue", [])]
    idx = int(state.get("index", 0))
    if idx + 1 < len(queue):
        next_id = queue[idx + 1]
        state["index"] = idx + 1
        state["target_user_id"] = next_id
        state["started_at"] = datetime.now(timezone.utc).isoformat()
        state["status"] = "active"
        await _event(session, game, "vote_state", state)
        await session.commit()
        return {"finished": False, "target_user_id": next_id, "records": records}
    # Final vote2 result is intentionally resolved by the host/game engine later.
    game.phase = "vote2_complete"
    state["status"] = "finished"
    await _event(session, game, "vote2_completed", {
        "round_no": round_no, "candidates": queue,
    })
    await session.commit()
    return {"finished": True, "candidates": queue, "records": records}


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
            row[0].exit_type = "death"
            eliminated = row[1]
    await _event(session, game, "voting_resolved",
                 {"round_no": round_no, "eliminated_user_id": eliminated.id if eliminated else None, "tie": len(leaders) != 1})
    winner = await check_winner(session, game.id)
    if winner:
        await finalize_game(session, game, winner)
        await session.commit()
        return {"resolved": True, "winner": winner, "eliminated": eliminated, "tie": len(leaders) != 1}
    game.phase = "night"
    await _event(session, game, "phase_changed", {"to": "night", "round_no": round_no})
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
    """Finalize a game with a manually selected or engine-detected result."""
    if game.status == "finished":
        return
    existing = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "stats_recorded"
    ))
    if existing.scalars().first():
        return
    valid = {"citizen", "mafia", "independent", "citizen_independent", "draw"}
    if winner not in valid:
        raise ValueError("نتیجه بازی نامعتبر است.")
    game.status, game.phase, game.finished_at = "finished", "result", datetime.now(timezone.utc)
    for player, user, role in await all_players(session, game.id):
        user.games_played += 1
        winning = (
            (winner == "mafia" and role and role.team == "mafia")
            or (winner == "citizen" and role and role.team == "citizen")
            or (winner == "independent" and role and role.team == "independent")
            or (winner == "citizen_independent" and role and role.team in {"citizen", "independent"})
        )
        if winning:
            user.games_won += 1
            if role.team == "mafia":
                user.mafia_wins += 1
            elif role.team == "citizen":
                user.citizen_wins += 1
            elif role.team == "independent":
                user.independent_wins += 1
    newly_earned = await record_game_result(session, game.id, winner)
    await _event(session, game, "stats_recorded", {
        "winner": winner,
        "reports": {
            str(user_id): {
                **{k: v for k, v in report.items() if k != "achievements"},
                "achievements": [a.key for a in report.get("achievements", [])],
            }
            for user_id, report in newly_earned.items()
        },
    })


def _scenario_challenge_mode(game) -> str:
    # Scenario.challenge_mode is the source of truth. The fallback keeps old
    # databases compatible until the migration has been applied.
    mode = getattr(getattr(game, "scenario", None), "challenge_mode", None)
    return mode or "limited"


async def current_turn(session, game_id: int) -> dict | None:
    result = await session.execute(
        select(GameEvent).where(
            GameEvent.game_id == game_id,
            GameEvent.event_type == "turn_state",
        ).order_by(GameEvent.id.desc())
    )
    event = result.scalars().first()
    return _payload(event) if event else None


async def _current_scenario(session, game):
    return await session.get(Scenario, game.scenario_id)


async def is_user_silenced(session, game_id: int, user_id: int, round_no: int) -> bool:
    player = (await session.execute(select(GamePlayer).where(
        GamePlayer.game_id == game_id, GamePlayer.user_id == user_id
    ))).scalar_one_or_none()
    if player and player.silence_until_round == round_no:
        return True
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game_id,
        GameEvent.event_type == "silence",
    ).order_by(GameEvent.id.desc()))
    for event in result.scalars():
        data = _payload(event)
        if data.get("round_no") == round_no and data.get("user_id") == user_id:
            return bool(data.get("active"))
    return False


async def choose_leader(session, game, leader_user_id: int | None = None):
    if game.status != "running" or game.phase != "setup":
        raise ValueError("مرحله انتخاب سردست فعال نیست.")
    players = await alive_players(session, game.id)
    if not players:
        raise ValueError("بازیکن زنده‌ای برای انتخاب سردست وجود ندارد.")
    alive_ids = {user.id for _, user, _ in players}
    auto_selected = leader_user_id is None
    if leader_user_id is None:
        import secrets
        leader_user_id = secrets.choice(sorted(alive_ids))
    if leader_user_id not in alive_ids:
        raise ValueError("سردست باید یکی از بازیکنان زنده باشد.")
    round_no = await current_round(session, game.id)
    await _event(session, game, "leader_selected", {
        "round_no": round_no, "leader_user_id": leader_user_id,
        "mode": "auto" if auto_selected else "manual",
    })
    await session.commit()
    return {"leader_user_id": leader_user_id, "round_no": round_no, "mode": "auto" if auto_selected else "manual"}


async def start_round(session, game):
    if game.status != "running" or game.phase != "setup":
        raise ValueError("مرحله شروع دور فعال نیست.")
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "leader_selected"
    ).order_by(GameEvent.id.desc()))
    leader_event = result.scalars().first()
    if not leader_event:
        raise ValueError("ابتدا باید سردست انتخاب شود.")
    data = _payload(leader_event)
    leader_id = int(data["leader_user_id"])
    game.phase = "day"
    game.started_at = game.started_at or datetime.now(timezone.utc)
    await start_day_turns(session, game, leader_id)
    return {"leader_user_id": leader_id, "round_no": int(data.get("round_no", 1))}


async def start_day_turns(session, game, first_user_id: int | None = None):
    if game.status != "running" or game.phase != "day":
        raise ValueError("مرحله روز فعال نیست.")
    round_no = await current_round(session, game.id)
    players = await alive_players(session, game.id)
    if not players:
        raise ValueError("بازیکن زنده‌ای برای نوبت وجود ندارد.")
    silent_ids = {user.id for player, user, _ in players if player.silence_until_round == round_no}
    normal = [user.id for _, user, _ in players if user.id not in silent_ids]
    if first_user_id in normal:
        normal.remove(first_user_id)
        normal.insert(0, first_user_id)
    if not normal:
        raise ValueError("همه بازیکنان زنده این دور ساکت هستند.")
    extra_queue = [
        user.id for player, user, _ in players
        if player.extra_turn_round == round_no and user.id not in silent_ids
    ]
    await _event(session, game, "turn_queue", {
        "round_no": round_no, "queue": normal, "extra_queue": extra_queue,
        "index": 0, "extra_index": -1,
    })
    await _event(session, game, "turn_state", {
        "round_no": round_no, "kind": "main", "user_id": normal[0],
        "status": "active", "started_at": datetime.now(timezone.utc).isoformat(), "index": 0,
    })
    await session.commit()
    return normal[0]


async def _latest_turn_queue(session, game_id: int, round_no: int) -> dict | None:
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game_id,
        GameEvent.event_type == "turn_queue",
    ).order_by(GameEvent.id.desc()))
    for event in result.scalars():
        data = _payload(event)
        if data.get("round_no") == round_no:
            return data
    return None


async def _start_challenge_turn(session, game, requester_id: int, mode: str, source_request_id: int):
    turn = await current_turn(session, game.id)
    if not turn:
        raise ValueError("نوبت فعال پیدا نشد.")
    now = datetime.now(timezone.utc).isoformat()
    await _event(session, game, "turn_state", {
        "round_no": turn["round_no"],
        "kind": "challenge",
        "user_id": requester_id,
        "status": "active",
        "started_at": now,
        "challenge_request_id": source_request_id,
        "placement": mode,
        "resume_main_user_id": turn["user_id"],
    })
    await _event(session, game, "challenge_turn_started", {
        "round_no": turn["round_no"],
        "user_id": requester_id,
        "challenge_request_id": source_request_id,
    })
    return requester_id


async def request_challenge(session, game, requester: User):
    if game.status != "running" or game.phase != "day":
        raise ValueError("در حال حاضر امکان درخواست چالش نیست.")
    turn = await current_turn(session, game.id)
    if not turn or turn.get("kind") != "main" or turn.get("status") != "active":
        raise ValueError("در حال حاضر نوبت اصلی فعال نیست.")
    round_no = int(turn["round_no"])
    if requester.id == int(turn["user_id"]):
        raise ValueError("صاحب نوبت اصلی نمی‌تواند برای خودش درخواست چالش بدهد.")
    row = (await session.execute(select(GamePlayer).where(
        GamePlayer.game_id == game.id,
        GamePlayer.user_id == requester.id,
        GamePlayer.alive.is_(True),
    ))).scalar_one_or_none()
    if row is None:
        raise ValueError("فقط بازیکن زنده می‌تواند درخواست چالش بدهد.")
    if await is_user_silenced(session, game.id, requester.id, round_no):
        raise ValueError("بازیکن ساکت نمی‌تواند چالش بگیرد.")
    requester_player = await session.scalar(select(GamePlayer).where(
        GamePlayer.game_id == game.id, GamePlayer.user_id == requester.id
    ))
    if requester_player and requester_player.extra_turn_round == round_no:
        raise ValueError("بازیکن دارای ترن اضافه نمی‌تواند چالش بگیرد.")
    if turn.get("kind") == "extra":
        raise ValueError("در ترن اضافه امکان چالش وجود ندارد.")
    if not game.challenge_enabled:
        raise ValueError("درخواست چالش در تنظیمات این بازی غیرفعال است.")
    mode = getattr(game, "challenge_mode", "limited")
    if mode != "free":
        result = await session.execute(select(GameEvent).where(
            GameEvent.game_id == game.id,
            GameEvent.event_type == "challenge_turn_started",
        ).order_by(GameEvent.id.desc()))
        for event in result.scalars():
            data = _payload(event)
            if data.get("round_no") == round_no and data.get("user_id") == requester.id:
                raise ValueError("در این دور سهم چالش شما استفاده شده است.")
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id,
        GameEvent.event_type == "challenge_request",
    ).order_by(GameEvent.id.desc()))
    for event in result.scalars():
        data = _payload(event)
        if data.get("round_no") == round_no and data.get("requester_id") == requester.id and data.get("status") == "pending":
            raise ValueError("درخواست چالش شما هنوز در انتظار پاسخ است.")
    event = await _event(session, game, "challenge_request", {
        "round_no": round_no,
        "requester_id": requester.id,
        "target_turn_user_id": int(turn["user_id"]),
        "status": "pending",
        "message_id": None,
        "chat_id": None,
    }, requester.id)
    await session.commit()
    return {"event_id": event.id, "turn_user_id": int(turn["user_id"]), "round_no": round_no}


async def pending_challenge_requests(session, game):
    turn = await current_turn(session, game.id)
    if not turn or turn.get("kind") != "main":
        return []
    round_no = int(turn["round_no"])
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id,
        GameEvent.event_type == "challenge_request",
    ).order_by(GameEvent.id.asc()))
    rows = []
    for event in result.scalars():
        data = _payload(event)
        if data.get("round_no") == round_no and data.get("target_turn_user_id") == int(turn["user_id"]) and data.get("status") == "pending":
            rows.append((event, data))
    return rows


async def attach_challenge_request_message(session, event_id: int, chat_id: int, message_id: int):
    event = await session.get(GameEvent, event_id)
    if not event:
        return
    data = _payload(event)
    data["chat_id"] = chat_id
    data["message_id"] = message_id
    event.payload = json.dumps(data, ensure_ascii=False)
    await session.commit()


async def choose_challenge(session, game, turn_owner: User, request_event_id: int):
    if game.status != "running" or game.phase != "day":
        raise ValueError("چالش فقط در روز بازی قابل اجراست.")
    turn = await current_turn(session, game.id)
    if not turn or turn.get("kind") != "main" or int(turn["user_id"]) != turn_owner.id:
        raise ValueError("فقط صاحب نوبت اصلی می‌تواند یک درخواست را انتخاب کند.")
    event = await session.get(GameEvent, request_event_id)
    if not event or event.game_id != game.id or event.event_type != "challenge_request":
        raise ValueError("درخواست چالش پیدا نشد.")
    data = _payload(event)
    if data.get("status") != "pending":
        raise ValueError("این درخواست دیگر فعال نیست.")
    requester_id = int(data["requester_id"])
    requester = await session.get(User, requester_id)
    if requester:
        requester.challenges += 1
    round_no = int(turn["round_no"])
    if await is_user_silenced(session, game.id, requester_id, round_no):
        raise ValueError("این بازیکن ساکت است و نمی‌تواند چالش بگیرد.")
    # The selected request is granted; every other request in this turn is rejected.
    requests = await pending_challenge_requests(session, game)
    for req_event, req_data in requests:
        req_data["status"] = "accepted" if req_event.id == event.id else "rejected"
        req_event.payload = json.dumps(req_data, ensure_ascii=False)
    event_data = _payload(event)
    event_data["status"] = "accepted"
    event_data["accepted_at"] = datetime.now(timezone.utc).isoformat()
    event.payload = json.dumps(event_data, ensure_ascii=False)
    await session.flush()
    await session.commit()
    return {"requester_id": requester_id, "round_no": round_no, "request_event_id": event.id, "requests": requests}


async def select_challenge_placement(session, game, turn_owner: User, request_event_id: int, placement: str):
    if placement not in ("before", "after"):
        raise ValueError("جایگاه چالش نامعتبر است.")
    turn = await current_turn(session, game.id)
    if not turn or turn.get("kind") != "main" or int(turn["user_id"]) != turn_owner.id:
        raise ValueError("فقط صاحب نوبت اصلی می‌تواند زمان چالش را تعیین کند.")
    event = await session.get(GameEvent, request_event_id)
    if not event or event.game_id != game.id or event.event_type != "challenge_request":
        raise ValueError("درخواست چالش پیدا نشد.")
    data = _payload(event)
    if data.get("status") != "accepted":
        raise ValueError("ابتدا باید یک درخواست چالش انتخاب شود.")
    started = datetime.fromisoformat(turn["started_at"])
    now = datetime.now(timezone.utc)
    if now - started >= timedelta(minutes=1):
        placement = "after"
    data["placement"] = placement
    data["placement_selected_at"] = now.isoformat()
    event.payload = json.dumps(data, ensure_ascii=False)
    if placement == "before":
        turn["status"] = "paused"
        turn["paused_at"] = now.isoformat()
        await _event(session, game, "turn_state", turn)
        await _start_challenge_turn(session, game, int(data["requester_id"]), "before", event.id)
    else:
        await _event(session, game, "pending_after_challenge", {
            "round_no": turn["round_no"],
            "request_event_id": event.id,
            "requester_id": int(data["requester_id"]),
            "main_user_id": int(turn["user_id"]),
            "status": "pending",
        })
    await session.commit()
    return {"placement": placement, "requester_id": int(data["requester_id"]), "request_event_id": event.id}


async def auto_place_challenge_after(session, game, request_event_id: int):
    event = await session.get(GameEvent, request_event_id)
    if not event:
        return None
    data = _payload(event)
    if data.get("status") != "accepted" or data.get("placement"):
        return None
    turn = await current_turn(session, game.id)
    if not turn or turn.get("kind") != "main" or turn.get("status") != "active":
        return None
    return await select_challenge_placement(
        session, game, await session.get(User, int(turn["user_id"])), request_event_id, "after"
    )


async def _start_next_main_turn(session, game, round_no: int):
    queue = await _latest_turn_queue(session, game.id, round_no)
    players = await alive_players(session, game.id)
    alive_ids = {user.id for _, user, _ in players}
    if not queue:
        queue_ids = [user.id for _, user, _ in players]
        index = 0
        extra_queue = []
        extra_index = -1
    else:
        queue_ids = [uid for uid in queue.get("queue", []) if uid in alive_ids]
        index = int(queue.get("index", -1)) + 1
        extra_queue = [uid for uid in queue.get("extra_queue", []) if uid in alive_ids]
        extra_index = int(queue.get("extra_index", -1))
    if index < len(queue_ids):
        next_user = queue_ids[index]
        await _event(session, game, "turn_queue", {
            "round_no": round_no, "queue": queue_ids, "index": index,
            "extra_queue": extra_queue, "extra_index": extra_index,
        })
        await _event(session, game, "turn_state", {
            "round_no": round_no, "kind": "main", "user_id": next_user,
            "status": "active", "started_at": datetime.now(timezone.utc).isoformat(), "index": index,
        })
        return next_user
    extra_index += 1
    if extra_index < len(extra_queue):
        next_user = extra_queue[extra_index]
        await _event(session, game, "turn_queue", {
            "round_no": round_no, "queue": queue_ids, "index": len(queue_ids) - 1,
            "extra_queue": extra_queue, "extra_index": extra_index,
        })
        await _event(session, game, "turn_state", {
            "round_no": round_no, "kind": "extra", "user_id": next_user,
            "status": "active", "started_at": datetime.now(timezone.utc).isoformat(), "index": extra_index,
        })
        return next_user
    return None


async def next_turn(session, game):
    turn = await current_turn(session, game.id)
    if not turn or turn.get("status") not in ("active", "paused"):
        raise ValueError("نوبت فعالی وجود ندارد.")
    round_no = int(turn["round_no"])
    if turn.get("kind") == "defense":
        await _event(session, game, "turn_state", {**turn, "status": "finished", "finished_at": datetime.now(timezone.utc).isoformat()})
        state_result = await session.execute(select(GameEvent).where(
            GameEvent.game_id == game.id, GameEvent.event_type == "vote2_state"
        ).order_by(GameEvent.id.desc()))
        state_event = state_result.scalars().first()
        if not state_event:
            raise ValueError("صف دفاع پیدا نشد.")
        state = _payload(state_event)
        queue = [int(x) for x in state.get("queue", [])]
        idx = int(state.get("index", 0))
        if idx + 1 < len(queue):
            next_id = queue[idx + 1]
            state["index"] = idx + 1
            state["target_user_id"] = next_id
            state["started_at"] = datetime.now(timezone.utc).isoformat()
            state["status"] = "active"
            await _event(session, game, "vote2_state", state)
            await session.commit()
            return {"kind": "defense", "user_id": next_id}
        game.phase = "voting2"
        await _event(session, game, "vote_state", {
            "round_no": round_no, "phase": "vote2", "index": 0,
            "queue": queue, "target_user_id": queue[0],
            "status": "active", "started_at": datetime.now(timezone.utc).isoformat(),
        })
        await session.commit()
        return {"kind": "voting2", "user_id": queue[0]}
    if turn.get("kind") == "challenge":
        placement = turn.get("placement", "before")
        await _event(session, game, "turn_state", {**turn, "status": "finished", "finished_at": datetime.now(timezone.utc).isoformat()})
        if placement == "before":
            resume_user = turn.get("resume_main_user_id")
            await _event(session, game, "turn_state", {
                "round_no": round_no,
                "kind": "main",
                "user_id": resume_user,
                "status": "active",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "resumed_after_challenge": True,
                "challenge_consumed": True,
            })
            await session.commit()
            return {"kind": "main", "user_id": resume_user, "resumed": True}
        next_user = await _start_next_main_turn(session, game, round_no)
        await session.commit()
        return {"kind": "main", "user_id": next_user, "resumed": False} if next_user else {"kind": "finished_day"}
    # Main turn.
    after = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id,
        GameEvent.event_type == "pending_after_challenge",
    ).order_by(GameEvent.id.desc()))
    for event in after.scalars():
        data = _payload(event)
        if data.get("round_no") == round_no and data.get("status") == "pending":
            data["status"] = "started"
            event.payload = json.dumps(data, ensure_ascii=False)
            await _event(session, game, "turn_state", {**turn, "status": "finished", "finished_at": datetime.now(timezone.utc).isoformat()})
            await _start_challenge_turn(session, game, int(data["requester_id"]), "after", int(data["request_event_id"]))
            await session.commit()
            return {"kind": "challenge", "user_id": int(data["requester_id"]), "placement": "after"}
    await _event(session, game, "turn_state", {**turn, "status": "finished", "finished_at": datetime.now(timezone.utc).isoformat()})
    next_user = await _start_next_main_turn(session, game, round_no)
    await session.commit()
    return {"kind": "main", "user_id": next_user, "resumed": False} if next_user else {"kind": "finished_day"}


async def submit_challenge(session, game, challenger: User, target_user_id: int | None = None):
    # Backward-compatible wrapper: the target is always the current main-turn owner.
    return await request_challenge(session, game, challenger)


async def resolve_challenge(session, game, challenge_event_id: int, accepted: bool):
    # Kept as a compatibility shim for old callers. A challenge is now a request
    # that must be accepted by the owner of the current main turn, not by the target.
    event = await session.get(GameEvent, challenge_event_id)
    if not event or event.game_id != game.id or event.event_type != "challenge_request":
        raise ValueError("درخواست چالش پیدا نشد.")
    data = _payload(event)
    if data.get("status") != "pending":
        raise ValueError("این درخواست قبلاً تعیین تکلیف شده است.")
    data["status"] = "accepted" if accepted else "rejected"
    event.payload = json.dumps(data, ensure_ascii=False)
    await session.commit()
    return data



async def send_game_result_notifications(bot, session, game) -> None:
    event = await session.scalar(select(GameEvent).where(GameEvent.game_id == game.id, GameEvent.event_type == "stats_recorded").order_by(GameEvent.id.desc()))
    if not event:
        return
    data = _payload(event)
    for uid_text, report in (data.get("reports") or {}).items():
        user = await session.get(User, int(uid_text))
        if not user:
            continue
        stats = report.get("stats") or {}
        lines = []
        if user.notify_game_result:
            lines = ["📊 گزارش عملکرد بازی", "", "🏆 برد" if stats.get("won") else "نتیجه: این بازی را نبردید", f"💰 امتیاز این بازی: +{report.get('score_delta', 0)}", f"⭐ امتیاز فعلی: {report.get('score_after', user.score)}", "", f"🎯 شات: {stats.get('kills', 0)}", f"🩺 نجات: {stats.get('saves', 0)}", f"🔎 تحقیق موفق: {stats.get('investigation_hits', 0)}", f"🎯 رأی درست: {stats.get('correct_votes', 0)}", f"⚔️ چالش پذیرفته: {stats.get('accepted_challenges', 0)}", f"🥊 فیس‌آف: {stats.get('faceoff_wins', 0)} برد", f"🛡 بقا: {'بله' if stats.get('survived') else 'خیر'}", "", f"📈 امتیاز عملکرد: {stats.get('performance', 0)}/30", f"🏅 رتبه: {report.get('rank_after', '')}"]
        if report.get("rank_after") != report.get("rank_before") and user.notify_rank_changes:
            if not lines:
                lines = ["🏆 تغییر رتبه"]
            lines.append(f"🎉 ارتقای رتبه: {report.get('rank_before')} ← {report.get('rank_after')}")
        earned = report.get("achievements") or []
        if earned and user.notify_achievements:
            names = []
            for key in earned:
                achievement = await session.scalar(select(Achievement).where(Achievement.key == key))
                if achievement:
                    names.append(f"{achievement.icon} {achievement.name_fa} (+{achievement.points})")
            if names:
                if not lines:
                    lines = ["🏅 دستاوردهای جدید"]
                lines.extend(["", "🏅 دستاوردهای جدید:", *names])
        if not lines:
            continue
        try:
            await bot.send_message(user.telegram_id, "\n".join(lines))
        except Exception:
            pass