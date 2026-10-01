import pytest
from app.core.game.engine import GameEngine, GameEnginePhase, GameState, TransitionError

def test_valid_transition():
    state = GameState(GameEnginePhase.SETUP)
    GameEngine.transition(state, GameEnginePhase.NIGHT)
    assert state.phase == GameEnginePhase.NIGHT

def test_invalid_transition():
    state = GameState(GameEnginePhase.SETUP)
    with pytest.raises(TransitionError):
        GameEngine.transition(state, GameEnginePhase.VOTING)
