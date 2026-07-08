from sap_engine.cpu.game import CpuGameEngine
from sap_engine.models import BattleOutcome, Phase, PetInstance
from sap_engine.registry import load_registry
from sap_engine.rng import SeededRNG


def test_swan_grants_gold_at_start_of_turn() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(1))
    state = engine.new_game(["Alpha", "Beta"])

    swan = PetInstance(definition=registry.pets["Swan"])
    state.players[0].team[0] = swan
    state.players[0].gold = 0
    engine.triggers.apply_start_of_turn(state.players[0])

    assert state.players[0].gold == swan.level


def test_pig_grants_gold_on_sell() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(2))
    state = engine.new_game(["Alpha", "Beta"])

    pig = PetInstance(definition=registry.pets["Pig"])
    state.players[0].team[0] = pig
    state.players[0].gold = 0

    result = engine.shop.sell_pet(state.players[0], 0)

    assert result.success is True
    assert state.players[0].gold == 2


def test_mosquito_hits_enemy_at_start_of_battle() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(3))
    state = engine.new_game(["Alpha", "Beta"])

    mosquito = PetInstance(definition=registry.pets["Mosquito"])
    duck = PetInstance(definition=registry.pets["Duck"])
    duck.health = 1
    state.players[0].team[0] = mosquito
    state.players[1].team[0] = duck

    state.phase = Phase.BATTLE
    result = engine.battle.resolve(state)

    assert result.finished is True
    assert result.outcome == BattleOutcome.WIN
    assert state.players[0].last_battle_result == BattleOutcome.WIN


def test_battle_state_is_restored_after_resolution() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(8))
    state = engine.new_game(["Alpha", "Beta"])

    boar = PetInstance(definition=registry.pets["Boar"])
    duck = PetInstance(definition=registry.pets["Duck"])
    duck.health = 1
    state.players[0].team[0] = boar
    state.players[1].team[0] = duck

    result = engine.battle.resolve(state)

    assert result.finished is True
    assert state.players[0].team[0] is not None
    assert state.players[0].team[0].temporary_attack == 0
    assert state.players[0].team[0].temporary_health == 0
    assert state.players[0].team[0].attack == registry.pets["Boar"].attack
    assert state.players[1].team[0] is not None
    assert state.players[1].team[0].health == 1
