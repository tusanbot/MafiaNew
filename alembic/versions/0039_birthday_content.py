"""Add configurable birthday video and greeting templates.
Revision ID: 0039_birthday_content
Revises: 0038_birthdays
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0039_birthday_content"
down_revision: Union[str, Sequence[str], None] = "0038_birthdays"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "birthday_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_file_id", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "birthday_message_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.bulk_insert(
        sa.table("birthday_message_templates", sa.column("text", sa.Text())),
        [
            {"text": "🎂 تولدت مبارک {mention} عزیز! 🎉\\nامیدواریم سال جدید زندگیت پر از اتفاق‌های خوب و بردهای شیرین باشه."},
            {"text": "🥳 امروز روز توئه {name}!\\nاز طرف بچه‌های مافیا: تولدت مبارک و همیشه خوشحال و موفق باشی. 🎁"},
            {"text": "🎈 یک سال دیگه هم گذشت و هنوز از دستت خلاص نشدیم {name}! 😄\\nتولدت مبارک؛ سال فوق‌العاده‌ای برات آرزو می‌کنیم."},
            {"text": "🎉 تولدت مبارک {mention}!\\nامروز رأی‌گیری ممنوع؛ فقط تبریک و کیک! 🍰"},
            {"text": "💐 بهترین آرزوها برای {name} در روز تولدش!\\nتنت سالم، دلت شاد و بازی‌هات پر از برد. 🎂"},
        ],
    )


def downgrade() -> None:
    op.drop_table("birthday_message_templates")
    op.drop_table("birthday_settings")
