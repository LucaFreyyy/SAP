"""CPU battle engine.

Team layout (matches wiki):
  index 0 = slot 1 = back
  index 4 = slot 5 = front / attacker
  'ahead' = higher index (toward the attacker)
  Pets compact toward the HIGH end (index 4) before each attack.

A pet is alive when (health + temporary_health) > 0.
Damage drains temporary_health first, then base health.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import BattleOutcome, BattleSnapshot, GameState, PetInstance, PlayerState
from ..triggers import TriggerEngine, _is_alive

MAX_BATTLE_STEPS = 200


@dataclass(slots=True)
class BattleStepResult:
    finished: bool
    outcome: BattleOutcome
    snapshot: BattleSnapshot


class BattleEngine:
    def __init__(self, triggers: TriggerEngine | None = None) -> None:
        self.triggers = triggers
        self.step_history: list[dict] = []
        self.current_step = 0

    def resolve(self, state: GameState) -> BattleStepResult:
        """Run the full battle from Start-of-Battle to resolution."""
        state.phase = state.phase.BATTLE
        snapshot = state.battle
        snapshot.finished = False
        snapshot.outcome = BattleOutcome.ONGOING
        self.step_history = []
        self.current_step = 0

        p0, p1 = state.players[0], state.players[1]

        # Save pre-battle team state keyed by pet identity
        pre0 = _snapshot_team(p0)
        pre1 = _snapshot_team(p1)

        # Capture initial state (before any battle steps)
        self._capture_step(state, p0, p1, "Start of Battle")

        # Reset per-battle counters
        for player in (p0, p1):
            player.hurt_count_this_battle = 0
            for pet in player.team:
                if pet is not None:
                    pet.knock_out_count = 0
                    pet.ability_uses = 0

        # --- Start-of-Battle step ---
        if self.triggers is not None:
            all_sob = sorted(
                [(pet, p0, p1) for pet in _living(p0)]
                + [(pet, p1, p0) for pet in _living(p1)],
                key=lambda t: -t[0].effective_attack,
            )
            for pet, player, opp in all_sob:
                if _is_alive(pet):
                    self.triggers.apply_start_of_battle_pet(pet, player, opp, self._summon_callback)

        # Capture state after SOB triggers
        self._capture_step(state, p0, p1, "After Start of Battle")

        # --- Combat loop ---
        while True:
            _compact(p0)
            _compact(p1)

            left = _last_alive(p0)
            right = _last_alive(p1)

            if left is None and right is None:
                return self._end(state, p0, p1, BattleOutcome.DRAW, snapshot, pre0, pre1)
            if left is None:
                p0.health -= 1
                p0.losses += 1
                p1.wins += 1
                return self._end(state, p0, p1, BattleOutcome.LOSS, snapshot, pre0, pre1)
            if right is None:
                p1.health -= 1
                p1.losses += 1
                p0.wins += 1
                return self._end(state, p0, p1, BattleOutcome.WIN, snapshot, pre0, pre1)

            snapshot.step_index += 1
            snapshot.attacker_name = left.name
            snapshot.defender_name = right.name

            # Capture state before this attack
            self._capture_step(state, p0, p1, f"Step {snapshot.step_index}: {left.name} vs {right.name}")

            if snapshot.step_index > MAX_BATTLE_STEPS:
                return self._end(state, p0, p1, BattleOutcome.DRAW, snapshot, pre0, pre1)

            # Before-attack triggers (Boar etc.)
            if self.triggers:
                self.triggers.apply_before_attack(left, p0, p1)
                self.triggers.apply_before_attack(right, p1, p0)

            # Calculate attack damage (Steak / Meat Bone bonuses)
            left_deals = self._calc_attack_damage(left)
            right_deals = self._calc_attack_damage(right)

            # Apply damage simultaneously
            if self.triggers:
                right_took = self.triggers._deal_damage_battle(
                    right, left_deals, p1, p0, is_hurt=False
                )
                left_took = self.triggers._deal_damage_battle(
                    left, right_deals, p0, p1, is_hurt=False
                )
            else:
                right_took = _raw_damage(right, left_deals)
                left_took = _raw_damage(left, right_deals)

            # Chili: deal 5 damage to the second enemy
            if left.perk == "chili":
                second = _second_alive(p1)
                if second is not None:
                    if self.triggers:
                        self.triggers._deal_damage_battle(second, 5, p1, p0,
                                                          is_hurt=True,
                                                          summon_callback=self._summon_callback)
                    else:
                        _raw_damage(second, 5)

            if right.perk == "chili":
                second = _second_alive(p0)
                if second is not None:
                    if self.triggers:
                        self.triggers._deal_damage_battle(second, 5, p0, p1,
                                                          is_hurt=True,
                                                          summon_callback=self._summon_callback)
                    else:
                        _raw_damage(second, 5)

            right_dead = not _is_alive(right)
            left_dead = not _is_alive(left)

            # Peanut: one-shot any enemy this pet hurts
            if not right_dead and left.perk == "peanut" and right_took > 0:
                right.health = -(right.temporary_health + 1)
                right.temporary_health = 0
                right_dead = True

            if not left_dead and right.perk == "peanut" and left_took > 0:
                left.health = -(left.temporary_health + 1)
                left.temporary_health = 0
                left_dead = True

            # Hurt triggers (only if pet survived)
            if self.triggers:
                if not right_dead and right_took > 0:
                    self.triggers.apply_hurt(right, p1, p0, self._summon_callback)
                if not left_dead and left_took > 0:
                    self.triggers.apply_hurt(left, p0, p1, self._summon_callback)

            # After-attack triggers (Elephant, Kangaroo, Snake)
            if self.triggers:
                if not left_dead:
                    self.triggers.apply_after_attack(left, p0, p1, self._summon_callback)
                if not right_dead:
                    self.triggers.apply_after_attack(right, p1, p0, self._summon_callback)

            # Faint handling + knock-out triggers
            if right_dead:
                right_idx = next((i for i, p in enumerate(p1.team) if p is right), -1)
                if right_idx >= 0:
                    p1.team[right_idx] = None
                if self.triggers:
                    if right_idx >= 0:
                        self.triggers.apply_faint(right, right_idx, p1, p0, self._summon_callback)
                    if _is_alive(left):
                        self.triggers.apply_knock_out(left, p0, p1, self._summon_callback)

            if left_dead:
                left_idx = next((i for i, p in enumerate(p0.team) if p is left), -1)
                if left_idx >= 0:
                    p0.team[left_idx] = None
                if self.triggers:
                    if left_idx >= 0:
                        self.triggers.apply_faint(left, left_idx, p0, p1, self._summon_callback)
                    if not right_dead and _is_alive(right):
                        self.triggers.apply_knock_out(right, p1, p0, self._summon_callback)

            self._process_pending_deaths(p0, p1)

    # ------------------------------------------------------------------

    def _end(self, state, p0, p1, outcome, snapshot, pre0, pre1):
        snapshot.finished = True
        snapshot.outcome = outcome
        state.last_battle_result = outcome

        # Save battle history to snapshot
        snapshot.step_history = self.step_history
        snapshot.current_step = len(self.step_history) - 1

        if outcome == BattleOutcome.WIN:
            p0.last_battle_result = BattleOutcome.WIN
            p1.last_battle_result = BattleOutcome.LOSS
        elif outcome == BattleOutcome.LOSS:
            p0.last_battle_result = BattleOutcome.LOSS
            p1.last_battle_result = BattleOutcome.WIN
        else:
            p0.last_battle_result = BattleOutcome.DRAW
            p1.last_battle_result = BattleOutcome.DRAW

        _restore_team(p0, pre0)
        _restore_team(p1, pre1)

        return BattleStepResult(True, outcome, snapshot)

    def _capture_step(self, state: GameState, p0: PlayerState, p1: PlayerState, description: str) -> None:
        """Capture the current state of both teams for battle replay."""
        step_data = {
            "description": description,
            "p0_team": self._serialize_team(p0),
            "p1_team": self._serialize_team(p1),
            "p0_health": p0.health,
            "p1_health": p1.health,
        }
        self.step_history.append(step_data)

    def _serialize_team(self, player: PlayerState) -> list[dict]:
        """Serialize a team to a dict for replay."""
        team_data = []
        for pet in player.team:
            if pet is None:
                team_data.append(None)
            else:
                team_data.append({
                    "name": pet.name,
                    "attack": pet.attack,
                    "health": pet.health,
                    "temporary_attack": pet.temporary_attack,
                    "temporary_health": pet.temporary_health,
                    "level": pet.level,
                    "experience": pet.experience,
                    "perk": pet.perk,
                    "perk_uses": pet.perk_uses,
                })
        return team_data

    def _calc_attack_damage(self, attacker: PetInstance) -> int:
        dmg = attacker.effective_attack
        if attacker.perk == "meat_bone":
            dmg += 3
        if attacker.perk == "steak" and attacker.perk_uses == 0:
            dmg += 20
            attacker.perk_uses = 1
        return dmg

    def _process_pending_deaths(self, p0: PlayerState, p1: PlayerState) -> None:
        for player, opp in [(p0, p1), (p1, p0)]:
            for i in range(len(player.team)):
                pet = player.team[i]
                if pet is not None and not _is_alive(pet):
                    player.team[i] = None
                    if self.triggers:
                        self.triggers.apply_faint(pet, i, player, opp, self._summon_callback)

    def _summon_callback(self, player: PlayerState, slot_idx: int, pet: PetInstance) -> None:
        if self.triggers:
            self.triggers.apply_friend_summoned(pet, player, self._summon_callback)

    @staticmethod
    def _frontmost_alive(player: PlayerState) -> PetInstance | None:
        return _last_alive(player)


# ------------------------------------------------------------------

def _living(player: PlayerState) -> list[PetInstance]:
    return [pet for pet in player.team if pet is not None and _is_alive(pet)]


def _last_alive(player: PlayerState) -> PetInstance | None:
    for i in range(len(player.team) - 1, -1, -1):
        pet = player.team[i]
        if pet is not None and _is_alive(pet):
            return pet
    return None


def _second_alive(player: PlayerState) -> PetInstance | None:
    found = 0
    for i in range(len(player.team) - 1, -1, -1):
        pet = player.team[i]
        if pet is not None and _is_alive(pet):
            found += 1
            if found == 2:
                return pet
    return None


def _compact(player: PlayerState) -> None:
    living = [pet for pet in player.team if pet is not None and _is_alive(pet)]
    n = len(player.team)
    player.team[:] = [None] * (n - len(living)) + living


def _raw_damage(target: PetInstance, amount: int) -> int:
    if target.temporary_health > 0:
        if amount <= target.temporary_health:
            target.temporary_health -= amount
        else:
            target.health -= (amount - target.temporary_health)
            target.temporary_health = 0
    else:
        target.health -= amount
    return amount


def _snapshot_team(player: PlayerState) -> list[tuple[PetInstance | None, dict | None]]:
    snap: list[tuple[PetInstance | None, dict | None]] = []
    for pet in player.team:
        if pet is None:
            snap.append((None, None))
            continue
        snap.append(
            (
                pet,
                {
                    "attack": pet.attack,
                    "health": pet.health,
                    "perk": pet.perk,
                    "perk_uses": pet.perk_uses,
                    "level": pet.level,
                    "experience": pet.experience,
                    "copied_ability": pet.copied_ability,
                    "temporary_attack": pet.temporary_attack,
                    "temporary_health": pet.temporary_health,
                },
            )
        )
    return snap


def _restore_team(player: PlayerState, snap: list[tuple[PetInstance | None, dict | None]]) -> None:
    for index, (pet, saved) in enumerate(snap):
        if pet is None or saved is None:
            player.team[index] = None
            continue
        player.team[index] = pet
        pet.attack = saved["attack"]
        pet.health = saved["health"]
        pet.perk = saved["perk"]
        pet.perk_uses = saved["perk_uses"]
        pet.level = saved["level"]
        pet.experience = saved["experience"]
        pet.knock_out_count = 0
        pet.ability_uses = 0
        pet.temporary_attack = 0
        pet.temporary_health = 0
        if pet.name == "Parrot":
            pet.copied_ability = None
        else:
            pet.copied_ability = saved.get("copied_ability")
