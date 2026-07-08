from sap_engine.cpu.game import CpuGameEngine
from sap_engine.models import PetInstance, ShopOffer
from sap_engine.registry import load_registry
from sap_engine.rng import SeededRNG


def test_apple_applies_permanent_stats() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(4))
    state = engine.new_game(["Alpha", "Beta"])

    player = state.players[0]
    player.team[0] = PetInstance(definition=registry.pets["Duck"])
    player.shop.slots[0] = ShopOffer(kind="food", name="Apple", tier=1)

    result = engine.shop.buy_food(player, 0, 0)

    assert result.success is True
    assert player.team[0].attack == 3
    assert player.team[0].health == 3
    assert player.gold == 7


def test_canned_food_buffs_current_and_future_shop_pets() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(5))
    state = engine.new_game(["Alpha", "Beta"])

    player = state.players[0]
    player.team[0] = PetInstance(definition=registry.pets["Duck"])
    player.shop.slots[0] = ShopOffer(kind="food", name="Canned Food", tier=4)
    player.shop.slots[1] = ShopOffer(kind="pet", name="Beaver", tier=1)

    result = engine.shop.buy_food(player, 0)

    assert result.success is True
    assert player.shop_attack_bonus == 1
    assert player.shop_health_bonus == 1
    assert player.shop.slots[1].bonus_attack == 1
    assert player.shop.slots[1].bonus_health == 1

    player.turn = 3
    engine.shop.roll(player)
    pet_slots = [slot for slot in player.shop.slots if slot is not None and slot.kind == "pet"]
    assert pet_slots
    assert all(slot.bonus_attack == 1 and slot.bonus_health == 1 for slot in pet_slots)


def test_chocolate_levels_pet_and_grants_stats() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(6))
    state = engine.new_game(["Alpha", "Beta"])

    player = state.players[0]
    fish = PetInstance(definition=registry.pets["Fish"])
    player.team[0] = fish
    player.shop.slots[0] = ShopOffer(kind="food", name="Chocolate", tier=5)

    result = engine.shop.buy_food(player, 0, 0)

    assert result.success is True
    assert player.team[0].experience == 1
    assert player.team[0].attack == fish.definition.attack + 1
    assert player.team[0].health == fish.definition.health + 1
