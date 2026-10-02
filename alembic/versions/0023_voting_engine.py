from alembic import op
import sqlalchemy as sa

revision = "0023_voting_engine"
down_revision = "0022_game_integrity"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    game_cols = {c["name"] for c in sa.inspect(bind).get_columns("games")}
    scenario_cols = {c["name"] for c in sa.inspect(bind).get_columns("scenarios")}
    vote_cols = {c["name"] for c in sa.inspect(bind).get_columns("votes")}

    for name, typ, default in (
        ("voting_pre_delay_seconds", sa.Integer(), "10"),
        ("vote_seconds", sa.Integer(), "10"),
        ("voting_mode", sa.String(20), "'manual'"),
        ("vote2_selection_mode", sa.String(20), "'manual'"),
    ):
        if name not in game_cols:
            op.add_column("games", sa.Column(name, typ, nullable=False, server_default=sa.text(default)))
    if "vote_defense_threshold" not in scenario_cols:
        op.add_column("scenarios", sa.Column("vote_defense_threshold", sa.Integer(), nullable=False, server_default="2"))
    if "phase" not in vote_cols:
        op.add_column("votes", sa.Column("phase", sa.String(20), nullable=False, server_default="vote1"))

    uniques = {c.get("name") for c in sa.inspect(bind).get_unique_constraints("votes")}
    if "uq_vote_per_round" in uniques:
        op.drop_constraint("uq_vote_per_round", "votes", type_="unique")
    if "uq_vote_per_phase" not in uniques:
        op.create_unique_constraint("uq_vote_per_phase", "votes", ["game_id", "voter_user_id", "round_no", "phase"])

    for table, names in (("games", ("voting_pre_delay_seconds", "vote_seconds", "voting_mode", "vote2_selection_mode")),
                         ("scenarios", ("vote_defense_threshold",)),
                         ("votes", ("phase",))):
        for name in names:
            op.alter_column(table, name, server_default=None)


def downgrade():
    bind = op.get_bind()
    uniques = {c.get("name") for c in sa.inspect(bind).get_unique_constraints("votes")}
    if "uq_vote_per_phase" in uniques:
        op.drop_constraint("uq_vote_per_phase", "votes", type_="unique")
    if "uq_vote_per_round" not in uniques:
        op.create_unique_constraint("uq_vote_per_round", "votes", ["game_id", "voter_user_id", "round_no"])
    for table, name in (("votes", "phase"), ("scenarios", "vote_defense_threshold"),
                        ("games", "vote2_selection_mode"), ("games", "voting_mode"),
                        ("games", "vote_seconds"), ("games", "voting_pre_delay_seconds")):
        cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        if name in cols:
            op.drop_column(table, name)
