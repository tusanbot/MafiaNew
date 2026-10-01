from alembic import op
import sqlalchemy as sa

revision = "0021_scenario_role_duplicates"
down_revision = "0020_game_timing"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    constraints = sa.inspect(bind).get_unique_constraints("scenario_roles")
    for constraint in constraints:
        if constraint.get("name") == "uq_scenario_role":
            op.drop_constraint("uq_scenario_role", "scenario_roles", type_="unique")

def downgrade():
    bind = op.get_bind()
    constraints = sa.inspect(bind).get_unique_constraints("scenario_roles")
    if not any(c.get("name") == "uq_scenario_role" for c in constraints):
        op.create_unique_constraint("uq_scenario_role", "scenario_roles", ["scenario_id", "role_id"])
