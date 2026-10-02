from alembic import op
import sqlalchemy as sa

revision = "0024_vote_per_target"
down_revision = "0023_voting_engine"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    uniques = {c.get("name") for c in sa.inspect(bind).get_unique_constraints("votes")}
    if "uq_vote_per_phase" in uniques:
        op.drop_constraint("uq_vote_per_phase", "votes", type_="unique")
    if "uq_vote_per_target" not in uniques:
        op.create_unique_constraint(
            "uq_vote_per_target",
            "votes",
            ["game_id", "voter_user_id", "target_user_id", "round_no", "phase"],
        )


def downgrade():
    bind = op.get_bind()
    uniques = {c.get("name") for c in sa.inspect(bind).get_unique_constraints("votes")}
    if "uq_vote_per_target" in uniques:
        op.drop_constraint("uq_vote_per_target", "votes", type_="unique")
    if "uq_vote_per_phase" not in uniques:
        op.create_unique_constraint(
            "uq_vote_per_phase",
            "votes",
            ["game_id", "voter_user_id", "round_no", "phase"],
        )
