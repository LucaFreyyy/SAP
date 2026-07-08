"""Trigger engine: all pet ability and food perk logic.

Team layout convention (matches wiki):
  index 0 = slot 1 = back of team
  index 4 = slot 5 = front of team (the attacker)
  "ahead" = toward higher index (toward the front / attacker)
  "behind" = toward lower index (toward the back)
  Pets compact toward the HIGH end (index 4) before each attack.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from .models import BattleOutcome, PetDefinition, PetInstance, PlayerState, ShopOffer
from .paths import PETS_BY_TIER
from .registry import DataRegistry
from .rng import SeededRNG
from .cpu.shop_slots import insert_shop_offer_from_right
from .cpu.battle_queue import BattleAbilityEvent, BattleAbilityQueue, STEP_LABELS

# Faint-summon token stats indexed by level (1-based)
ZOMBIE_CRICKET_STATS = {1: (1, 1), 2: (2, 2), 3: (3, 3)}
RAM_STATS = {1: (2, 2), 2: (4, 4), 3: (6, 6)}
BUS_STATS = {1: (5, 3), 2: (10, 6), 3: (15, 9)}

SOB_ABILITIES = frozenset({
    "Mosquito", "Dodo", "Dolphin", "Crab", "Skunk", "Armadillo", "Crocodile", "Whale", "Leopard",
})
FAINT_ABILITIES = frozenset({
    "Ant", "Cricket", "Rat", "Hedgehog", "Flamingo", "Spider", "Sheep", "Deer", "Turtle",
    "Rooster", "Mammoth", "Badger",
})
HURT_ABILITIES = frozenset({"Peacock", "Camel", "Blowfish", "Gorilla"})
BEFORE_ATTACK_ABILITIES = frozenset({"Boar"})
KNOCK_OUT_ABILITIES = frozenset({"Hippo", "Rhino"})
FRIEND_SUMMONED_RESPONDERS = frozenset({"Horse", "Turkey", "Dog"})
FAINT_PERKS = frozenset({"honey", "mushroom"})


@dataclass(slots=True)
class TriggerResult:
    changed: bool
    message: str = ""


@dataclass(slots=True)
class _QueuedHurt:
    pet: PetInstance
    player: PlayerState
    other: PlayerState


SummonCallback = Callable[["PlayerState", int, "PetInstance"], None]
AbilityListener = Callable[[PetInstance, PlayerState], None]


def _is_alive(pet: PetInstance) -> bool:
    """A pet is alive if its effective health (base + temporary) > 0."""
    return (pet.health + pet.temporary_health) > 0


class TriggerEngine:
    def __init__(
        self,
        registry: DataRegistry,
        rng: SeededRNG,
        ability_listener: AbilityListener | None = None,
    ) -> None:
        self.registry = registry
        self.rng = rng
        self.ability_listener = ability_listener
        self._hurt_pending: list[_QueuedHurt] = []
        self._battle_queue = BattleAbilityQueue(rng)
        self._battle_mode = False
        self._executing_battle_event = False

    def enter_battle_mode(
        self,
        on_step,
        summon_callback: SummonCallback | None,
    ) -> None:
        self._battle_mode = True
        self._battle_queue.clear()
        self._battle_queue.on_step = on_step
        self._battle_queue.summon_callback = summon_callback

    def exit_battle_mode(self) -> None:
        self._battle_mode = False
        self._battle_queue.clear()

    def enqueue_battle_batch(self, events: list[BattleAbilityEvent]) -> None:
        self._battle_queue.enqueue_batch(events)

    def enqueue_battle_chain(self, event: BattleAbilityEvent) -> None:
        self._battle_queue.enqueue_chain(event)

    def drain_battle_queue(self) -> None:
        self._battle_queue.drain(self._execute_battle_event)

    @staticmethod
    def _ability_name(pet: PetInstance) -> str:
        return pet.copied_ability or pet.name

    def _pet_has_faint_ability(self, pet: PetInstance) -> bool:
        if self._ability_name(pet) in FAINT_ABILITIES:
            return True
        if pet.name == "Whale":
            swallowed = pet.copied_ability or ""
            return swallowed.startswith("whale_swallowed:")
        return False

    def should_queue_sob(self, pet: PetInstance) -> bool:
        return self._ability_name(pet) in SOB_ABILITIES

    def should_queue_before_attack(self, attacker: PetInstance, player: PlayerState) -> bool:
        return self._ability_name(attacker) in BEFORE_ATTACK_ABILITIES

    def should_queue_after_attack(
        self,
        attacker: PetInstance,
        player: PlayerState,
        opponent: PlayerState,
    ) -> bool:
        if self._ability_name(attacker) == "Elephant":
            return self._friend_behind(player, attacker) is not None
        for pet in self._living_team(player):
            if pet is attacker:
                continue
            ability = self._ability_name(pet)
            if ability == "Kangaroo" and self._friend_ahead(player, pet) is attacker:
                return True
            if (
                ability == "Snake"
                and self._friend_ahead(player, pet) is attacker
                and pet.ability_uses < 5
            ):
                return True
        return False

    def should_queue_hurt(self, hurt_pet: PetInstance, hurt_player: PlayerState) -> bool:
        ability = self._ability_name(hurt_pet)
        if ability not in HURT_ABILITIES:
            return False
        if ability == "Gorilla" and hurt_pet.ability_uses >= hurt_pet.level:
            return False
        return True

    def should_queue_faint(
        self,
        fainted_pet: PetInstance,
        fainted_idx: int,
        player: PlayerState,
    ) -> bool:
        if self._pet_has_faint_ability(fainted_pet):
            return True
        if fainted_pet.perk in FAINT_PERKS:
            return True
        return False

    def should_queue_knock_out(self, attacker: PetInstance) -> bool:
        return self._ability_name(attacker) in KNOCK_OUT_ABILITIES

    def should_queue_friend_summoned(self, summoned_pet: PetInstance, player: PlayerState) -> bool:
        if self._ability_name(summoned_pet) == "Scorpion":
            return True
        for pet in self._living_team(player):
            if pet is summoned_pet:
                continue
            if self._ability_name(pet) in FRIEND_SUMMONED_RESPONDERS:
                return True
        return False

    def _apply_wolverine(
        self,
        wolverine: PetInstance,
        player: PlayerState,
        opponent: PlayerState,
    ) -> None:
        removal = 3 * wolverine.level
        for enemy in self._living_team(opponent):
            self._reduce_health_min_one(enemy, removal)

    def _execute_battle_event(self, event: BattleAbilityEvent) -> None:
        summon_callback = self._battle_queue.summon_callback
        self._executing_battle_event = True
        try:
            if event.kind == "sob":
                self.apply_start_of_battle_pet(
                    event.pet, event.player, event.opponent, summon_callback,
                    _tiger_level=event.tiger_level,
                )
            elif event.kind == "before_attack":
                self.apply_before_attack(
                    event.pet, event.player, event.opponent,
                    _tiger_level=event.tiger_level,
                )
            elif event.kind == "hurt":
                self.apply_hurt(
                    event.pet, event.player, event.opponent, summon_callback,
                    _tiger_level=event.tiger_level,
                    _triggers_wolverine=event.triggers_wolverine,
                )
            elif event.kind == "after_attack":
                self.apply_after_attack(
                    event.pet, event.player, event.opponent, summon_callback,
                    _tiger_level=event.tiger_level,
                )
            elif event.kind == "faint":
                fainted = event.fainted_pet or event.pet
                self.apply_faint(
                    fainted,
                    event.fainted_idx if event.fainted_idx is not None else -1,
                    event.player,
                    event.opponent,
                    summon_callback,
                    _tiger_level=event.tiger_level,
                )
            elif event.kind == "friend_faint":
                self._apply_friend_faint_reaction(
                    event.pet,
                    event.fainted_pet,
                    event.fainted_idx if event.fainted_idx is not None else -1,
                    event.player,
                    event.opponent,
                    summon_callback,
                    friend_idx=event.friend_faint_target_idx,
                )
            elif event.kind == "knock_out":
                self.apply_knock_out(
                    event.pet, event.player, event.opponent, summon_callback,
                    _tiger_level=event.tiger_level,
                )
            elif event.kind == "friend_summoned":
                summoned = event.summoned_pet or event.pet
                self.apply_friend_summoned(
                    summoned, event.player, summon_callback,
                    _tiger_level=event.tiger_level,
                )
            elif event.kind == "wolverine":
                self._apply_wolverine(event.pet, event.player, event.opponent)
        finally:
            self._executing_battle_event = False

    def _queue_tiger_sob(
        self,
        pet: PetInstance,
        player: PlayerState,
        opponent: PlayerState,
    ) -> None:
        if not self.should_queue_sob(pet):
            return
        for tiger in list(self._living_team(player)):
            if (tiger.copied_ability or tiger.name) != "Tiger":
                continue
            if self._friend_ahead(player, tiger) is pet:
                self.enqueue_battle_chain(
                    BattleAbilityEvent("sob", pet, player, opponent, tiger_level=tiger.level)
                )
                break

    def _queue_tiger_before_attack(
        self,
        attacker: PetInstance,
        player: PlayerState,
        opponent: PlayerState,
    ) -> None:
        if not self.should_queue_before_attack(attacker, player):
            return
        for tiger in list(self._living_team(player)):
            if (tiger.copied_ability or tiger.name) != "Tiger":
                continue
            if self._friend_ahead(player, tiger) is attacker:
                self.enqueue_battle_chain(
                    BattleAbilityEvent(
                        "before_attack", attacker, player, opponent, tiger_level=tiger.level
                    )
                )
                break

    def _queue_tiger_hurt(
        self,
        hurt_pet: PetInstance,
        hurt_player: PlayerState,
        other_player: PlayerState,
    ) -> None:
        if not self.should_queue_hurt(hurt_pet, hurt_player):
            return
        for tiger in list(self._living_team(hurt_player)):
            if (tiger.copied_ability or tiger.name) != "Tiger":
                continue
            if self._friend_ahead(hurt_player, tiger) is hurt_pet:
                self.enqueue_battle_chain(
                    BattleAbilityEvent(
                        "hurt", hurt_pet, hurt_player, other_player, tiger_level=tiger.level
                    )
                )
                break

    def _queue_tiger_faint(
        self,
        fainted_pet: PetInstance,
        fainted_idx: int,
        player: PlayerState,
        opponent: PlayerState,
    ) -> None:
        if not self._pet_has_faint_ability(fainted_pet):
            return
        for tiger in list(self._living_team(player)):
            if (tiger.copied_ability or tiger.name) != "Tiger":
                continue
            tiger_idx = next((i for i, p in enumerate(player.team) if p is tiger), -1)
            if tiger_idx >= 0 and fainted_idx > tiger_idx:
                has_living_between = any(
                    player.team[j] is not None and _is_alive(player.team[j])
                    for j in range(tiger_idx + 1, fainted_idx)
                )
                if not has_living_between:
                    self.enqueue_battle_chain(
                        BattleAbilityEvent(
                            "faint",
                            fainted_pet,
                            player,
                            opponent,
                            fainted_idx=fainted_idx,
                            tiger_level=tiger.level,
                        )
                    )
                    break

    def _queue_tiger_knock_out(
        self,
        attacker: PetInstance,
        attacker_player: PlayerState,
        defender_player: PlayerState,
    ) -> None:
        if not self.should_queue_knock_out(attacker):
            return
        for tiger in list(self._living_team(attacker_player)):
            if (tiger.copied_ability or tiger.name) != "Tiger":
                continue
            if self._friend_ahead(attacker_player, tiger) is attacker:
                self.enqueue_battle_chain(
                    BattleAbilityEvent(
                        "knock_out",
                        attacker,
                        attacker_player,
                        defender_player,
                        tiger_level=tiger.level,
                    )
                )
                break

    def _queue_tiger_after_attack(
        self,
        attacker: PetInstance,
        player: PlayerState,
        opponent: PlayerState,
    ) -> None:
        if self._ability_name(attacker) != "Elephant":
            return
        if self._friend_behind(player, attacker) is None:
            return
        for tiger in list(self._living_team(player)):
            if (tiger.copied_ability or tiger.name) != "Tiger":
                continue
            if self._friend_ahead(player, tiger) is attacker:
                self.enqueue_battle_chain(
                    BattleAbilityEvent(
                        "after_attack", attacker, player, opponent, tiger_level=tiger.level
                    )
                )
                break

    def _queue_tiger_friend_summoned(
        self,
        summoned_pet: PetInstance,
        player: PlayerState,
    ) -> None:
        if not self.should_queue_friend_summoned(summoned_pet, player):
            return
        for tiger in list(self._living_team(player)):
            if (tiger.copied_ability or tiger.name) != "Tiger":
                continue
            if self._friend_ahead(player, tiger) is summoned_pet:
                self.enqueue_battle_chain(
                    BattleAbilityEvent(
                        "friend_summoned",
                        summoned_pet,
                        player,
                        player,
                        summoned_pet=summoned_pet,
                        tiger_level=tiger.level,
                    )
                )
                break

    def _collect_friend_faint_reaction_events(
        self,
        fainted_pet: PetInstance,
        fainted_idx: int,
        player: PlayerState,
        opponent: PlayerState,
    ) -> list[BattleAbilityEvent]:
        batch: list[BattleAbilityEvent] = []
        for i, friend in enumerate(player.team):
            if friend is None or friend is fainted_pet or not _is_alive(friend):
                continue
            friend_ability = friend.copied_ability or friend.name
            reacts = False

            if fainted_idx > i:
                nearest_ahead_alive = next(
                    (
                        j
                        for j in range(i + 1, fainted_idx)
                        if player.team[j] is not None and _is_alive(player.team[j])
                    ),
                    None,
                )
                if nearest_ahead_alive is None and friend_ability == "Ox":
                    reacts = True

            if friend_ability in {"Shark", "Fly"}:
                reacts = True

            if reacts:
                batch.append(
                    BattleAbilityEvent(
                        "friend_faint",
                        friend,
                        player,
                        opponent,
                        fainted_pet=fainted_pet,
                        fainted_idx=fainted_idx,
                        friend_faint_target_idx=i,
                    )
                )
        return batch

    def _enqueue_wolverine_triggers(
        self,
        hurt_player: PlayerState,
        other_player: PlayerState,
    ) -> None:
        for wolverine in self._living_team(hurt_player):
            if self._ability_name(wolverine) == "Wolverine":
                self.enqueue_battle_chain(
                    BattleAbilityEvent(
                        "wolverine", wolverine, hurt_player, other_player,
                    )
                )

    def _enqueue_friend_faint_reactions(
        self,
        fainted_pet: PetInstance,
        fainted_idx: int,
        player: PlayerState,
        opponent: PlayerState,
    ) -> None:
        self.enqueue_battle_batch(
            self._collect_friend_faint_reaction_events(
                fainted_pet, fainted_idx, player, opponent,
            )
        )

    def collect_friend_faint_reaction_events(
        self,
        fainted_pet: PetInstance,
        fainted_idx: int,
        player: PlayerState,
        opponent: PlayerState,
    ) -> list[BattleAbilityEvent]:
        """Return friend-faint events for merging into a simultaneous faint batch."""
        return self._collect_friend_faint_reaction_events(
            fainted_pet, fainted_idx, player, opponent,
        )

    def _apply_friend_faint_reaction(
        self,
        friend: PetInstance,
        fainted_pet: PetInstance,
        fainted_idx: int,
        player: PlayerState,
        opponent: PlayerState,
        summon_callback: SummonCallback | None,
        *,
        friend_idx: int | None = None,
    ) -> None:
        i = friend_idx if friend_idx is not None else (
            player.team.index(friend) if friend in player.team else -1
        )
        friend_ability = friend.copied_ability or friend.name

        if fainted_idx > i:
            nearest_ahead_alive = next(
                (
                    j
                    for j in range(i + 1, fainted_idx)
                    if player.team[j] is not None and _is_alive(player.team[j])
                ),
                None,
            )
            if nearest_ahead_alive is None and friend_ability == "Ox":
                if friend.knock_out_count < friend.level:
                    friend.perk = "melon"
                    friend.perk_uses = 0
                    friend.attack = min(50, friend.attack + 1)
                    friend.knock_out_count += 1

        if friend_ability == "Shark":
            gain = 2 * friend.level
            friend.attack = min(50, friend.attack + gain)
            friend.health = min(50, friend.health + gain)

        elif friend_ability == "Fly":
            if friend.ability_uses < 3 and fainted_pet.name != "Zombie Fly":
                fly_stats = 4 * friend.level
                self._summon_at(
                    player,
                    fainted_idx,
                    "Zombie Fly",
                    fly_stats,
                    fly_stats,
                    friend.level,
                    summon_callback,
                )
                friend.ability_uses += 1

    def flush_battle_hurts(self) -> None:
        """Move pending Hurt triggers into the battle FIFO queue."""
        if self._battle_mode:
            self._battle_queue.flush_hurts_to_queue()

    def enqueue_hurt(
        self,
        hurt_pet: PetInstance,
        hurt_player: PlayerState,
        other_player: PlayerState,
    ) -> None:
        """Queue a Hurt trigger (wiki §9 FIFO ordering)."""
        if self._battle_mode:
            hurt_player.hurt_count_this_battle += 1
            triggers_wolverine = hurt_player.hurt_count_this_battle % 4 == 0
            if self.should_queue_hurt(hurt_pet, hurt_player):
                self._battle_queue.note_hurt(
                    hurt_pet, hurt_player, other_player,
                    triggers_wolverine=triggers_wolverine,
                )
            elif triggers_wolverine:
                self._enqueue_wolverine_triggers(hurt_player, other_player)
            return
        self._hurt_pending.append(_QueuedHurt(hurt_pet, hurt_player, other_player))

    def flush_hurt_queue(self, summon_callback: SummonCallback | None = None) -> None:
        """Resolve queued Hurt triggers in descending attack order (FIFO per batch)."""
        if self._battle_mode:
            return
        while self._hurt_pending:
            batch = self._hurt_pending
            self._hurt_pending = []
            batch.sort(key=lambda entry: (-entry.pet.effective_attack, self.rng.random()))
            for entry in batch:
                if entry.pet not in entry.player.team:
                    continue
                self.apply_hurt(
                    entry.pet,
                    entry.player,
                    entry.other,
                    summon_callback,
                )

    @staticmethod
    def _reduce_health_min_one(pet: PetInstance, amount: int) -> None:
        """Skunk/Wolverine health removal: not Hurt damage, cannot drop below 1 HP."""
        remaining = amount
        if pet.temporary_health > 0:
            if remaining <= pet.temporary_health:
                pet.temporary_health -= remaining
                return
            remaining -= pet.temporary_health
            pet.temporary_health = 0
        pet.health = max(1, pet.health - remaining)

    def _notify_ability(self, pet: PetInstance | None, player: PlayerState) -> None:
        if pet is not None and self.ability_listener is not None:
            self.ability_listener(pet, player)

    # ------------------------------------------------------------------
    # Shop-phase triggers
    # ------------------------------------------------------------------

    def apply_start_of_turn(self, player: PlayerState) -> None:
        """Fire all Start-of-Turn abilities."""
        # Reset per-turn counters
        player.rabbit_count_this_turn = 0
        player.food_cost_discount = 0
        player.dragon_buys_this_turn = 0
        # Cat: each Cat gives 2 food-multiplier uses per turn
        cat_count = sum(
            1 for p in player.team
            if p is not None and (p.copied_ability or p.name) == "Cat"
        )
        player.cat_food_uses_this_turn = 2 * cat_count

        for pet in self._living_team(player):
            ability = pet.copied_ability or pet.name

            if ability == "Swan":
                player.gold = min(player.gold + pet.level, 999)
                self._notify_ability(pet, player)

            elif ability == "Worm":
                apple_name = ["Apple", "Better Apple", "Best Apple"][pet.level - 1]
                self._insert_shop_food_right(
                    player, name=apple_name, tier=1, cost_override=2,
                )
                self._notify_ability(pet, player)

            elif ability == "Giraffe":
                ahead = self._friends_ahead(player, pet)
                for friend in ahead[: pet.level]:
                    friend.attack = min(50, friend.attack + 1)
                    friend.health = min(50, friend.health + 1)
                if ahead[: pet.level]:
                    self._notify_ability(pet, player)

            elif ability == "Squirrel":
                player.food_cost_discount = pet.level
                self._notify_ability(pet, player)

            elif ability == "Penguin":
                eligible = [p for p in self._living_team(player) if p is not pet and p.level >= 2]
                if eligible:
                    chosen = self.rng.sample(eligible, min(2, len(eligible)))
                    for friend in chosen:
                        friend.attack = min(50, friend.attack + pet.level)
                        friend.health = min(50, friend.health + pet.level)
                    self._notify_ability(pet, player)

    def apply_end_turn(self, player: PlayerState) -> None:
        """Fire all End-Turn abilities."""
        for pet in self._living_team(player):
            ability = pet.copied_ability or pet.name

            if ability == "Snail":
                if player.last_battle_result == BattleOutcome.LOSS:
                    ahead = self._friends_ahead(player, pet)
                    for friend in ahead[:3]:
                        friend.attack = min(50, friend.attack + pet.level)
                    if ahead[:3]:
                        self._notify_ability(pet, player)

            elif ability == "Bison":
                has_level3_friend = any(
                    p for p in self._living_team(player) if p is not pet and p.level == 3
                )
                if has_level3_friend:
                    pet.attack = min(50, pet.attack + pet.level)
                    pet.health = min(50, pet.health + pet.level * 2)
                    self._notify_ability(pet, player)

            elif ability == "Monkey":
                front = self._friend_at_front(player, exclude=pet)
                if front is not None:
                    front.attack = min(50, front.attack + pet.level * 2)
                    front.health = min(50, front.health + pet.level * 2)
                    self._notify_ability(pet, player)

            # Parrot always refreshes its copied ability regardless of what it's currently copying
            if pet.name == "Parrot":
                target = self._friend_ahead(player, pet)
                if target is not None:
                    pet.copied_ability = target.name
                else:
                    pet.copied_ability = None
                self._notify_ability(pet, player)

        # Bread perk: give +7 health until next battle
        for pet in self._living_team(player):
            if pet.perk == "bread":
                pet.temporary_health += 7

        # Cake perk: accumulate sell-value bonus each turn held
        for pet in self._living_team(player):
            if pet.perk == "cake":
                pet.perk_uses += 1

    def apply_buy(self, player: PlayerState, bought_pet: PetInstance) -> None:
        """Fire Buy trigger for bought_pet, then check Dragon."""
        ability = bought_pet.copied_ability or bought_pet.name

        if ability == "Otter":
            self._buff_random_friends(player, amount=bought_pet.level, attack=0, health=1, exclude=bought_pet)
            self._notify_ability(bought_pet, player)

        elif ability == "Cow":
            for i, slot in enumerate(player.shop.slots):
                if slot is not None and slot.kind == "food":
                    player.shop.slots[i] = None
            milk_name = ["Milk", "Better Milk", "Best Milk"][bought_pet.level - 1]
            for _ in range(2):
                self._insert_shop_food_right(player, name=milk_name, tier=5, cost_override=0)
            self._notify_ability(bought_pet, player)

        # Dragon: fires when ANY tier-1 pet is bought (including Dragon itself if tier 1,
        # but Dragon is tier 6 so in practice only fires for tier-1 friends)
        if bought_pet.tier == 1:
            for dragon in self._living_team(player):
                if (dragon.copied_ability or dragon.name) == "Dragon":
                    if player.dragon_buys_this_turn < 4:
                        player.dragon_buys_this_turn += 1
                        for friend in self._living_team(player):
                            if friend is not dragon:
                                friend.attack = min(50, friend.attack + dragon.level)
                                friend.health = min(50, friend.health + dragon.level)
                        self._notify_ability(dragon, player)

    def apply_fish_level_up(self, player: PlayerState, fish: PetInstance) -> None:
        """Fire Fish level-up: give 2 random friends +level/+level.
        Only fires when the levelling pet is Fish (or a Parrot copying Fish).
        """
        ability = fish.copied_ability or fish.name
        if ability != "Fish":
            return
        bonus = fish.level
        self._buff_random_friends(player, amount=2, attack=bonus, health=bonus, exclude=fish)
        self._notify_ability(fish, player)

    def apply_sell(self, player: PlayerState, sold_pet: PetInstance) -> None:
        """Fire Sell trigger."""
        ability = sold_pet.copied_ability or sold_pet.name

        if ability == "Pig":
            player.gold = min(player.gold + sold_pet.level, 999)
            self._notify_ability(sold_pet, player)

        elif ability == "Beaver":
            self._buff_random_friends(player, amount=2, attack=sold_pet.level, health=0)
            self._notify_ability(sold_pet, player)

        elif ability == "Duck":
            for offer in player.shop.slots:
                if offer is not None and offer.kind == "pet":
                    offer.bonus_health += sold_pet.level
            self._notify_ability(sold_pet, player)

        elif ability == "Pigeon":
            for _ in range(sold_pet.level):
                self._insert_shop_food_right(player, name="Bread Crumbs", tier=1, cost_override=0)
            self._notify_ability(sold_pet, player)

    def apply_eats_food(self, player: PlayerState, eating_pet: PetInstance) -> None:
        """Fire Eats-Food-related triggers (Rabbit reacts; Seal fires when it eats)."""
        # Rabbit: when any friendly eats food (including Rabbit itself), give +level health
        # Works 3 times per turn
        for pet in self._living_team(player):
            ability = pet.copied_ability or pet.name
            if ability == "Rabbit":
                if player.rabbit_count_this_turn < 3:
                    eating_pet.health = min(50, eating_pet.health + pet.level)
                    player.rabbit_count_this_turn += 1
                    self._notify_ability(pet, player)

        # Seal: when it eats food, give 3 random friends +level attack
        ability = eating_pet.copied_ability or eating_pet.name
        if ability == "Seal":
            self._buff_random_friends(player, amount=3, attack=eating_pet.level, health=0, exclude=eating_pet)
            self._notify_ability(eating_pet, player)

    # ------------------------------------------------------------------
    # Battle-phase triggers
    # ------------------------------------------------------------------

    def apply_start_of_battle_pet(
        self,
        pet: PetInstance,
        player: PlayerState,
        opponent: PlayerState,
        summon_callback: SummonCallback | None = None,
        *,
        _tiger_level: int | None = None,
    ) -> None:
        """Fire Start-of-Battle ability for ONE specific pet."""
        if not _is_alive(pet):
            return
        ability = pet.copied_ability or pet.name
        level = _tiger_level if _tiger_level is not None else pet.level

        if ability == "Mosquito":
            for _ in range(level):
                target = self._random_living_pet(opponent)
                if target is None:
                    break
                self._deal_damage_battle(target, 1, opponent, player,
                                         is_hurt=True, summon_callback=summon_callback)

        elif ability == "Dodo":
            target = self._friend_ahead(player, pet)
            if target is not None:
                # Dodo buff is always rounded down (wiki §9).
                bonus = max(1, math.floor(pet.effective_attack * 50 * level / 100))
                target.attack = min(50, target.attack + bonus)

        elif ability == "Dolphin":
            for _ in range(level):
                target = self._lowest_health_pet(opponent)
                if target is None:
                    break
                self._deal_damage_battle(target, 4, opponent, player,
                                         is_hurt=True, summon_callback=summon_callback)

        elif ability == "Crab":
            healthiest = max(
                (p for p in self._living_team(player) if p is not pet),
                key=lambda p: p.health + p.temporary_health,
                default=None,
            )
            if healthiest is not None:
                pct = 25 * level
                bonus = max(1, math.ceil((healthiest.health + healthiest.temporary_health) * pct / 100))
                pet.health = min(50, pet.health + bonus)

        elif ability == "Skunk":
            target = self._highest_health_pet(opponent)
            if target is not None:
                pct = 33 * level
                effective = target.health + target.temporary_health
                # Skunk health removal is rounded down; not Hurt damage; cannot kill (min 1 HP).
                reduction = math.floor(effective * pct / 100)
                self._reduce_health_min_one(target, reduction)

        elif ability == "Armadillo":
            bonus = 8 * level
            for p in self._living_team(player) + self._living_team(opponent):
                p.health = min(50, p.health + bonus)

        elif ability == "Crocodile":
            for _ in range(level):
                target = self._backmost_alive(opponent)
                if target is None:
                    break
                self._deal_damage_battle(target, 8, opponent, player,
                                         is_hurt=True, summon_callback=summon_callback)

        elif ability == "Whale":
            swallowee = self._friend_ahead(player, pet)
            if swallowee is not None:
                idx = next((i for i, p in enumerate(player.team) if p is swallowee), None)
                if idx is not None:
                    player.team[idx] = None
                    pet.copied_ability = (
                        f"whale_swallowed:{swallowee.name}"
                        f":{swallowee.attack}:{swallowee.health}:{swallowee.level}"
                    )

        elif ability == "Leopard":
            # Leopard damage is rounded down (wiki §9).
            dmg = math.floor(pet.effective_attack * 50 / 100)
            targets_hit: set[int] = set()
            for _ in range(level):
                candidates = [p for p in self._living_team(opponent) if id(p) not in targets_hit]
                if not candidates:
                    break
                target = self.rng.choice(candidates)
                targets_hit.add(id(target))
                if dmg > 0:
                    self._deal_damage_battle(target, dmg, opponent, player,
                                             is_hurt=True, summon_callback=summon_callback)

        sob_abilities = {
            "Mosquito", "Dodo", "Dolphin", "Crab", "Skunk", "Armadillo", "Crocodile", "Whale", "Leopard",
        }
        if ability in sob_abilities:
            self._notify_ability(pet, player)

        # Tiger repeat for SOB
        if _tiger_level is None:
            if self._battle_mode:
                self._queue_tiger_sob(pet, player, opponent)
            else:
                self._tiger_repeat_sob(pet, player, opponent, summon_callback)

        if not self._battle_mode:
            self.flush_hurt_queue(summon_callback)

    def _tiger_repeat_sob(
        self,
        pet: PetInstance,
        player: PlayerState,
        opponent: PlayerState,
        summon_callback: SummonCallback | None,
    ) -> None:
        for tiger in list(self._living_team(player)):
            if (tiger.copied_ability or tiger.name) != "Tiger":
                continue
            if self._friend_ahead(player, tiger) is pet:
                self.apply_start_of_battle_pet(pet, player, opponent, summon_callback,
                                               _tiger_level=tiger.level)
                break

    # Legacy full-team SOB (for backwards compat / tests that call it directly)
    def apply_start_of_battle(
        self,
        player: PlayerState,
        opponent: PlayerState,
        summon_callback: SummonCallback | None = None,
    ) -> None:
        for pet in sorted(self._living_team(player), key=lambda p: -p.effective_attack):
            self.apply_start_of_battle_pet(pet, player, opponent, summon_callback)

    def apply_before_attack(
        self,
        attacker: PetInstance,
        player: PlayerState,
        opponent: PlayerState,
        *,
        _tiger_level: int | None = None,
    ) -> None:
        """Before Attack trigger — fires just before the attacker's damage connects."""
        if not _is_alive(attacker):
            return
        ability = attacker.copied_ability or attacker.name
        level = _tiger_level if _tiger_level is not None else attacker.level

        if ability == "Boar":
            # Gains are temporary (not retained outside battle per wiki)
            attacker.temporary_attack = min(50 - attacker.attack, attacker.temporary_attack + 4 * level)
            attacker.temporary_health = min(50 - attacker.health, attacker.temporary_health + 2 * level)
            self._notify_ability(attacker, player)

        # Tiger repeat
        if _tiger_level is None:
            if self._battle_mode:
                self._queue_tiger_before_attack(attacker, player, opponent)
            else:
                for tiger in list(self._living_team(player)):
                    if (tiger.copied_ability or tiger.name) != "Tiger":
                        continue
                    if self._friend_ahead(player, tiger) is attacker:
                        self.apply_before_attack(attacker, player, opponent, _tiger_level=tiger.level)
                        break

    def apply_faint(
        self,
        fainted_pet: PetInstance,
        fainted_idx: int,
        player: PlayerState,
        opponent: PlayerState,
        summon_callback: SummonCallback | None = None,
        *,
        _tiger_level: int | None = None,
    ) -> None:
        """Fire Faint trigger for fainted_pet and (when _tiger_level is None) notify friends."""
        ability = fainted_pet.copied_ability or fainted_pet.name
        level = _tiger_level if _tiger_level is not None else fainted_pet.level

        # --- Faint ability of the fainted pet itself ---
        if ability == "Ant":
            target = self._random_living_pet(player)
            if target is not None:
                target.attack = min(50, target.attack + level)
                target.health = min(50, target.health + level)

        elif ability == "Cricket":
            stats = {1: (1, 1), 2: (2, 2), 3: (3, 3)}[level]
            self._summon_at(player, fainted_idx, "Zombie Cricket", stats[0], stats[1],
                            level, summon_callback)

        elif ability == "Rat":
            for _ in range(level):
                self._summon_at_front(opponent, "Dirty Rat", 1, 1, 1, summon_callback)

        elif ability == "Hedgehog":
            dmg = 2 * level
            for p_team, p_opp in [(player, opponent), (opponent, player)]:
                for p in list(self._living_team(p_team)):
                    if p is not fainted_pet:
                        self._deal_damage_battle(p, dmg, p_team, p_opp,
                                                 is_hurt=True, summon_callback=summon_callback)

        elif ability == "Flamingo":
            behind = self._friends_behind(player, fainted_pet)
            for friend in behind[:2]:
                friend.attack = min(50, friend.attack + level)
                friend.health = min(50, friend.health + level)

        elif ability == "Spider":
            tier3_names = list(PETS_BY_TIER.get(3, ()))
            if tier3_names:
                chosen_name = self.rng.choice(tier3_names)
                if chosen_name in self.registry.pets:
                    atk, hp = {1: (2, 2), 2: (4, 4), 3: (6, 6)}[level]
                    self._summon_at(player, fainted_idx, chosen_name, atk, hp, level, summon_callback)

        elif ability == "Sheep":
            atk, hp = RAM_STATS[min(level, 3)]
            self._summon_at(player, fainted_idx, "Ram", atk, hp, level, summon_callback)
            self._summon_at(player, fainted_idx, "Ram", atk, hp, level, summon_callback)

        elif ability == "Deer":
            atk, hp = BUS_STATS[min(level, 3)]
            bus = self._summon_at(player, fainted_idx, "Bus", atk, hp, level, summon_callback)
            if bus is not None:
                bus.perk = "chili"

        elif ability == "Turtle":
            behind = self._friends_behind(player, fainted_pet)
            for friend in behind[: level]:
                friend.perk = "melon"
                friend.perk_uses = 0

        # Whale faint: release the swallowed pet
        # Use pet.name here because copied_ability was overwritten with the swallowed-info string
        if fainted_pet.name == "Whale":
            swallowed = fainted_pet.copied_ability or ""
            if swallowed.startswith("whale_swallowed:"):
                parts = swallowed.split(":")
                name_part = parts[1]
                try:
                    atk_s, hp_s = int(parts[2]), int(parts[3])
                except (IndexError, ValueError):
                    atk_s, hp_s = 1, 1
                self._summon_at(player, fainted_idx, name_part, atk_s, hp_s,
                                level, summon_callback)

        elif ability == "Rooster":
            for _ in range(level):
                chick_hp = max(1, math.ceil(fainted_pet.health / 2))
                self._summon_at(player, fainted_idx, "Rooster Chick", 1, chick_hp, 1, summon_callback)

        elif ability == "Mammoth":
            for friend in self._living_team(player):
                friend.attack = min(50, friend.attack + level * 2)
                friend.health = min(50, friend.health + level * 2)

        elif ability == "Badger":
            dmg = math.ceil(fainted_pet.effective_attack * 50 * level / 100)
            # Pet immediately behind (lower index)
            behind_idx = fainted_idx - 1
            while behind_idx >= 0 and player.team[behind_idx] is None:
                behind_idx -= 1
            if behind_idx >= 0 and player.team[behind_idx] is not None:
                behind_pet = player.team[behind_idx]
                if _is_alive(behind_pet):
                    self._deal_damage_battle(behind_pet, dmg, player, opponent,
                                             is_hurt=True, summon_callback=summon_callback)
            # Pet immediately ahead (higher index), or enemy attacker if none
            ahead_idx = fainted_idx + 1
            while ahead_idx < len(player.team) and player.team[ahead_idx] is None:
                ahead_idx += 1
            if ahead_idx < len(player.team) and player.team[ahead_idx] is not None:
                ahead_pet = player.team[ahead_idx]
                if _is_alive(ahead_pet):
                    self._deal_damage_battle(ahead_pet, dmg, player, opponent,
                                             is_hurt=True, summon_callback=summon_callback)
            else:
                enemy_attacker = self._last_alive(opponent)
                if enemy_attacker is not None:
                    self._deal_damage_battle(enemy_attacker, dmg, opponent, player,
                                             is_hurt=True, summon_callback=summon_callback)

        # Tiger repeat for Faint ability (only ability, not perks/notifications)
        if _tiger_level is None:
            if self._battle_mode:
                self._queue_tiger_faint(fainted_pet, fainted_idx, player, opponent)
            else:
                self._tiger_repeat_faint(fainted_pet, fainted_idx, player, opponent, summon_callback)

        # Skip perks and friend notifications when called from Tiger repeat
        if _tiger_level is not None:
            return

        # --- Honey perk: summon 1/1 Bee ---
        if fainted_pet.perk == "honey":
            self._summon_at(player, fainted_idx, "Bee", 1, 1, 1, summon_callback)

        # --- Mushroom perk: come back as 1/1 ---
        elif fainted_pet.perk == "mushroom":
            revived = self._summon_at(player, fainted_idx, fainted_pet.name, 1, 1,
                                      fainted_pet.level, summon_callback)
            if revived is not None:
                revived.perk = None
                revived.ability_uses = fainted_pet.ability_uses

        # --- Notify surviving friends ---
        if not self._battle_mode:
            for i, friend in enumerate(player.team):
                if friend is None or friend is fainted_pet or not _is_alive(friend):
                    continue
                friend_ability = friend.copied_ability or friend.name

                # Friend Ahead Faints
                if fainted_idx > i:
                    nearest_ahead_alive = next(
                        (j for j in range(i + 1, fainted_idx)
                         if player.team[j] is not None and _is_alive(player.team[j])),
                        None,
                    )
                    if nearest_ahead_alive is None:
                        if friend_ability == "Ox":
                            if friend.knock_out_count < friend.level:
                                friend.perk = "melon"
                                friend.perk_uses = 0
                                friend.attack = min(50, friend.attack + 1)
                                friend.knock_out_count += 1

                # Friend Faints
                if friend_ability == "Shark":
                    gain = 2 * friend.level
                    friend.attack = min(50, friend.attack + gain)
                    friend.health = min(50, friend.health + gain)

                elif friend_ability == "Fly":
                    if friend.ability_uses < 3 and fainted_pet.name != "Zombie Fly":
                        fly_stats = 4 * friend.level
                        self._summon_at(player, fainted_idx, "Zombie Fly", fly_stats, fly_stats,
                                        friend.level, summon_callback)
                        friend.ability_uses += 1

        if not self._battle_mode:
            self.flush_hurt_queue(summon_callback)

    def _tiger_repeat_faint(
        self,
        fainted_pet: PetInstance,
        fainted_idx: int,
        player: PlayerState,
        opponent: PlayerState,
        summon_callback: SummonCallback | None,
    ) -> None:
        for tiger in list(self._living_team(player)):
            if (tiger.copied_ability or tiger.name) != "Tiger":
                continue
            # Tiger repeats the faint ability of its nearest friend ahead
            # At time of faint, fainted_pet is already removed, so check via idx
            tiger_idx = next((i for i, p in enumerate(player.team) if p is tiger), -1)
            if tiger_idx >= 0 and fainted_idx > tiger_idx:
                # Check that no living pet exists between tiger_idx and fainted_idx
                has_living_between = any(
                    player.team[j] is not None and _is_alive(player.team[j])
                    for j in range(tiger_idx + 1, fainted_idx)
                )
                if not has_living_between:
                    self.apply_faint(fainted_pet, fainted_idx, player, opponent,
                                     summon_callback, _tiger_level=tiger.level)
                    break

    def apply_hurt(
        self,
        hurt_pet: PetInstance,
        hurt_player: PlayerState,
        other_player: PlayerState,
        summon_callback: SummonCallback | None = None,
        *,
        _tiger_level: int | None = None,
        _triggers_wolverine: bool = False,
    ) -> None:
        """Fire Hurt trigger after this pet took damage (including lethal damage).

        Queued via FIFO before faint removal; the pet may already be at 0 HP but
        is still on the team when its Hurt ability resolves.
        """
        ability = hurt_pet.copied_ability or hurt_pet.name
        level = _tiger_level if _tiger_level is not None else hurt_pet.level

        if ability == "Peacock":
            hurt_pet.attack = min(50, hurt_pet.attack + 3 * level)

        elif ability == "Camel":
            behind = self._friend_behind(hurt_player, hurt_pet)
            if behind is not None:
                behind.attack = min(50, behind.attack + level)
                behind.health = min(50, behind.health + level * 2)

        elif ability == "Blowfish":
            target = self._random_living_pet(other_player)
            if target is not None:
                self._deal_damage_battle(target, 3 * level, other_player, hurt_player,
                                         is_hurt=True, summon_callback=summon_callback)

        elif ability == "Gorilla":
            max_uses = _tiger_level if _tiger_level is not None else hurt_pet.level
            if hurt_pet.ability_uses < max_uses:
                hurt_pet.perk = "coconut"
                hurt_pet.perk_uses = 0
                hurt_pet.ability_uses += 1

        # Only count hurt events and check Wolverine once (not per Tiger repeat)
        if _tiger_level is None and not self._battle_mode:
            hurt_player.hurt_count_this_battle += 1
            if hurt_player.hurt_count_this_battle % 4 == 0:
                for wolverine in self._living_team(hurt_player):
                    if (wolverine.copied_ability or wolverine.name) == "Wolverine":
                        removal = 3 * wolverine.level
                        for enemy in self._living_team(other_player):
                            # Not Hurt damage; cannot reduce below 1 HP.
                            self._reduce_health_min_one(enemy, removal)

            # Tiger repeat
            for tiger in list(self._living_team(hurt_player)):
                if (tiger.copied_ability or tiger.name) != "Tiger":
                    continue
                if self._friend_ahead(hurt_player, tiger) is hurt_pet:
                    self.apply_hurt(hurt_pet, hurt_player, other_player, summon_callback,
                                    _tiger_level=tiger.level)
                    break
        elif _tiger_level is None and self._battle_mode:
            self._queue_tiger_hurt(hurt_pet, hurt_player, other_player)
            if _triggers_wolverine:
                self._enqueue_wolverine_triggers(hurt_player, other_player)

    def apply_knock_out(
        self,
        attacker: PetInstance,
        attacker_player: PlayerState,
        defender_player: PlayerState,
        summon_callback: SummonCallback | None = None,
        *,
        _tiger_level: int | None = None,
    ) -> None:
        """Fire Knock-Out trigger for the attacker after it causes a faint."""
        ability = attacker.copied_ability or attacker.name
        level = _tiger_level if _tiger_level is not None else attacker.level

        if ability == "Hippo":
            if attacker.knock_out_count < 3:
                attacker.attack = min(50, attacker.attack + 3 * level)
                attacker.health = min(50, attacker.health + 3 * level)
                if _tiger_level is None:
                    attacker.knock_out_count += 1

        elif ability == "Rhino":
            target = self._last_alive(defender_player)
            if target is not None:
                dmg = 4 * level
                if target.tier == 1:
                    dmg *= 2
                self._deal_damage_battle(target, dmg, defender_player, attacker_player,
                                         is_hurt=True,
                                         attacker_pet=attacker,
                                         attacker_player=attacker_player,
                                         summon_callback=summon_callback)

        # Tiger repeat
        if _tiger_level is None:
            if self._battle_mode:
                self._queue_tiger_knock_out(attacker, attacker_player, defender_player)
            else:
                for tiger in list(self._living_team(attacker_player)):
                    if (tiger.copied_ability or tiger.name) != "Tiger":
                        continue
                    if self._friend_ahead(attacker_player, tiger) is attacker:
                        self.apply_knock_out(attacker, attacker_player, defender_player,
                                             summon_callback, _tiger_level=tiger.level)
                        break

        if not self._battle_mode:
            self.flush_hurt_queue(summon_callback)

    def apply_friend_summoned(
        self,
        summoned_pet: PetInstance,
        player: PlayerState,
        summon_callback: SummonCallback | None = None,
        *,
        _tiger_level: int | None = None,
    ) -> None:
        """Fire Friend Summoned trigger for all OTHER pets on the team."""
        # Scorpion gets Peanut perk when summoned
        if (summoned_pet.copied_ability or summoned_pet.name) == "Scorpion":
            summoned_pet.perk = "peanut"

        for pet in list(self._living_team(player)):
            if pet is summoned_pet:
                continue
            ability = pet.copied_ability or pet.name
            level = _tiger_level if _tiger_level is not None else pet.level

            if ability == "Horse":
                summoned_pet.temporary_attack = min(
                    50 - summoned_pet.attack,
                    summoned_pet.temporary_attack + level,
                )
                self._notify_ability(pet, player)

            elif ability == "Turkey":
                summoned_pet.attack = min(50, summoned_pet.attack + 3 * level)
                summoned_pet.health = min(50, summoned_pet.health + level)
                self._notify_ability(pet, player)

            elif ability == "Dog":
                pet.temporary_attack = min(50 - pet.attack, pet.temporary_attack + 2 * level)
                pet.temporary_health = min(50 - pet.health, pet.temporary_health + level)
                self._notify_ability(pet, player)

        # Tiger repeat (Tiger causes its friend ahead's Friend Summoned to repeat)
        if _tiger_level is None:
            if self._battle_mode:
                self._queue_tiger_friend_summoned(summoned_pet, player)
            else:
                for tiger in list(self._living_team(player)):
                    if (tiger.copied_ability or tiger.name) != "Tiger":
                        continue
                    if self._friend_ahead(player, tiger) is summoned_pet:
                        self.apply_friend_summoned(summoned_pet, player, summon_callback,
                                                   _tiger_level=tiger.level)
                        break

    def apply_after_attack(
        self,
        attacker: PetInstance,
        player: PlayerState,
        opponent: PlayerState,
        summon_callback: SummonCallback | None = None,
        *,
        _tiger_level: int | None = None,
    ) -> None:
        """Fire After-Attack trigger for attacker; also handles Kangaroo and Snake."""
        ability = attacker.copied_ability or attacker.name
        level = _tiger_level if _tiger_level is not None else attacker.level

        if ability == "Elephant":
            for _ in range(level):
                behind = self._friend_behind(player, attacker)
                if behind is not None:
                    self._deal_damage_battle(behind, 1, player, opponent,
                                             is_hurt=True, summon_callback=summon_callback)

        # Kangaroo gains stats when its nearest friend ahead just attacked
        for kang in list(self._living_team(player)):
            if kang is attacker:
                continue
            if (kang.copied_ability or kang.name) == "Kangaroo":
                if self._friend_ahead(player, kang) is attacker:
                    kang_level = _tiger_level if _tiger_level is not None else kang.level
                    kang.attack = min(50, kang.attack + kang_level)
                    kang.health = min(50, kang.health + kang_level)
                    # Tiger repeat: if Tiger has kang as its nearest friend ahead
                    if _tiger_level is None:
                        for tiger in self._living_team(player):
                            if tiger is kang or tiger is attacker:
                                continue
                            if (tiger.copied_ability or tiger.name) == "Tiger":
                                if self._friend_ahead(player, tiger) is kang:
                                    kang.attack = min(50, kang.attack + tiger.level)
                                    kang.health = min(50, kang.health + tiger.level)
                                    break

        # Snake fires when its nearest friend ahead attacks (5 times/battle)
        for snake in list(self._living_team(player)):
            if snake is attacker:
                continue
            if (snake.copied_ability or snake.name) == "Snake":
                if self._friend_ahead(player, snake) is attacker:
                    snake_level = _tiger_level if _tiger_level is not None else snake.level
                    if snake.ability_uses < 5:
                        target = self._random_living_pet(opponent)
                        if target is not None:
                            self._deal_damage_battle(target, 5 * snake_level, opponent, player,
                                                     is_hurt=True, summon_callback=summon_callback)
                        if _tiger_level is None:
                            snake.ability_uses += 1
                    # Tiger repeat for Snake
                    if _tiger_level is None:
                        for tiger in self._living_team(player):
                            if tiger is snake or tiger is attacker:
                                continue
                            if (tiger.copied_ability or tiger.name) == "Tiger":
                                if self._friend_ahead(player, tiger) is snake:
                                    if snake.ability_uses < 5:
                                        tgt = self._random_living_pet(opponent)
                                        if tgt is not None:
                                            self._deal_damage_battle(tgt, 5 * tiger.level,
                                                                     opponent, player,
                                                                     is_hurt=True,
                                                                     summon_callback=summon_callback)
                                    break

        # Tiger repeat for the attacker's own after-attack ability (e.g. Elephant)
        if _tiger_level is None:
            if self._battle_mode:
                self._queue_tiger_after_attack(attacker, player, opponent)
            else:
                for tiger in list(self._living_team(player)):
                    if (tiger.copied_ability or tiger.name) != "Tiger":
                        continue
                    if self._friend_ahead(player, tiger) is attacker:
                        self.apply_after_attack(attacker, player, opponent, summon_callback,
                                                _tiger_level=tiger.level)
                        break

        if not self._battle_mode:
            self.flush_hurt_queue(summon_callback)

    # ------------------------------------------------------------------
    # Damage helper used by the battle engine
    # ------------------------------------------------------------------

    def _deal_damage_battle(
        self,
        target: PetInstance,
        amount: int,
        target_player: PlayerState,
        other_player: PlayerState,
        *,
        is_hurt: bool = True,
        attacker_pet: PetInstance | None = None,
        attacker_player: PlayerState | None = None,
        summon_callback: SummonCallback | None = None,
    ) -> int:
        """Apply amount damage to target, handling Melon/Garlic/Coconut perks.
        Returns actual damage dealt.
        """
        actual = amount

        if target.perk == "melon" and target.perk_uses == 0:
            actual = max(0, actual - 20)
            target.perk_uses = 1
            if actual == 0:
                return 0

        elif target.perk == "garlic":
            actual = max(2, actual - 2)

        elif target.perk == "coconut" and target.perk_uses == 0:
            target.perk_uses = 1
            return 0

        # Drain temporary HP first, then base health
        if target.temporary_health > 0:
            if actual <= target.temporary_health:
                target.temporary_health -= actual
                actual_base = 0
            else:
                actual_base = actual - target.temporary_health
                target.temporary_health = 0
                target.health -= actual_base
        else:
            target.health -= actual

        if is_hurt and actual > 0:
            self.enqueue_hurt(target, target_player, other_player)

        return actual

    # ------------------------------------------------------------------
    # Cat food multiplier
    # ------------------------------------------------------------------

    def cat_food_multiplier(self, player: PlayerState) -> int:
        """Return the current Cat food multiplier for stat-giving foods.
        Returns 1 if no Cat is present or uses are exhausted.
        """
        if player.cat_food_uses_this_turn <= 0:
            return 1
        cats = [p for p in player.team if p is not None and (p.copied_ability or p.name) == "Cat"]
        if not cats:
            return 1
        # Each Cat at level L adds L to the multiplier (1 base + sum of levels)
        return 1 + sum(c.level for c in cats)

    def consume_cat_use(self, player: PlayerState) -> None:
        """Consume one Cat food multiplier use."""
        if player.cat_food_uses_this_turn > 0:
            player.cat_food_uses_this_turn -= 1

    # ------------------------------------------------------------------
    # Team helpers
    # ------------------------------------------------------------------

    def _living_team(self, player: PlayerState) -> list[PetInstance]:
        return [pet for pet in player.team if pet is not None and _is_alive(pet)]

    def _friend_indexes_ahead(self, player: PlayerState, pet: PetInstance) -> list[int]:
        try:
            index = player.team.index(pet)
        except ValueError:
            return []
        return list(range(index + 1, len(player.team)))

    def _friend_indexes_behind(self, player: PlayerState, pet: PetInstance) -> list[int]:
        try:
            index = player.team.index(pet)
        except ValueError:
            return []
        return list(range(index - 1, -1, -1))

    def _friends_ahead(self, player: PlayerState, pet: PetInstance) -> list[PetInstance]:
        result = []
        for idx in self._friend_indexes_ahead(player, pet):
            slot = player.team[idx]
            if slot is not None and _is_alive(slot):
                result.append(slot)
        return result

    def _friends_behind(self, player: PlayerState, pet: PetInstance) -> list[PetInstance]:
        result = []
        for idx in self._friend_indexes_behind(player, pet):
            slot = player.team[idx]
            if slot is not None and _is_alive(slot):
                result.append(slot)
        return result

    def _friend_ahead(self, player: PlayerState, pet: PetInstance) -> PetInstance | None:
        ahead = self._friends_ahead(player, pet)
        return ahead[0] if ahead else None

    def _friend_behind(self, player: PlayerState, pet: PetInstance) -> PetInstance | None:
        behind = self._friends_behind(player, pet)
        return behind[0] if behind else None

    def _last_alive(self, player: PlayerState) -> PetInstance | None:
        for i in range(len(player.team) - 1, -1, -1):
            pet = player.team[i]
            if pet is not None and _is_alive(pet):
                return pet
        return None

    def _backmost_alive(self, player: PlayerState) -> PetInstance | None:
        for i in range(len(player.team)):
            pet = player.team[i]
            if pet is not None and _is_alive(pet):
                return pet
        return None

    def _friend_at_front(self, player: PlayerState, exclude: PetInstance | None = None) -> PetInstance | None:
        for i in range(len(player.team) - 1, -1, -1):
            pet = player.team[i]
            if pet is not None and _is_alive(pet) and pet is not exclude:
                return pet
        return None

    def _buff_random_friends(
        self,
        player: PlayerState,
        amount: int,
        attack: int,
        health: int,
        exclude: PetInstance | None = None,
    ) -> None:
        candidates = [pet for pet in self._living_team(player) if pet is not exclude]
        if not candidates:
            return
        amount = min(amount, len(candidates))
        chosen = self.rng.sample(candidates, amount)
        for pet in chosen:
            pet.attack = min(50, pet.attack + attack)
            pet.health = min(50, pet.health + health)

    def _random_living_pet(self, player: PlayerState) -> PetInstance | None:
        candidates = self._living_team(player)
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def _lowest_health_pet(self, player: PlayerState) -> PetInstance | None:
        candidates = self._living_team(player)
        return min(candidates, key=lambda p: p.health + p.temporary_health) if candidates else None

    def _highest_health_pet(self, player: PlayerState) -> PetInstance | None:
        candidates = self._living_team(player)
        return max(candidates, key=lambda p: p.health + p.temporary_health) if candidates else None

    # ------------------------------------------------------------------
    # Shop slot helpers
    # ------------------------------------------------------------------

    def _insert_shop_food_right(
        self,
        player: PlayerState,
        name: str,
        tier: int,
        cost_override: int | None = None,
        bonus_attack: int = 0,
        bonus_health: int = 0,
    ) -> None:
        """Insert food at the right side of the shop."""
        icon = f"{name.replace(' ', '_')}.png"
        new_offer = ShopOffer(
            kind="food", name=name, tier=tier, frozen=False, icon_file=icon,
            bonus_attack=bonus_attack, bonus_health=bonus_health, cost_override=cost_override,
        )
        insert_shop_offer_from_right(player, new_offer)

    # ------------------------------------------------------------------
    # Summon helpers
    # ------------------------------------------------------------------

    def _summon_at(
        self,
        player: PlayerState,
        preferred_idx: int,
        name: str,
        attack: int,
        health: int,
        level: int,
        callback: SummonCallback | None,
    ) -> PetInstance | None:
        definition = self._make_token_definition(name, attack, health)
        pet = PetInstance(definition=definition, attack=attack, health=health, level=level)
        for idx in [preferred_idx] + list(range(preferred_idx - 1, -1, -1)):
            if 0 <= idx < len(player.team) and player.team[idx] is None:
                player.team[idx] = pet
                if callback:
                    callback(player, idx, pet)
                return pet
        return None

    def _summon_at_front(
        self,
        player: PlayerState,
        name: str,
        attack: int,
        health: int,
        level: int,
        callback: SummonCallback | None,
    ) -> PetInstance | None:
        definition = self._make_token_definition(name, attack, health)
        pet = PetInstance(definition=definition, attack=attack, health=health, level=level)
        for idx in range(len(player.team) - 1, -1, -1):
            if player.team[idx] is None:
                player.team[idx] = pet
                if callback:
                    callback(player, idx, pet)
                return pet
        return None

    def _make_token_definition(self, name: str, attack: int, health: int) -> PetDefinition:
        if name in self.registry.pets:
            return self.registry.pets[name]
        if name in self.registry.tokens:
            tok = self.registry.tokens[name]
            tier = tok.tier or 0
        else:
            tier = 0
        return PetDefinition(
            name=name, tier=tier, attack=attack, health=health,
            icon_file=f"{name.replace(' ', '_')}.png",
        )
