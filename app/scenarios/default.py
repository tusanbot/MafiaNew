from app.scenarios.legacy import SCENARIOS
from app.scenarios.registry import ScenarioRegistry

registry=ScenarioRegistry()
for scenario in SCENARIOS:
    registry.register(scenario)
