from alembic import op
import sqlalchemy as sa

revision = "0018_seed_scenario_roles"
down_revision = "0017_scenario_management"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    try:
        from app.scenarios.legacy import SCENARIOS
    except Exception:
        SCENARIOS = ()

    for definition in SCENARIOS:
        scenario = bind.execute(
            sa.text("SELECT id FROM scenarios WHERE key=:key"),
            {"key": definition.id},
        ).scalar()
        if scenario is None:
            continue
        existing = bind.execute(
            sa.text("SELECT 1 FROM scenario_roles WHERE scenario_id=:sid LIMIT 1"),
            {"sid": scenario},
        ).scalar()
        if existing:
            continue
        counts = {}
        order = []
        for key in definition.role_keys:
            if key not in counts:
                counts[key] = 0
                order.append(key)
            counts[key] += 1
        for position, key in enumerate(order):
            role_id = bind.execute(
                sa.text("SELECT id FROM roles WHERE key=:key"),
                {"key": key},
            ).scalar()
            if role_id is not None:
                bind.execute(
                    sa.text(
                        "INSERT INTO scenario_roles(scenario_id,role_id,count,position) "
                        "VALUES (:sid,:rid,:count,:position) "
                        "ON CONFLICT (scenario_id,role_id) DO NOTHING"
                    ),
                    {"sid": scenario, "rid": role_id, "count": counts[key], "position": position},
                )

def downgrade():
    # Do not remove user-created compositions; seeded rows are intentionally retained.
    pass
