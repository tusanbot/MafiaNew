from app.services.voting_rules import (
    threshold_for_count,
    build_phase_rules,
    normalize_rules,
    resolve_single_vote2,
    resolve_multi_vote2,
)


def test_half_rules():
    assert threshold_for_count(10, "half_up") == 5
    assert threshold_for_count(9, "half_up") == 5
    assert threshold_for_count(10, "half_plus_one_odd") == 5
    assert threshold_for_count(9, "half_plus_one_odd") == 5
    assert threshold_for_count(10, "half_minus_one_odd") == 5
    assert threshold_for_count(9, "half_minus_one_odd") == 3


def test_revoked_players_do_not_reduce_threshold_denominator():
    rules = normalize_rules({"vote1_threshold_mode": "half_up"})
    snapshot = build_phase_rules(
        rules,
        phase="vote1",
        voter_base_ids=list(range(1, 8)),
        eligible_voter_ids=[1, 2, 3, 4, 5],
        revoked_voter_ids=[6, 7],
    )
    assert snapshot["voter_base_count"] == 7
    assert snapshot["eligible_voter_count"] == 5
    assert snapshot["threshold"] == 4


def test_defenders_can_be_excluded_without_counting_revocations_as_players_lost():
    rules = normalize_rules({
        "vote1_threshold_mode": "half_up",
        "vote2_defenders_can_vote": False,
    })
    snapshot = build_phase_rules(
        rules,
        phase="vote2",
        voter_base_ids=[1, 2, 3, 4, 5, 6, 7],
        eligible_voter_ids=[1, 2, 3, 4, 5],
        revoked_voter_ids=[6, 7],
        defenders=[6, 7],
    )
    assert snapshot["voter_base_count"] == 7
    assert snapshot["eligible_voter_count"] == 5


def test_multi_highest_vote_rule():
    result = resolve_multi_vote2({10: 0, 11: 1}, normalize_rules({
        "vote2_multi_resolution": "highest",
    }))
    assert result["leaders"] == [11]
    assert result["eliminated_ids"] == [11]


def test_single_vote2_uses_vote1_rule():
    rules = normalize_rules({
        "vote1_threshold_mode": "half_up",
        "vote2_single_threshold_mode": "same_as_vote1",
    })
    result = resolve_single_vote2(4, 7, rules)
    assert result["threshold"] == 4
    assert result["qualified"] is True
