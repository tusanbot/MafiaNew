"""Merge the parallel Alembic migration branches.

Revision ID: 0037_merge_heads
Revises: 0036_achievement_tag_custom_emoji, 0017_user_score_history
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0037_merge_heads"
down_revision: Union[str, Sequence[str], None] = (
    "0036_achievement_tag_custom_emoji",
    "0017_user_score_history",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
