"""Configurable voting rules for Mafia scenarios.

The key distinction in this module is between:
- voter_base: players whose normal voting right exists and therefore count
  toward a scenario threshold;
- eligible_voters: players actually allowed to cast a vote in this phase.

A disciplinary vote-right revocation removes a player only from eligible_voters.
It MUST NOT reduce voter_base, so disciplinary penalties continue to affect
the team's chances as intended.
"""

from __future__ import annotations

from math import ceil, floor
from typing import Any


DEFAULT_RULES: dict[str, Any] = {
    "vote1_threshold_mode": "half_up",
    "vote1_threshold_value": 0,
    "vote2_single_threshold_mode": "same_as_vote1",
    "vote2_multi_resolution": "threshold",
    "vote2_multi_threshold_mode": "same_as_vote1",
    "vote2_defenders_can_vote": True,
    "vote2_visibility": "public",
    "vote2_tie_policy": "no_elimination",
}


def normalize_rules(raw: dict[str, Any] | None) -> dict[str, Any]:
    rules = dict(DEFAULT_RULES)
    if isinstance(raw, dict):
        for key in rules:
            if key in raw:
                rules[key] = raw[key]
    return rules


def threshold_for_count(count: int, mode: str, value: int = 0) -> int:
    """Return the minimum votes required by a threshold mode.

    half_up: at least 50%; odd populations round upward.
    half_plus_one_odd: even -> 50%, odd -> 50% + 1.
    half_minus_one_odd: even -> 50%, odd -> 50% - 1.
    fixed: exact configured vote count.
    percentage: ceil(count * value / 100).
    """
    count = max(0, int(count))
    mode = mode or "half_up"

    if mode == "fixed":
        return max(0, int(value or 0))
    if mode == "percentage":
        return max(0, ceil(count * int(value or 0) / 100))
    if mode == "half_plus_one_odd":
        return ceil(count / 2) + 1 if count % 2 else count // 2
    if mode == "half_minus_one_odd":
        return max(0, ceil(count / 2) - 1) if count % 2 else count // 2

    # Default: minimum 50%, rounded up for an odd population.
    return ceil(count / 2)


def threshold_label(mode: str, value: int = 0) -> str:
    return {
        "half_up": "حداقل ۵۰٪",
        "half_plus_one_odd": "۵۰٪ و در فرد +۱",
        "half_minus_one_odd": "۵۰٪ و در فرد −۱",
        "fixed": f"{int(value or 0)} رأی ثابت",
        "percentage": f"{int(value or 0)}٪",
    }.get(mode, "حداقل ۵۰٪")


def build_phase_rules(
    scenario_rules: dict[str, Any] | None,
    *,
    phase: str,
    voter_base_ids: list[int],
    eligible_voter_ids: list[int],
    revoked_voter_ids: list[int] | None = None,
    defenders: list[int] | None = None,
) -> dict[str, Any]:
    rules = normalize_rules(scenario_rules)
    revoked = {int(x) for x in (revoked_voter_ids or [])}
    base = [int(x) for x in voter_base_ids]
    eligible = [int(x) for x in eligible_voter_ids]
    payload = {
        "phase": phase,
        "voter_base_ids": base,
        "voter_base_count": len(base),
        "eligible_voter_ids": eligible,
        "eligible_voter_count": len(eligible),
        "revoked_voter_ids": sorted(revoked),
        "defenders": [int(x) for x in (defenders or [])],
    }
    if phase == "vote1":
        mode = str(rules["vote1_threshold_mode"])
        value = int(rules.get("vote1_threshold_value") or 0)
        payload.update({
            "threshold_mode": mode,
            "threshold_value": value,
            "threshold": threshold_for_count(len(base), mode, value),
        })
    else:
        payload.update({
            "visibility": str(rules["vote2_visibility"]),
            "defenders_can_vote": bool(rules["vote2_defenders_can_vote"]),
            "multi_resolution": str(rules["vote2_multi_resolution"]),
            "tie_policy": str(rules["vote2_tie_policy"]),
        })
    return payload


def resolve_single_vote2(
    vote_count: int,
    voter_base_count: int,
    rules: dict[str, Any],
) -> dict[str, Any]:
    mode = str(rules.get("vote2_single_threshold_mode") or "same_as_vote1")
    if mode == "same_as_vote1":
        mode = str(rules.get("vote1_threshold_mode") or "half_up")
        value = int(rules.get("vote1_threshold_value") or 0)
    else:
        value = int(rules.get("vote2_single_threshold_value") or 0)
    threshold = threshold_for_count(voter_base_count, mode, value)
    return {
        "threshold": threshold,
        "qualified": int(vote_count) >= threshold,
        "threshold_mode": mode,
        "threshold_value": value,
    }


def resolve_multi_vote2(
    vote_counts: dict[int, int],
    rules: dict[str, Any],
) -> dict[str, Any]:
    resolution = str(rules.get("vote2_multi_resolution") or "threshold")
    if not vote_counts:
        return {"resolution": resolution, "eliminated_ids": [], "tie": False, "max_votes": 0}

    maximum = max(vote_counts.values())
    leaders = sorted(uid for uid, count in vote_counts.items() if count == maximum)

    if resolution == "threshold":
        mode = str(rules.get("vote2_multi_threshold_mode") or "same_as_vote1")
        if mode == "same_as_vote1":
            mode = str(rules.get("vote1_threshold_mode") or "half_up")
            value = int(rules.get("vote1_threshold_value") or 0)
        else:
            value = int(rules.get("vote2_multi_threshold_value") or 0)
        # The caller supplies the base count through the state.  This helper
        # only resolves candidates once the threshold has been calculated.
        return {
            "resolution": "threshold",
            "leaders": leaders,
            "max_votes": maximum,
            "tie": len(leaders) > 1,
            "threshold_mode": mode,
            "threshold_value": value,
        }

    # Plurality / highest-votes resolution.
    return {
        "resolution": resolution,
        "leaders": leaders,
        "eliminated_ids": [] if len(leaders) != 1 else leaders,
        "max_votes": maximum,
        "tie": len(leaders) > 1,
        "tie_policy": str(rules.get("vote2_tie_policy") or "no_elimination"),
    }
