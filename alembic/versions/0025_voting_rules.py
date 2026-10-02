from alembic import op
import sqlalchemy as sa

revision = "0025_voting_rules"
down_revision = "0024_vote_per_target"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scenarios",
        sa.Column("voting_rules", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("scenarios", "voting_rules")
