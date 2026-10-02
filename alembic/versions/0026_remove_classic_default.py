from alembic import op
import sqlalchemy as sa

revision = "0026_remove_classic_default"
down_revision = "0025_voting_rules"
branch_labels = None
depends_on = None


def upgrade():
    # Keep historical games intact, but remove the legacy hardcoded scenario
    # from all selectable/default scenario lists.
    op.execute(sa.text(
        "UPDATE scenarios SET enabled = FALSE WHERE key = 'classic'"
    ))


def downgrade():
    op.execute(sa.text(
        "UPDATE scenarios SET enabled = TRUE WHERE key = 'classic'"
    ))
