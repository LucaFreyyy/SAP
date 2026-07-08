import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from sap_engine.models import PetInstance, ShopOffer
from sap_engine.ui.app import GameUI


def test_ui_bootstrap_creates_game_ui() -> None:
    ui = GameUI()
    assert ui.state is None
    assert ui.engine.registry.pets
    assert "Human vs Human" in ui.mode_buttons


def test_ui_routes_team_click_for_food_to_buy_food() -> None:
    ui = GameUI()
    ui._start_mode("Human vs Human")
    assert ui.state is not None

    player = ui.state.current_player()
    player.team[0] = PetInstance(definition=ui.registry.pets["Duck"])
    player.shop.slots[0] = ShopOffer(kind="food", name="Apple", tier=1)

    ui.handle_click(ui._shop_rect(0).center)
    ui.handle_click(ui._team_rect(0).center)

    assert player.team[0].attack == 3
    assert player.team[0].health == 3
    assert ui.status.startswith("Fed Apple")


def test_perk_icon_map_covers_all_perks() -> None:
    from sap_engine.models import PERK_NAMES
    from sap_engine.ui.app import PERK_ICON_MAP

    assert PERK_NAMES == set(PERK_ICON_MAP.keys())

