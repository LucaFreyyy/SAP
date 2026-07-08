"""FIFO battle ability queue (wiki §9).

Simultaneous triggers are sorted by descending attack (random ties) then appended
to the queue. Abilities triggered during resolution append to the tail.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..models import PetInstance, PlayerState
    from ..rng import SeededRNG
    from ..triggers import SummonCallback


STEP_LABELS = {
    "sob": "Start of Battle",
    "before_attack": "Before Attack",
    "hurt": "Hurt",
    "after_attack": "After Attack",
    "faint": "Faint",
    "friend_faint": "Friend Faints",
    "knock_out": "Knock Out",
    "friend_summoned": "Friend Summoned",
}


@dataclass(slots=True)
class BattleAbilityEvent:
    kind: str
    pet: PetInstance
    player: PlayerState
    opponent: PlayerState
    slot_idx: int | None = None
    tiger_level: int | None = None
    fainted_pet: PetInstance | None = None
    fainted_idx: int | None = None
    summoned_pet: PetInstance | None = None
    friend_faint_target_idx: int | None = None


BattleStepCallback = Callable[["BattleAbilityEvent"], None]


@dataclass
class BattleAbilityQueue:
    rng: SeededRNG
    events: list[BattleAbilityEvent] = field(default_factory=list)
    pending_hurts: list[tuple[PetInstance, PlayerState, PlayerState]] = field(default_factory=list)
    on_step: BattleStepCallback | None = None
    summon_callback: SummonCallback | None = None

    def clear(self) -> None:
        self.events.clear()
        self.pending_hurts.clear()
        self.on_step = None
        self.summon_callback = None

    def enqueue_batch(self, batch: list[BattleAbilityEvent]) -> None:
        if not batch:
            return
        batch.sort(key=lambda event: (-event.pet.effective_attack, self.rng.random()))
        self.events.extend(batch)

    def enqueue_chain(self, event: BattleAbilityEvent) -> None:
        self.events.append(event)

    def note_hurt(self, pet: PetInstance, player: PlayerState, opponent: PlayerState) -> None:
        self.pending_hurts.append((pet, player, opponent))

    def flush_hurts_to_queue(self) -> None:
        if not self.pending_hurts:
            return
        batch = [
            BattleAbilityEvent("hurt", pet, player, opponent)
            for pet, player, opponent in self.pending_hurts
        ]
        self.pending_hurts.clear()
        self.enqueue_batch(batch)

    def drain(self, executor: Callable[[BattleAbilityEvent], None]) -> None:
        while self.events:
            event = self.events.pop(0)
            executor(event)
            if self.on_step is not None:
                self.on_step(event)
            self.flush_hurts_to_queue()
