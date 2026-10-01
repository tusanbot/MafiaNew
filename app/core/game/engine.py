from dataclasses import dataclass
from enum import Enum

class TransitionError(ValueError):
    pass

class GameEnginePhase(str, Enum):
    SETUP = "setup"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    RESULT = "result"
    FINISHED = "finished"

ALLOWED = {
    GameEnginePhase.SETUP: {GameEnginePhase.NIGHT, GameEnginePhase.FINISHED},
    GameEnginePhase.NIGHT: {GameEnginePhase.DAY, GameEnginePhase.RESULT, GameEnginePhase.FINISHED},
    GameEnginePhase.DAY: {GameEnginePhase.VOTING, GameEnginePhase.NIGHT, GameEnginePhase.RESULT, GameEnginePhase.FINISHED},
    GameEnginePhase.VOTING: {GameEnginePhase.NIGHT, GameEnginePhase.RESULT, GameEnginePhase.FINISHED},
    GameEnginePhase.RESULT: {GameEnginePhase.NIGHT, GameEnginePhase.FINISHED},
    GameEnginePhase.FINISHED: set(),
}

@dataclass
class GameState:
    phase: GameEnginePhase
    round_no: int = 1

class GameEngine:
    @staticmethod
    def transition(state: GameState, target: GameEnginePhase) -> GameState:
        if target not in ALLOWED[state.phase]:
            raise TransitionError(f"transition {state.phase.value} -> {target.value} is not allowed")
        previous = state.phase
        state.phase = target
        if target == GameEnginePhase.NIGHT and previous != GameEnginePhase.SETUP:
            state.round_no += 1
        return state
