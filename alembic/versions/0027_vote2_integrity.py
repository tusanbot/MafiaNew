from alembic import op
import sqlalchemy as sa

revision = "0027_vote2_integrity"
down_revision = "0026_remove_classic_default"
branch_labels = None
depends_on = None


def upgrade():
    # vote2 is a single ballot per voter. The application already enforces
    # this, but concurrent/replayed callbacks can race between the SELECT and
    # INSERT. Remove any historical duplicates deterministically first, then
    # enforce the invariant at the database layer.
    op.execute(sa.text("""
        DELETE FROM votes v
        USING votes older
        WHERE v.phase = 'vote2'
          AND older.phase = 'vote2'
          AND v.game_id = older.game_id
          AND v.voter_user_id = older.voter_user_id
          AND v.round_no = older.round_no
          AND v.id > older.id
    """))
    op.create_index(
        "uq_votes_vote2_one_ballot",
        "votes",
        ["game_id", "voter_user_id", "round_no"],
        unique=True,
        postgresql_where=sa.text("phase = 'vote2'"),
    )


def downgrade():
    op.drop_index("uq_votes_vote2_one_ballot", table_name="votes")
