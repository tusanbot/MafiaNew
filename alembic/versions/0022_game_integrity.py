from alembic import op
import sqlalchemy as sa

revision = "0022_game_integrity"
down_revision = "0021_scenario_role_duplicates"
branch_labels = None
depends_on = None


def _has_unique(bind, table, name):
    return any(
        c.get("name") == name
        for c in sa.inspect(bind).get_unique_constraints(table)
    )


def upgrade():
    bind = op.get_bind()

    if not _has_unique(bind, "game_players", "uq_game_player_user"):
        op.create_unique_constraint(
            "uq_game_player_user", "game_players", ["game_id", "user_id"]
        )
    if not _has_unique(bind, "game_players", "uq_game_player_seat"):
        op.create_unique_constraint(
            "uq_game_player_seat", "game_players", ["game_id", "seat"]
        )
    if not _has_unique(bind, "votes", "uq_vote_per_round"):
        op.create_unique_constraint(
            "uq_vote_per_round", "votes", ["game_id", "voter_user_id", "round_no"]
        )


def downgrade():
    bind = op.get_bind()
    if _has_unique(bind, "votes", "uq_vote_per_round"):
        op.drop_constraint("uq_vote_per_round", "votes", type_="unique")
    if _has_unique(bind, "game_players", "uq_game_player_seat"):
        op.drop_constraint("uq_game_player_seat", "game_players", type_="unique")
    if _has_unique(bind, "game_players", "uq_game_player_user"):
        op.drop_constraint("uq_game_player_user", "game_players", type_="unique")
