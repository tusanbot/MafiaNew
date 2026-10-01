from alembic import op
import sqlalchemy as sa

revision = "0013_scenario_training_links"
down_revision = "0012_game_challenge_limit"
branch_labels = None
depends_on = None

SCENARIO_LINKS = {
    "interrogator_10": ("https://whitesho.com/NewTvScenario/%D8%B3%D9%86%D8%A7%D8%B1%DB%8C%D9%88-%D8%A8%D8%A7%D8%B2%D9%BE%D8%B1%D8%B3-%D8%A8%D8%A7%D8%B2%DB%8C-%D9%85%D8%A7%D9%81%DB%8C%D8%A7", None),
    "capo": ("https://whitesho.com/MafiaCapo/%D8%B3%D9%86%D8%A7%D8%B1%DB%8C%D9%88-%DA%A9%D8%A7%D9%BE%D9%88-%D8%A8%D8%A7%D8%B2%DB%8C-%D9%85%D8%A7%D9%81%DB%8C%D8%A7", None),
    "godfather_jack": ("https://whitesho.com/GodFatherJackSparrowScenario/%D8%B3%D9%86%D8%A7%D8%B1%DB%8C%D9%88-%D9%BE%D8%AF%D8%B1%D8%AE%D9%88%D8%A7%D9%86%D8%AF%D9%87-%D8%AC%DA%A9-%DA%AF%D9%86%D8%AC%D8%B4%DA%A9%D9%87-%D8%A8%D8%A7%D8%B2%DB%8C-%D9%85%D8%A7%D9%81%DB%8C%D8%A7", None),
    "godfather_nostra": ("https://whitesho.com/GodFatherScenario/%D8%B3%D9%86%D8%A7%D8%B1%DB%8C%D9%88-%D9%BE%D8%AF%D8%B1%D8%AE%D9%88%D8%A7%D9%86%D8%AF%D9%87-%D8%A8%D8%A7%D8%B2%DB%8C-%D9%85%D8%A7%D9%81%DB%8C%D8%A7", None),
    "godfather_sherlock": ("https://whitesho.com/GodfatherSherlockholmes/%D8%B3%D9%86%D8%A7%D8%B1%DB%8C%D9%88-%D9%BE%D8%AF%D8%B1%D8%AE%D9%88%D8%A7%D9%86%D8%AF%D9%87-%D8%B4%D8%B1%D9%84%D9%88%DA%A9-%D9%87%D9%84%D9%85%D8%B2-%D8%A8%D8%A7%D8%B2%DB%8C-%D9%85%D8%A7%D9%81%DB%8C%D8%A7", None),
    "el_clasico": ("https://whitesho.com/MafiaElclasico/%D8%B3%D9%86%D8%A7%D8%B1%DB%8C%D9%88-%D8%A7%D9%84-%DA%A9%D9%84%D8%A7%D8%B3%DB%8C%DA%A9%D9%88-%D8%A8%D8%A7%D8%B2%DB%8C-%D9%85%D8%A7%D9%81%DB%8C%D8%A7", None),
    "zodiac": ("https://whitesho.com/ZodiacScenario/%D8%B3%D9%86%D8%A7%D8%B1%DB%8C%D9%88-%D8%B2%D9%88%D8%AF%DB%8C%D8%A7%DA%A9-%D8%A8%D8%A7%D8%B2%DB%8C-%D9%85%D8%A7%D9%81%DB%8C%D8%A7", None),
}

def _execute(stmt, **params):
    op.execute(stmt.bindparams(**params))

def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("scenarios")}
    if "training_url" not in cols:
        op.add_column("scenarios", sa.Column("training_url", sa.Text(), nullable=True))
    if "telegram_training_url" not in cols:
        op.add_column("scenarios", sa.Column("telegram_training_url", sa.Text(), nullable=True))
    for key, (training_url, telegram_training_url) in SCENARIO_LINKS.items():
        _execute(sa.text("""
            UPDATE scenarios
            SET training_url = :training_url,
                telegram_training_url = :telegram_training_url
            WHERE key = :key
        """), key=key, training_url=training_url, telegram_training_url=telegram_training_url)

def downgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("scenarios")}
    if "telegram_training_url" in cols:
        op.drop_column("scenarios", "telegram_training_url")
    if "training_url" in cols:
        op.drop_column("scenarios", "training_url")
