from app.scenarios.registry import RoleDefinition, ScenarioDefinition
CLASSIC=ScenarioDefinition(
 id="classic", name_fa="کلاسیک", min_players=7, max_players=20,
 roles=(RoleDefinition("godfather","پدرخوانده","mafia"),RoleDefinition("mafia","مافیا","mafia"),RoleDefinition("doctor","دکتر","citizen"),RoleDefinition("detective","کارآگاه","citizen"),RoleDefinition("citizen","شهروند ساده","citizen")),
)