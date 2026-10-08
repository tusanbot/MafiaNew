from __future__ import annotations

import json
from typing import Any


def remove_player(player: Any, exit_type: str) -> None:
    """Remove a player while keeping the GamePlayer row for later history/restore."""
    player.alive = False
    player.exit_type = exit_type
    player.silence_until_round = None
    player.extra_turn_round = None


def restore_removed_player(player: Any) -> bool:
    """Restore only a player removed through the normal death/remove action."""
    if getattr(player, "alive", False) or getattr(player, "exit_type", None) != "death":
        return False
    player.alive = True
    player.exit_type = None
    player.silence_until_round = None
    player.extra_turn_round = None
    return True


def apply_kick(player: Any, user: Any, penalty: int = 1) -> None:
    remove_player(player, "kick")
    user.kicks = int(getattr(user, "kicks", 0) or 0) + 1
    user.score = int(getattr(user, "score", 0) or 0) - int(penalty)


def swap_roles_for_faceoff(source: Any, destination: Any) -> None:
    """Swap roles, then remove the source player as a face-off exit."""
    source.role_id, destination.role_id = destination.role_id, source.role_id
    remove_player(source, "faceoff")


def silence_target_round(
    player: Any,
    round_no: int,
    phase: str,
    queue_payload: dict[str, Any] | None = None,
) -> int:
    """Set the round in which silence expires.

    At night the current round has already completed, so silence targets the
    next round. During the day, a player whose turn has already passed also
    gets silence in the next round.
    """
    target_round = int(round_no)
    if phase == "night":
        target_round += 1
    elif phase == "day" and queue_payload:
        try:
            queue = [int(x) for x in queue_payload.get("queue", [])]
            index = int(queue_payload.get("index", -1))
            if player.user_id in queue and queue.index(player.user_id) <= index:
                target_round += 1
        except (TypeError, ValueError):
            pass
    player.silence_until_round = target_round
    return target_round


def grant_extra_turn(player: Any, round_no: int) -> None:
    player.extra_turn_round = int(round_no)


def parse_turn_payload(payload: str | None) -> dict[str, Any]:
    try:
        value = json.loads(payload or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
