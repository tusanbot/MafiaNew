from app.scenarios.classic import CLASSIC
from app.scenarios.legacy import SCENARIOS
from app.scenarios.registry import ScenarioRegistry
registry=ScenarioRegistry()
registry.register(CLASSIC)
for scenario in SCENARIOS: registry.register(scenario)
