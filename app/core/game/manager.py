from dataclasses import dataclass, field
from typing import Any
from app.core.game.state import GamePhase, GameStatus

@dataclass
class GameSession:
    game_id: str
    group_id: int
    scenario_id: str
    status: GameStatus = GameStatus.WAITING
    phase: GamePhase = GamePhase.LOBBY
    players: list[int] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)

class GameManager:
    def __init__(self) -> None:
        self._games: dict[str, GameSession] = {}
    def create(self, session: GameSession) -> GameSession:
        self._games[session.game_id] = session
        return session
    def get(self, game_id: str) -> GameSession | None:
        return self._games.get(game_id)
    def remove(self, game_id: str) -> None:
        self._games.pop(game_id, None)
