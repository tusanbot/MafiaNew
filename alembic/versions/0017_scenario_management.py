from alembic import op
import sqlalchemy as sa

revision = "0017_scenario_management"
down_revision = "0016_detailed_stats"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    if "tags" not in user_columns:
        op.add_column("users", sa.Column("tags", sa.Text(), nullable=False, server_default=""))

    scenario_columns = {c["name"] for c in inspector.get_columns("scenarios")}
    if "description" not in scenario_columns:
        op.add_column("scenarios", sa.Column("description", sa.Text(), nullable=False, server_default=""))

    if "scenario_roles" not in set(inspector.get_table_names()):
        op.create_table(
            "scenario_roles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("scenario_id", "role_id", name="uq_scenario_role"),
        )

def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scenario_roles" in set(inspector.get_table_names()):
        op.drop_table("scenario_roles")
    scenario_columns = {c["name"] for c in sa.inspect(bind).get_columns("scenarios")}
    if "description" in scenario_columns:
        op.drop_column("scenarios", "description")
    user_columns = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "tags" in user_columns:
        op.drop_column("users", "tags")
