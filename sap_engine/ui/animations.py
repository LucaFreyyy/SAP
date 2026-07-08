from __future__ import annotations

from dataclasses import dataclass

from ..models import PetInstance, PlayerState


HIGHLIGHT_FRAMES = 70
GOLDEN_BORDER_FRAMES = 70
ROTATION_FORWARD_FRAMES = 8
ROTATION_BACK_FRAMES = 20
MAX_ROTATION_DEG = 45.0


@dataclass(slots=True)
class PetVisualFX:
    rotation_deg: float = 0.0
    rotation_phase: str = "idle"  # idle | forward | back
    rotation_frame: int = 0
    highlight_attack: int = 0
    highlight_health: int = 0
    highlight_xp: int = 0
    highlight_perk: int = 0
    perk_lost: str | None = None
    perk_lost_frames: int = 0
    golden_border: int = 0


@dataclass(slots=True)
class PetSnapshot:
    attack: int
    health: int
    temporary_attack: int
    temporary_health: int
    experience: int
    level: int
    perk: str | None = None
    perk_uses: int = 0


ReplayKey = tuple[str, int, int]


class AnimationTracker:
    def __init__(self) -> None:
        self._fx: dict[int, PetVisualFX] = {}
        self._replay_fx: dict[ReplayKey, PetVisualFX] = {}

    def clear(self) -> None:
        self._fx.clear()
        self._replay_fx.clear()

    def _fx_for(self, pet: PetInstance) -> PetVisualFX:
        key = id(pet)
        if key not in self._fx:
            self._fx[key] = PetVisualFX()
        return self._fx[key]

    def trigger_replay_abilities(self, ability_triggers: list[dict], current: dict) -> None:
        for entry in ability_triggers:
            player_idx = entry.get("player")
            if player_idx is None:
                continue
            uid = entry.get("uid")
            if uid is None:
                slot_idx = entry.get("slot")
                if slot_idx is None or slot_idx < 0:
                    continue
                team = current.get(f"p{player_idx}_team", [])
                if slot_idx >= len(team) or team[slot_idx] is None:
                    continue
                uid = team[slot_idx].get("uid")
            if uid is None:
                continue
            self._start_rotation(self._replay_fx.setdefault(("replay", player_idx, uid), PetVisualFX()))

    def on_replay_step_changed(self, current: dict, previous: dict | None) -> None:
        if previous is None:
            return
        for player_idx, team_key in ((0, "p0_team"), (1, "p1_team")):
            current_team = current.get(team_key, [])
            previous_team = previous.get(team_key, [])
            prev_by_uid: dict[int, dict] = {}
            for pet_data in previous_team:
                if pet_data is None:
                    continue
                uid = pet_data.get("uid")
                if uid is not None:
                    prev_by_uid[uid] = pet_data
            for pet_data in current_team:
                if pet_data is None:
                    continue
                uid = pet_data.get("uid")
                if uid is None:
                    continue
                prev_data = prev_by_uid.get(uid)
                if prev_data is None:
                    continue
                old_atk = prev_data["attack"] + prev_data.get("temporary_attack", 0)
                new_atk = pet_data["attack"] + pet_data.get("temporary_attack", 0)
                old_hp = prev_data["health"] + prev_data.get("temporary_health", 0)
                new_hp = pet_data["health"] + pet_data.get("temporary_health", 0)
                atk_changed = new_atk != old_atk
                hp_changed = new_hp != old_hp
                xp_changed = (
                    pet_data.get("experience", 0) != prev_data.get("experience", 0)
                    or pet_data.get("level", 0) != prev_data.get("level", 0)
                )
                perk_changed = (
                    pet_data.get("perk") != prev_data.get("perk")
                    or pet_data.get("perk_uses", 0) != prev_data.get("perk_uses", 0)
                )
                if not (atk_changed or hp_changed or xp_changed or perk_changed):
                    continue
                key = ("replay", player_idx, uid)
                fx = self._replay_fx.setdefault(key, PetVisualFX())
                if atk_changed:
                    fx.highlight_attack = HIGHLIGHT_FRAMES
                if hp_changed:
                    fx.highlight_health = HIGHLIGHT_FRAMES
                if xp_changed:
                    fx.highlight_xp = GOLDEN_BORDER_FRAMES
                    fx.golden_border = GOLDEN_BORDER_FRAMES
                if perk_changed:
                    self._note_perk_change(
                        fx,
                        prev_data.get("perk"),
                        pet_data.get("perk"),
                    )

    def on_replay_step_change(
        self,
        current: dict,
        previous: dict | None,
        player_idx: int,
    ) -> None:
        self.on_replay_step_changed(current, previous)

    @staticmethod
    def _start_rotation(fx: PetVisualFX) -> None:
        if fx.rotation_phase == "idle":
            fx.rotation_phase = "forward"
            fx.rotation_frame = 0
            fx.rotation_deg = 0.0

    def on_ability_trigger(self, pet: PetInstance, _player: PlayerState) -> None:
        self._start_rotation(self._fx_for(pet))

    @staticmethod
    def _note_perk_change(
        fx: PetVisualFX,
        old_perk: str | None,
        new_perk: str | None,
    ) -> None:
        fx.highlight_perk = HIGHLIGHT_FRAMES
        if old_perk and old_perk != new_perk:
            fx.perk_lost = old_perk
            fx.perk_lost_frames = HIGHLIGHT_FRAMES

    def note_xp_gain(self, pet: PetInstance, *, leveled_up: bool = False) -> None:
        fx = self._fx_for(pet)
        fx.highlight_xp = GOLDEN_BORDER_FRAMES
        fx.golden_border = GOLDEN_BORDER_FRAMES
        if leveled_up:
            fx.highlight_attack = max(fx.highlight_attack, HIGHLIGHT_FRAMES)
            fx.highlight_health = max(fx.highlight_health, HIGHLIGHT_FRAMES)

    def snapshot_player(self, player: PlayerState) -> dict[int, PetSnapshot]:
        snaps: dict[int, PetSnapshot] = {}
        for pet in player.team:
            if pet is None:
                continue
            snaps[id(pet)] = PetSnapshot(
                attack=pet.attack,
                health=pet.health,
                temporary_attack=pet.temporary_attack,
                temporary_health=pet.temporary_health,
                experience=pet.experience,
                level=pet.level,
                perk=pet.perk,
                perk_uses=pet.perk_uses,
            )
        return snaps

    def snapshot_state(self, players: list[PlayerState]) -> dict[int, PetSnapshot]:
        snaps: dict[int, PetSnapshot] = {}
        for player in players:
            snaps.update(self.snapshot_player(player))
        return snaps

    def record_changes(
        self,
        before: dict[int, PetSnapshot],
        after: dict[int, PetSnapshot],
        *,
        xp_pet_ids: set[int] | None = None,
    ) -> None:
        xp_pet_ids = xp_pet_ids or set()
        for pet_id, new_snap in after.items():
            old_snap = before.get(pet_id)
            if old_snap is None:
                continue
            fx = self._fx.setdefault(pet_id, PetVisualFX())
            old_eff_atk = old_snap.attack + old_snap.temporary_attack
            new_eff_atk = new_snap.attack + new_snap.temporary_attack
            old_eff_hp = old_snap.health + old_snap.temporary_health
            new_eff_hp = new_snap.health + new_snap.temporary_health
            if new_eff_atk != old_eff_atk or new_snap.temporary_attack != old_snap.temporary_attack:
                fx.highlight_attack = HIGHLIGHT_FRAMES
            if new_eff_hp != old_eff_hp or new_snap.temporary_health != old_snap.temporary_health:
                fx.highlight_health = HIGHLIGHT_FRAMES
            if new_snap.experience != old_snap.experience or new_snap.level != old_snap.level:
                fx.highlight_xp = GOLDEN_BORDER_FRAMES
                fx.golden_border = GOLDEN_BORDER_FRAMES
                if new_snap.level > old_snap.level:
                    fx.highlight_attack = max(fx.highlight_attack, HIGHLIGHT_FRAMES)
                    fx.highlight_health = max(fx.highlight_health, HIGHLIGHT_FRAMES)
            if new_snap.perk != old_snap.perk or new_snap.perk_uses != old_snap.perk_uses:
                self._note_perk_change(fx, old_snap.perk, new_snap.perk)
        for pet_id in xp_pet_ids:
            if pet_id in after:
                self._fx.setdefault(pet_id, PetVisualFX())
                self._fx[pet_id].highlight_xp = GOLDEN_BORDER_FRAMES
                self._fx[pet_id].golden_border = GOLDEN_BORDER_FRAMES

    def tick(self) -> None:
        self._tick_map(self._fx)
        self._tick_map(self._replay_fx)

    def _tick_map(self, store: dict) -> None:
        dead: list = []
        for key, fx in store.items():
            if fx.highlight_attack > 0:
                fx.highlight_attack -= 1
            if fx.highlight_health > 0:
                fx.highlight_health -= 1
            if fx.highlight_xp > 0:
                fx.highlight_xp -= 1
            if fx.highlight_perk > 0:
                fx.highlight_perk -= 1
            if fx.perk_lost_frames > 0:
                fx.perk_lost_frames -= 1
                if fx.perk_lost_frames == 0:
                    fx.perk_lost = None
            if fx.golden_border > 0:
                fx.golden_border -= 1

            if fx.rotation_phase == "forward":
                fx.rotation_frame += 1
                progress = min(1.0, fx.rotation_frame / ROTATION_FORWARD_FRAMES)
                fx.rotation_deg = MAX_ROTATION_DEG * progress
                if fx.rotation_frame >= ROTATION_FORWARD_FRAMES:
                    fx.rotation_phase = "back"
                    fx.rotation_frame = 0
            elif fx.rotation_phase == "back":
                fx.rotation_frame += 1
                progress = min(1.0, fx.rotation_frame / ROTATION_BACK_FRAMES)
                fx.rotation_deg = MAX_ROTATION_DEG * (1.0 - progress)
                if fx.rotation_frame >= ROTATION_BACK_FRAMES:
                    fx.rotation_phase = "idle"
                    fx.rotation_deg = 0.0
                    fx.rotation_frame = 0

            if (
                fx.rotation_phase == "idle"
                and fx.highlight_attack == 0
                and fx.highlight_health == 0
                and fx.highlight_xp == 0
                and fx.highlight_perk == 0
                and fx.perk_lost_frames == 0
                and fx.golden_border == 0
            ):
                dead.append(key)
        for key in dead:
            del store[key]

    def fx(self, pet: PetInstance | None) -> PetVisualFX | None:
        if pet is None:
            return None
        return self._fx.get(id(pet))

    def replay_fx(self, player_idx: int, pet_uid: int | None) -> PetVisualFX | None:
        if pet_uid is None:
            return None
        return self._replay_fx.get(("replay", player_idx, pet_uid))
