from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import BattleOutcome, PetInstance, PlayerState, ShopOffer
from .paths import SHOP_SLOT_LAYOUT
from .registry import DataRegistry
from .rng import SeededRNG


@dataclass(slots=True)
class TriggerResult:
    changed: bool
    message: str = ""


class TriggerEngine:
    def __init__(self, registry: DataRegistry, rng: SeededRNG) -> None:
        self.registry = registry
        self.rng = rng

    def apply_start_of_turn(self, player: PlayerState) -> None:
        for pet in self._living_team(player):
            if pet.name == "Swan":
                player.gold += pet.level

    def apply_end_turn(self, player: PlayerState) -> None:
        if player.last_battle_result != BattleOutcome.LOSS:
            return
        snail = self._first_pet_by_name(player, "Snail")
        if snail is None:
            return
        bonus = snail.level
        for index in self._friend_indexes_ahead(player, snail):
            friend = player.team[index]
            if friend is not None:
                friend.attack = min(50, friend.attack + bonus)

    def apply_buy(self, player: PlayerState, bought_pet: PetInstance) -> None:
        if bought_pet.name == "Otter":
            self._buff_random_friends(player, amount=bought_pet.level, attack=0, health=1)
        elif bought_pet.name == "Horse":
            bought_pet.temporary_attack += bought_pet.level

    def apply_sell(self, player: PlayerState, sold_pet: PetInstance) -> None:
        if sold_pet.name == "Pig":
            player.gold += sold_pet.level
        elif sold_pet.name == "Beaver":
            self._buff_random_friends(player, amount=2, attack=sold_pet.level, health=0)

    def apply_shop_on_sell(self, player: PlayerState, sold_pet: PetInstance) -> None:
        if sold_pet.name == "Duck":
            for offer in player.shop.slots:
                if offer is not None and offer.kind == "pet":
                    offer.tier = max(offer.tier, sold_pet.level)
        elif sold_pet.name == "Pigeon":
            self._insert_shop_food(player, name="Bread Crumbs", tier=1)

    def apply_start_of_battle(self, player: PlayerState, opponent: PlayerState) -> None:
        for pet in self._living_team(player):
            if pet.name == "Mosquito":
                for _ in range(pet.level):
                    target = self._random_living_pet(opponent)
                    if target is None:
                        return
                    self._deal_damage(target, 1)
            elif pet.name == "Dodo":
                target = self._friend_ahead(player, pet)
                if target is not None:
                    target.attack = min(50, target.attack + max(1, pet.attack // 2) * pet.level)
            elif pet.name == "Dolphin":
                for _ in range(pet.level):
                    target = self._lowest_health_pet(opponent)
                    if target is None:
                        return
                    self._deal_damage(target, 4)
            elif pet.name == "Crab":
                healthiest = self._highest_health_pet(player)
                if healthiest is not None and healthiest is not pet:
                    bonus = max(1, healthiest.health * (25 * pet.level) // 100)
                    pet.health = min(50, pet.health + bonus)

    def apply_after_attack(self, player: PlayerState, attacker: PetInstance) -> None:
        if attacker.name != "Elephant":
            return
        behind = self._friend_behind(player, attacker)
        if behind is not None:
            self._deal_damage(behind, 1)

    def _living_team(self, player: PlayerState) -> list[PetInstance]:
        return [pet for pet in player.team if pet is not None and pet.health > 0]

    def _first_pet_by_name(self, player: PlayerState, name: str) -> PetInstance | None:
        for pet in player.team:
            if pet is not None and pet.name == name and pet.health > 0:
                return pet
        return None

    def _friend_indexes_ahead(self, player: PlayerState, pet: PetInstance) -> list[int]:
        index = player.team.index(pet)
        return [candidate for candidate in range(0, index)]

    def _friend_ahead(self, player: PlayerState, pet: PetInstance) -> PetInstance | None:
        for index in reversed(self._friend_indexes_ahead(player, pet)):
            friend = player.team[index]
            if friend is not None and friend.health > 0:
                return friend
        return None

    def _friend_behind(self, player: PlayerState, pet: PetInstance) -> PetInstance | None:
        index = player.team.index(pet)
        for candidate in range(index + 1, len(player.team)):
            friend = player.team[candidate]
            if friend is not None and friend.health > 0:
                return friend
        return None

    def _buff_random_friends(self, player: PlayerState, amount: int, attack: int, health: int) -> None:
        candidates = [pet for pet in self._living_team(player)]
        if not candidates:
            return
        amount = min(amount, len(candidates))
        chosen = self.rng.sample(candidates, amount)
        for pet in chosen:
            pet.attack = min(50, pet.attack + attack)
            pet.health = min(50, pet.health + health)

    def _insert_shop_food(self, player: PlayerState, name: str, tier: int) -> None:
        for index in range(len(player.shop.slots) - 1, -1, -1):
            if player.shop.slots[index] is None:
                player.shop.slots[index] = ShopOffer(kind="food", name=name, tier=tier, frozen=False, icon_file=f"{name.replace(' ', '_')}.png")
                return

    def _random_living_pet(self, player: PlayerState) -> PetInstance | None:
        candidates = self._living_team(player)
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def _lowest_health_pet(self, player: PlayerState) -> PetInstance | None:
        candidates = self._living_team(player)
        return min(candidates, key=lambda pet: pet.health) if candidates else None

    def _highest_health_pet(self, player: PlayerState) -> PetInstance | None:
        candidates = self._living_team(player)
        return max(candidates, key=lambda pet: pet.health) if candidates else None

    def _deal_damage(self, pet: PetInstance, amount: int) -> None:
        pet.health -= amount
