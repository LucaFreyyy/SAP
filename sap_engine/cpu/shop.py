from __future__ import annotations

from dataclasses import dataclass

from ..models import PetInstance, PlayerState, ShopOffer
from ..paths import shop_slot_layout_for_turn, unlock_tier_for_turn
from ..registry import DataRegistry
from ..rng import SeededRNG
from ..triggers import TriggerEngine


@dataclass(slots=True)
class ShopActionResult:
    success: bool
    message: str = ""


class ShopEngine:
    def __init__(self, registry: DataRegistry, rng: SeededRNG) -> None:
        self.registry = registry
        self.rng = rng
        self.triggers = TriggerEngine(registry, rng)

    def refresh(self, player: PlayerState) -> None:
        player.shop.tier = unlock_tier_for_turn(player.turn)
        layout = shop_slot_layout_for_turn(player.turn)
        if len(player.shop.slots) != len(layout):
            player.shop.slots = [None] * len(layout)
        for index, slot_kind in enumerate(layout):
            current = player.shop.slots[index]
            if current is not None and current.frozen:
                continue
            if slot_kind == "buffer":
                player.shop.slots[index] = None
                continue
            pool = self.registry.pet_pool(player.shop.tier) if slot_kind == "pet" else self.registry.food_pool(player.shop.tier)
            if not pool:
                player.shop.slots[index] = None
                continue
            chosen = self.rng.choice(pool)
            player.shop.slots[index] = ShopOffer(
                kind=slot_kind,
                name=chosen.name,
                tier=chosen.tier,
                frozen=False,
                icon_file=chosen.icon_file,
            )

    def sell_pet(self, player: PlayerState, team_index: int) -> ShopActionResult:
        pet = player.team[team_index]
        if pet is None:
            return ShopActionResult(False, "No pet in that team slot.")
        player.gold += pet.level
        self.triggers.apply_sell(player, pet)
        self.triggers.apply_shop_on_sell(player, pet)
        player.team[team_index] = None
        return ShopActionResult(True, f"Sold {pet.name} for {pet.level} gold.")

    def buy_pet(self, player: PlayerState, shop_index: int, team_index: int | None = None) -> ShopActionResult:
        offer = player.shop.slots[shop_index]
        if offer is None or offer.kind != "pet":
            return ShopActionResult(False, "No pet available in that shop slot.")
        if player.gold < 3:
            return ShopActionResult(False, "Not enough gold.")
        definition = self.registry.pets[offer.name]
        target_index = team_index if team_index is not None else player.first_empty_team_slot()
        if target_index is None:
            return ShopActionResult(False, "Team is full.")

        current = player.team[target_index]
        if current and current.name == definition.name:
            self._merge_instances(current, PetInstance(definition=definition))
            bought = current
        else:
            bought = PetInstance(definition=definition)
            player.team[target_index] = bought

        player.gold -= 3
        player.shop.slots[shop_index] = None
        self.triggers.apply_buy(player, bought)
        return ShopActionResult(True, f"Bought {definition.name}.")

    def buy_food(self, player: PlayerState, shop_index: int, team_index: int) -> ShopActionResult:
        offer = player.shop.slots[shop_index]
        if offer is None or offer.kind != "food":
            return ShopActionResult(False, "No food available in that shop slot.")
        price = 1 if offer.name == "Sleeping Pill" else 3
        if player.gold < price:
            return ShopActionResult(False, "Not enough gold.")
        if player.team[team_index] is None:
            return ShopActionResult(False, "No pet in the target team slot.")
        player.gold -= price
        player.shop.slots[shop_index] = None
        target = player.team[team_index]
        if offer.name == "Chocolate":
            target.experience = min(5, target.experience + 1)
            target.attack = min(50, target.attack + 1)
            target.health = min(50, target.health + 1)
        elif offer.name == "Apple":
            target.attack = min(50, target.attack + 1)
            target.health = min(50, target.health + 1)
        elif offer.name == "Honey":
            target.temporary_health += 1
        return ShopActionResult(True, f"Fed {offer.name}.")

    def end_turn(self, player: PlayerState) -> None:
        self.triggers.apply_end_turn(player)
        player.turn += 1

    @staticmethod
    def _merge_instances(target: PetInstance, source: PetInstance) -> None:
        target.experience += 1 + source.experience
        target.level = 3 if target.experience >= 5 else 2 if target.experience >= 2 else 1
        target.attack = min(50, max(target.attack, source.attack) + 1)
        target.health = min(50, max(target.health, source.health) + 1)
