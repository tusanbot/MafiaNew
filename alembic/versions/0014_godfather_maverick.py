from alembic import op
import sqlalchemy as sa

revision = "0014_godfather_maverick"
down_revision = "0013_scenario_training_links"
branch_labels = None
depends_on = None

ROLE = (
    "maverick",
    "ماوریک",
    "independent",
    "مستقل سناریوی پدرخوانده؛ شب معرفی دو هدف و از شب دوم دریافت نتیجه استعلام آن‌ها. در شب دوم یکی را برای ادامه در جایگاهش انتخاب می‌کند؛ در صورت تبدیل، نقش و ساید فرد انتخاب‌شده را ادامه می‌دهد. تا وقتی مستقل است شب‌کشی و استعلام او منفی است و مافیا تا زمانی که ماوریک مستقل است با برابری نفرات برنده نمی‌شود.",
)

SCENARIO = (
    "godfather_maverick",
    "پدرخوانده-ماوریک",
    11,
    11,
    "limited",
    1,
)


def upgrade():
    op.execute(
        sa.text("""
            INSERT INTO roles(key, name_fa, team, description)
            VALUES (:key, :name, :team, :description)
            ON CONFLICT (key) DO UPDATE SET
                name_fa = EXCLUDED.name_fa,
                team = EXCLUDED.team,
                description = EXCLUDED.description
        """).bindparams(
            key=ROLE[0],
            name=ROLE[1],
            team=ROLE[2],
            description=ROLE[3],
        )
    )

    op.execute(
        sa.text("""
            INSERT INTO scenarios(
                key, name_fa, min_players, max_players, enabled,
                challenge_mode, challenge_limit
            )
            VALUES (
                :key, :name, :min_players, :max_players, true,
                :challenge_mode, :challenge_limit
            )
            ON CONFLICT (key) DO UPDATE SET
                name_fa = EXCLUDED.name_fa,
                min_players = EXCLUDED.min_players,
                max_players = EXCLUDED.max_players,
                enabled = true,
                challenge_mode = EXCLUDED.challenge_mode,
                challenge_limit = EXCLUDED.challenge_limit
        """).bindparams(
            key=SCENARIO[0],
            name=SCENARIO[1],
            min_players=SCENARIO[2],
            max_players=SCENARIO[3],
            challenge_mode=SCENARIO[4],
            challenge_limit=SCENARIO[5],
        )
    )


def downgrade():
    op.execute(
        sa.text("DELETE FROM scenarios WHERE key = :key").bindparams(
            key=SCENARIO[0]
        )
    )
    op.execute(
        sa.text("DELETE FROM roles WHERE key = :key").bindparams(
            key=ROLE[0]
        )
    )
