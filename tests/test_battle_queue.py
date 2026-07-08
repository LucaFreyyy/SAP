"""Tests for wiki §9 FIFO battle ability queue."""
from __future__ import annotations

from sap_engine.cpu.battle_queue import BattleAbilityEvent, BattleAbilityQueue
from sap_engine.cpu.game import CpuGameEngine
from sap_engine.models import Phase, PetInstance
from sap_engine.registry import load_registry
from sap_engine.rng import SeededRNG


def make_engine(seed: int = 42) -> CpuGameEngine:
    return CpuGameEngine(load_registry(), SeededRNG(seed))


def make_pet(engine: CpuGameEngine, name: str, **kwargs) -> PetInstance:
    defn = engine.registry.pets[name]
    return PetInstance(definition=defn, **kwargs)


def test_enqueue_batch_sorts_by_attack_desc() -> None:
    """Simultaneous triggers enter the FIFO sorted by descending attack."""
    engine = make_engine()
    p0 = engine.new_game(["A", "B"]).players[0]
    strong = make_pet(engine, "Peacock", attack=8, health=5)
    weak = make_pet(engine, "Peacock", attack=3, health=5)
    p0.team[3] = weak
    p0.team[4] = strong
    opp = engine.new_game(["C", "D"]).players[0]

    queue = BattleAbilityQueue(engine.rng)
    queue.enqueue_batch([
        BattleAbilityEvent("hurt", weak, p0, opp),
        BattleAbilityEvent("hurt", strong, p0, opp),
    ])

    assert [event.pet.effective_attack for event in queue.events] == [8, 3]


def test_chained_events_append_to_tail() -> None:
    """Abilities triggered during resolution append to the queue tail."""
    engine = make_engine()
    p0 = engine.new_game(["A", "B"]).players[0]
    peacock = make_pet(engine, "Peacock", attack=5, health=5)
    tiger = make_pet(engine, "Tiger", attack=2, health=5, level=2)
    p0.team[3] = tiger
    p0.team[4] = peacock
    opp = engine.new_game(["C", "D"]).players[0]

    queue = BattleAbilityQueue(engine.rng)
    queue.enqueue_batch([BattleAbilityEvent("hurt", peacock, p0, opp)])
    executed: list[str] = []

    def executor(event: BattleAbilityEvent) -> None:
        executed.append(event.pet.name)
        if event.tiger_level is None and event.pet is peacock:
            queue.enqueue_chain(
                BattleAbilityEvent("hurt", peacock, p0, opp, tiger_level=2)
            )

    queue.drain(executor)
    assert executed == ["Peacock", "Peacock"]


def test_battle_replay_step_per_ability_execution() -> None:
    """Each resolved ability during battle becomes its own replay step."""
    engine = make_engine(seed=77)
    state = engine.new_game(["Alpha", "Beta"])
    p0, p1 = state.players

    p0.team[4] = make_pet(engine, "Mosquito", attack=4, health=6)
    p1.team[4] = make_pet(engine, "Ant", attack=1, health=1)

    state.phase = Phase.BATTLE
    result = engine.battle.resolve(state)

    descriptions = [step["description"] for step in result.snapshot.step_history]
    assert "Start of Battle" in descriptions[0]
    assert any(d.startswith("Start of Battle: Mosquito") for d in descriptions)


def test_hurt_steps_fire_before_faint_in_replay() -> None:
    """Lethal attack damage still produces a Hurt step before faint resolution."""
    engine = make_engine(seed=88)
    state = engine.new_game(["Alpha", "Beta"])
    p0, p1 = state.players

    peacock = make_pet(engine, "Peacock", attack=1, health=1)
    p0.team[4] = peacock
    p1.team[4] = make_pet(engine, "Ant", attack=5, health=5)

    state.phase = Phase.BATTLE
    result = engine.battle.resolve(state)

    descriptions = [step["description"] for step in result.snapshot.step_history]
    hurt_idx = next(i for i, d in enumerate(descriptions) if d.startswith("Hurt: Peacock"))
    faint_idx = next(i for i, d in enumerate(descriptions) if d.startswith("Faint: Peacock"))
    assert hurt_idx < faint_idx
