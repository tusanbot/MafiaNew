from dataclasses import dataclass
from datetime import datetime

@dataclass
class PersistedGame:
    game_id:str
    group_id:int
    scenario_id:str
    status:str
    phase:str
    created_at:datetime|None=None

class GameRepository:
    """Persistence contract; DB implementation can be swapped without changing game logic."""
    async def save(self, game:PersistedGame)->PersistedGame: raise NotImplementedError
    async def get(self, game_id:str)->PersistedGame|None: raise NotImplementedError
