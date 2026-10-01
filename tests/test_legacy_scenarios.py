from app.scenarios.legacy import SCENARIOS, ROLE_DEFINITIONS, get_scenario

def test_all_legacy_scenarios_are_registered():
    assert len(SCENARIOS) == 12
    assert [s.name_fa for s in SCENARIOS] == [
        "سناریو تستی 2","روسی 6","بازپرس","کاپو","پدرخوانده-جک","پدرخوانده-نوسترا",
        "پدرخوانده-شرلوک","الکلاسیکو","قمار باز","زودیاک","کلاسیک 12","کلاسیک 13"
    ]

def test_legacy_role_counts_and_teams():
    expected = {
        "test_2": (1,1,0), "russian_6": (2,4,0), "interrogator_10": (3,7,0),
        "capo": (3,7,0), "godfather_jack": (3,7,1), "godfather_nostra": (3,7,1),
        "godfather_sherlock": (3,7,1), "el_clasico": (3,7,1), "gambler": (4,7,0),
        "zodiac": (3,8,1), "classic_12": (4,8,0), "classic_13": (4,8,1)
    }
    for scenario in SCENARIOS:
        counts = {"mafia":0,"citizen":0,"independent":0}
        for key in scenario.role_keys:
            counts[scenario.roles[[r.id for r in scenario.roles].index(key)].team] += 1
        assert (counts["mafia"],counts["citizen"],counts["independent"]) == expected[scenario.id]

def test_legacy_scenario_role_lists_preserve_duplicate_simple_citizens():
    assert len(get_scenario("godfather_jack").role_keys) == 11
    assert get_scenario("godfather_jack").role_keys.count("citizen") == 3
    assert get_scenario("classic_13").role_keys.count("novice") == 1

def test_legacy_roles_are_unique_by_key():
    keys=[r.id for r in ROLE_DEFINITIONS]
    assert len(keys)==len(set(keys))
