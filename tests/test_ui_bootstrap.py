import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from sap_engine.ui.app import GameUI


def test_ui_bootstrap_creates_game_ui() -> None:
    ui = GameUI()
    assert ui.state is None
    assert ui.engine.registry.pets
    assert "Human vs Human" in ui.mode_buttons
