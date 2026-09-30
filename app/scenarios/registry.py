from dataclasses import dataclass

@dataclass(frozen=True)
class RoleDefinition:
    id: str
    name_fa: str
    team: str
    description: str = ""

@dataclass(frozen=True)
class ScenarioDefinition:
    id: str
    name_fa: str
    min_players: int
    max_players: int
    roles: tuple[RoleDefinition, ...] = ()

class ScenarioRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ScenarioDefinition] = {}
    def register(self, scenario: ScenarioDefinition) -> None:
        self._items[scenario.id] = scenario
    def get(self, scenario_id: str) -> ScenarioDefinition | None:
        return self._items.get(scenario_id)
    def all(self) -> tuple[ScenarioDefinition, ...]:
        return tuple(self._items.values())
