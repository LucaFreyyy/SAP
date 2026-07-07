from __future__ import annotations

from dataclasses import dataclass

from ..models import BattleOutcome, BattleSnapshot, GameState, PetInstance, PlayerState
from ..triggers import TriggerEngine
from ..rng import SeededRNG


@dataclass(slots=True)
class BattleStepResult:
    finished: bool
    outcome: BattleOutcome
    snapshot: BattleSnapshot


class BattleEngine:
    """Minimal CPU battle loop that is intentionally easy to swap for richer trigger logic later."""

    def __init__(self, triggers: TriggerEngine | None = None) -> None:
        self.triggers = triggers

    def resolve(self, state: GameState) -> BattleStepResult:
        state.phase = state.phase.BATTLE
        snapshot = state.battle
        snapshot.finished = False
        snapshot.outcome = BattleOutcome.ONGOING

        if self.triggers is not None:
            self.triggers.apply_start_of_battle(state.players[0], state.players[1])
            self.triggers.apply_start_of_battle(state.players[1], state.players[0])

        while True:
            left = self._frontmost_alive(state.players[0])
            right = self._frontmost_alive(state.players[1])
            if left is None and right is None:
                snapshot.finished = True
                snapshot.outcome = BattleOutcome.DRAW
                state.last_battle_result = BattleOutcome.DRAW
                state.players[0].last_battle_result = BattleOutcome.DRAW
                state.players[1].last_battle_result = BattleOutcome.DRAW
                return BattleStepResult(True, BattleOutcome.DRAW, snapshot)
            if left is None:
                snapshot.finished = True
                snapshot.outcome = BattleOutcome.LOSS
                state.last_battle_result = BattleOutcome.LOSS
                state.players[0].health -= 1
                state.players[1].wins += 1
                state.players[0].last_battle_result = BattleOutcome.LOSS
                state.players[1].last_battle_result = BattleOutcome.WIN
                return BattleStepResult(True, BattleOutcome.LOSS, snapshot)
            if right is None:
                snapshot.finished = True
                snapshot.outcome = BattleOutcome.WIN
                state.last_battle_result = BattleOutcome.WIN
                state.players[1].health -= 1
                state.players[0].wins += 1
                state.players[0].last_battle_result = BattleOutcome.WIN
                state.players[1].last_battle_result = BattleOutcome.LOSS
                return BattleStepResult(True, BattleOutcome.WIN, snapshot)

            snapshot.step_index += 1
            snapshot.attacker_name = left.name
            snapshot.defender_name = right.name
            right.health -= left.attack
            left.health -= right.attack
            if self.triggers is not None:
                self.triggers.apply_after_attack(state.players[0], left)
                self.triggers.apply_after_attack(state.players[1], right)
            if snapshot.step_index > 200:
                snapshot.finished = True
                snapshot.outcome = BattleOutcome.DRAW
                state.last_battle_result = BattleOutcome.DRAW
                return BattleStepResult(True, BattleOutcome.DRAW, snapshot)

    @staticmethod
    def _frontmost_alive(player: PlayerState) -> PetInstance | None:
        for pet in player.team:
            if pet is not None and pet.health is not None and pet.health > 0:
                return pet
        return None
