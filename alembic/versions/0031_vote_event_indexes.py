"""Add indexes for game event and vote hot paths.

Revision ID: 0031_vote_event_indexes
Revises: 0030_profile_tags
"""
from alembic import op

revision = "0031_vote_event_indexes"
down_revision = "0030_profile_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_game_events_game_type_id",
        "game_events",
        ["game_id", "event_type", "id"],
    )
    op.create_index(
        "ix_votes_game_round_phase_target",
        "votes",
        ["game_id", "round_no", "phase", "target_user_id"],
    )
    op.create_index(
        "ix_votes_game_round_phase_voter",
        "votes",
        ["game_id", "round_no", "phase", "voter_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_votes_game_round_phase_voter", table_name="votes")
    op.drop_index("ix_votes_game_round_phase_target", table_name="votes")
    op.drop_index("ix_game_events_game_type_id", table_name="game_events")
