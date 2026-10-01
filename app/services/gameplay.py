import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Game, GameEvent, GamePlayer, Role, User, Vote, Scenario
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
            row[0].exit_type = "death"
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
    players_to_reset = (await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id))).scalars().all()
    for player in players_to_reset:
        if player.extra_turn_round == round_no:
            player.extra_turn_round = None
        if player.silence_until_round == round_no:
            player.silence_until_round = None
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
    await _event(session, game, "stats_recorded", {"winner": winner})


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
