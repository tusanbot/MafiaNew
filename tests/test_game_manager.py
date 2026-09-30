from app.core.game.manager import GameManager, GameSession

def test_create_and_get_game() -> None:
    manager = GameManager()
    session = GameSession(game_id="test", group_id=-100, scenario_id="classic")
    manager.create(session)
    assert manager.get("test") is session
