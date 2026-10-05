"""Add invite button settings to group invitations.
Revision ID: 0043_invitation_button
Revises: 0042_group_invitation
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0043_invitation_button"
down_revision: Union[str, Sequence[str], None] = "0042_group_invitation"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("group_invitation_settings", sa.Column("invite_button_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("group_invitation_settings", sa.Column("invite_button_text", sa.String(length=100), nullable=False, server_default="🎮 ورود به بازی"))

def downgrade() -> None:
    op.drop_column("group_invitation_settings", "invite_button_text")
    op.drop_column("group_invitation_settings", "invite_button_enabled")
