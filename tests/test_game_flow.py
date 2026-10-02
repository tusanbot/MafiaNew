from app.core.game.engine import GameEngine, GameEnginePhase, GameState


def test_setup_can_start_day_after_leader_selection():
    state = GameState(GameEnginePhase.SETUP, 1)
    result = GameEngine.transition(state, GameEnginePhase.DAY)
    assert result.phase is GameEnginePhase.DAY
    assert result.round_no == 1


def test_day_cannot_skip_to_result_without_explicit_finish():
    state = GameState(GameEnginePhase.DAY, 1)
    result = GameEngine.transition(state, GameEnginePhase.RESULT)
    assert result.phase is GameEnginePhase.RESULT


def test_telegram_html_mention_is_nested_safely():
    from app.utils.text import tg_mention

    value = tg_mention(123456, "مهدی")
    assert value == '<b><a href="tg://user?id=123456">مهدی</a></b>'
