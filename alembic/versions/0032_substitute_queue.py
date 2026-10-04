"""Separate lobby reserves from the substitute (sub) queue.

Revision ID: 0032_substitute_queue
Revises: 0031_vote_event_indexes
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_substitute_queue"
down_revision = "0031_vote_event_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_players", sa.Column("is_substitute", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("game_players", sa.Column("substitute_position", sa.Integer(), nullable=True))
    op.create_index(
        "ix_game_players_game_substitute_position",
        "game_players",
        ["game_id", "is_substitute", "substitute_position"],
    )


def downgrade() -> None:
    op.drop_index("ix_game_players_game_substitute_position", table_name="game_players")
    op.drop_column("game_players", "substitute_position")
    op.drop_column("game_players", "is_substitute")
