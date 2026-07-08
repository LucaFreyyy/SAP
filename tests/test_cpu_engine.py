from sap_engine.cpu.game import CpuGameEngine
from sap_engine.registry import load_registry
from sap_engine.rng import SeededRNG


def test_cpu_game_engine_creates_two_player_match() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(7))

    state = engine.new_game(["Alpha", "Beta"])

    assert state.phase.value == "shop"
    assert state.players[0].health == 6
    assert state.players[1].health == 6
    assert state.active_player_index == 0
    assert state.players[0].gold == 10
    assert len(state.players[0].shop.slots) == 9
    assert sum(slot is not None for slot in state.players[0].shop.slots[:3]) >= 1
    assert all(slot is None for slot in state.players[0].shop.slots[3:8])


def test_cpu_game_engine_can_advance_a_turn() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(11))
    state = engine.new_game(["Alpha", "Beta"])

    result = engine.end_shop_turn(state)

    assert result.phase.value == "shop"
    assert state.active_player_index == 1
    assert state.players[1].gold == 10


def test_shop_layout_scales_with_turn() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(9))
    state = engine.new_game(["Alpha", "Beta"])

    state.players[0].turn = 5
    engine.shop.roll(state.players[0])
    assert len(state.players[0].shop.slots) == 9
    assert sum(slot is not None for slot in state.players[0].shop.slots[:4]) >= 1
    assert all(slot is None for slot in state.players[0].shop.slots[4:7])

    state.players[0].turn = 9
    engine.shop.roll(state.players[0])
    assert sum(slot is not None for slot in state.players[0].shop.slots[:5]) >= 1


def test_cpu_game_engine_resolves_battle_after_second_player() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(11))
    state = engine.new_game(["Alpha", "Beta"])

    engine.end_shop_turn(state)
    result = engine.end_shop_turn(state)

    assert result.phase.value == "battle"
    assert result.battle_pending is True
    resolved = engine.resolve_battle_and_start_next_round(state)
    assert resolved.phase.value == "shop"
    assert state.turn == 2
    assert state.active_player_index == 0


def test_game_finishes_after_round_limit() -> None:
    registry = load_registry()
    engine = CpuGameEngine(registry, SeededRNG(12))
    state = engine.new_game(["Alpha", "Beta"])

    state.turn = 25
    state.players[0].actions = 4
    state.players[1].actions = 7
    state.players[0].health = 5
    state.players[1].health = 5

    engine.end_shop_turn(state)
    engine.end_shop_turn(state)
    result = engine.resolve_battle_and_start_next_round(state)

    assert result.phase.value == "transition"
    assert state.finished is True
    assert state.winner_index == 0
    assert state.finish_reason in {"health_tiebreak", "actions_tiebreak"}
