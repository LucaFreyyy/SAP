from sap_engine.paths import ALL_FOOD_NAMES, ALL_PET_NAMES, TOKEN_NAMES, icon_path
from sap_engine.registry import load_registry


def test_registry_loads_core_data() -> None:
    registry = load_registry()

    assert len(registry.pets) == len(ALL_PET_NAMES)
    assert len(registry.foods) == len(ALL_FOOD_NAMES)
    assert len(registry.tokens) == len(TOKEN_NAMES)

    assert registry.pets["Duck"].tier == 1
    assert registry.pets["Dodo"].tier == 3
    assert registry.foods["Apple"].tier == 1
    assert registry.tokens["Coconut"].name == "Coconut"


def test_icon_paths_exist_for_sample_assets() -> None:
    assert icon_path("pets", "Duck").exists()
    assert icon_path("foods", "Apple").exists()
    assert icon_path("tokens", "Coconut").exists()
