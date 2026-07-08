"""Shop engine: buy pets/food, sell, roll, freeze, merge."""
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
    levelled_up: bool = False    # True if a pet just reached a new level
    level_up_pet: str = ""       # Name of the pet that levelled up


class ShopEngine:
    def __init__(self, registry: DataRegistry, rng: SeededRNG) -> None:
        self.registry = registry
        self.rng = rng
        self.triggers = TriggerEngine(registry, rng)

    # ------------------------------------------------------------------
    # Shop management
    # ------------------------------------------------------------------

    def refresh(self, player: PlayerState, *, keep_frozen: bool = True) -> None:
        """Roll the shop — replace all unfrozen slots with fresh offers."""
        player.shop.tier = unlock_tier_for_turn(player.turn)
        layout = shop_slot_layout_for_turn(player.turn)

        if len(player.shop.slots) != len(layout):
            player.shop.slots = [None] * len(layout)

        for index, slot_kind in enumerate(layout):
            current = player.shop.slots[index]
            if keep_frozen and current is not None and current.frozen:
                continue
            if slot_kind == "buffer":
                player.shop.slots[index] = None
                continue
            pool = (
                self.registry.pet_pool(player.shop.tier)
                if slot_kind == "pet"
                else self.registry.food_pool(player.shop.tier)
            )
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
                bonus_attack=player.shop_attack_bonus if slot_kind == "pet" else 0,
                bonus_health=player.shop_health_bonus if slot_kind == "pet" else 0,
            )

    def roll_shop(self, player: PlayerState) -> ShopActionResult:
        """Spend 1 gold to reroll all unfrozen slots."""
        if player.gold < 1:
            return ShopActionResult(False, "Not enough gold to roll (costs 1).")
        player.gold -= 1
        player.actions += 1
        self.refresh(player)
        return ShopActionResult(True, "Shop rolled.")

    def freeze_slot(self, player: PlayerState, shop_index: int) -> ShopActionResult:
        """Toggle freeze on a shop slot."""
        if not (0 <= shop_index < len(player.shop.slots)):
            return ShopActionResult(False, "Invalid shop index.")
        offer = player.shop.slots[shop_index]
        if offer is None:
            return ShopActionResult(False, "No item in that slot.")
        offer.frozen = not offer.frozen
        state = "frozen" if offer.frozen else "unfrozen"
        return ShopActionResult(True, f"{offer.name} {state}.")

    # ------------------------------------------------------------------
    # Buying pets
    # ------------------------------------------------------------------

    def buy_pet(
        self,
        player: PlayerState,
        shop_index: int,
        team_index: int | None = None,
    ) -> ShopActionResult:
        """Buy a pet from the shop and place it on the team.

        Placement rules (per wiki):
        - Empty slot: place there directly.
        - Same-named pet: merge (gain XP, take max stats +1).
        - Different pet + team has an empty slot: push existing pet(s) toward
          the back (lower indices) to make room.
        - Different pet + team is full: fail.
        """
        if not (0 <= shop_index < len(player.shop.slots)):
            return ShopActionResult(False, "Invalid shop index.")
        offer = player.shop.slots[shop_index]
        if offer is None or offer.kind != "pet":
            return ShopActionResult(False, "No pet available in that shop slot.")
        if player.gold < 3:
            return ShopActionResult(False, "Not enough gold.")
        if offer.name not in self.registry.pets:
            return ShopActionResult(False, f"Unknown pet: {offer.name}.")

        definition = self.registry.pets[offer.name]

        if team_index is None:
            team_index = player.first_empty_team_slot()
        if team_index is None:
            return ShopActionResult(False, "Team is full.")
        if not (0 <= team_index < 5):
            return ShopActionResult(False, "Invalid team index.")

        current = player.team[team_index]
        levelled_up = False
        level_up_pet_name = ""

        if current is not None and current.name == definition.name:
            # --- Merge ---
            old_level = current.level
            source = PetInstance(
                definition=definition,
                attack=min(50, definition.attack + offer.bonus_attack),
                health=min(50, definition.health + offer.bonus_health),
            )
            _merge_instances(current, source)
            bought = current
            if current.level > old_level:
                levelled_up = True
                level_up_pet_name = current.name
                self.triggers.apply_fish_level_up(player, current)

        elif current is None:
            # --- Place in empty slot ---
            atk = min(50, definition.attack + offer.bonus_attack)
            hp = min(50, definition.health + offer.bonus_health)
            bought = PetInstance(definition=definition, attack=atk, health=hp)
            player.team[team_index] = bought
            self.triggers.apply_friend_summoned(bought, player)

        else:
            # --- Push and place ---
            if player.first_empty_team_slot() is None:
                return ShopActionResult(False, "Team is full; cannot push pet.")
            _push_team_back(player, team_index)
            atk = min(50, definition.attack + offer.bonus_attack)
            hp = min(50, definition.health + offer.bonus_health)
            bought = PetInstance(definition=definition, attack=atk, health=hp)
            player.team[team_index] = bought
            self.triggers.apply_friend_summoned(bought, player)

        player.gold -= 3
        player.shop.slots[shop_index] = None
        player.actions += 1
        self.triggers.apply_buy(player, bought)
        return ShopActionResult(True, f"Bought {definition.name}.", levelled_up, level_up_pet_name)

    def move_pet(self, player: PlayerState, from_index: int, to_index: int) -> ShopActionResult:
        """Reposition or merge a team pet."""
        if not (0 <= from_index < 5 and 0 <= to_index < 5):
            return ShopActionResult(False, "Invalid team index.")
        src = player.team[from_index]
        if src is None:
            return ShopActionResult(False, "No pet in source slot.")
        dst = player.team[to_index]

        if dst is not None and dst.name == src.name:
            old_level = dst.level
            _merge_instances(dst, src)
            player.team[from_index] = None
            if dst.level > old_level:
                self.triggers.apply_fish_level_up(player, dst)
            player.actions += 1
            return ShopActionResult(True, f"Merged {src.name}.", dst.level > old_level, src.name)
        else:
            player.team[from_index], player.team[to_index] = player.team[to_index], player.team[from_index]
            player.actions += 1
            return ShopActionResult(True, f"Moved {src.name}.")

    # ------------------------------------------------------------------
    # Selling pets
    # ------------------------------------------------------------------

    def sell_pet(self, player: PlayerState, team_index: int) -> ShopActionResult:
        if not (0 <= team_index < 5):
            return ShopActionResult(False, "Invalid team index.")
        pet = player.team[team_index]
        if pet is None:
            return ShopActionResult(False, "No pet in that team slot.")

        # Sell value = level + Cake perk bonus (perk_uses = number of turns held)
        sell_value = pet.level
        if pet.perk == "cake":
            sell_value += pet.perk_uses

        player.gold = min(player.gold + sell_value, 999)
        player.team[team_index] = None
        player.actions += 1
        self.triggers.apply_sell(player, pet)
        return ShopActionResult(True, f"Sold {pet.name} for {sell_value} gold.")

    # ------------------------------------------------------------------
    # Buying food
    # ------------------------------------------------------------------

    def buy_food(
        self,
        player: PlayerState,
        shop_index: int,
        team_index: int | None = None,
    ) -> ShopActionResult:
        """Buy a food item from the shop and apply its effect."""
        if not (0 <= shop_index < len(player.shop.slots)):
            return ShopActionResult(False, "Invalid shop index.")
        offer = player.shop.slots[shop_index]
        if offer is None or offer.kind != "food":
            return ShopActionResult(False, "No food available in that shop slot.")

        name = offer.name

        # Determine price
        if offer.cost_override is not None:
            price = offer.cost_override
        elif name == "Sleeping Pill":
            price = 1
        else:
            price = max(0, 3 - player.food_cost_discount)

        if player.gold < price:
            return ShopActionResult(False, "Not enough gold.")

        # Foods requiring a pet target
        TARGETED = {
            "Apple", "Better Apple", "Best Apple",
            "Honey", "Sleeping Pill", "Meat Bone", "Cupcake",
            "Garlic", "Cake", "Bread", "Pear", "Chili",
            "Chocolate", "Steak", "Melon", "Mushroom",
            "Milk", "Better Milk", "Best Milk",
            "Bread Crumbs",
        }

        target: PetInstance | None = None
        if name in TARGETED:
            if team_index is None or not (0 <= team_index < 5):
                return ShopActionResult(False, "Must choose a valid team slot for this food.")
            target = player.team[team_index]
            if target is None:
                return ShopActionResult(False, "No pet in the target team slot.")

        player.gold -= price
        player.shop.slots[shop_index] = None
        player.actions += 1

        levelled_up = False
        level_up_pet_name = ""

        # ------- Apply effect -------
        # Cat multiplier: foods that give stat bonuses are multiplied
        # (does NOT apply to perk foods, Chocolate, Sleeping Pill, Canned Food)
        CAT_MULTIPLIED = {
            "Apple", "Better Apple", "Best Apple", "Bread Crumbs",
            "Milk", "Better Milk", "Best Milk", "Pear", "Cupcake",
            "Salad Bowl", "Sushi", "Pizza",
        }
        if name in CAT_MULTIPLIED:
            cat_mult = self.triggers.cat_food_multiplier(player)
            self.triggers.consume_cat_use(player)
        else:
            cat_mult = 1

        if name in ("Apple", "Better Apple", "Best Apple"):
            bonus = {"Apple": 1, "Better Apple": 2, "Best Apple": 3}[name] * cat_mult
            target.attack = min(50, target.attack + bonus)
            target.health = min(50, target.health + bonus)
            self.triggers.apply_eats_food(player, target)

        elif name == "Bread Crumbs":
            target.attack = min(50, target.attack + 1 * cat_mult)
            self.triggers.apply_eats_food(player, target)

        elif name in ("Milk", "Better Milk", "Best Milk"):
            target.attack = min(50, target.attack + 1 * cat_mult)
            target.health = min(50, target.health + 2 * cat_mult)
            self.triggers.apply_eats_food(player, target)

        elif name == "Pear":
            target.attack = min(50, target.attack + 2 * cat_mult)
            target.health = min(50, target.health + 2 * cat_mult)
            self.triggers.apply_eats_food(player, target)

        elif name == "Honey":
            target.perk = "honey"
            target.perk_uses = 0
            self.triggers.apply_eats_food(player, target)

        elif name == "Meat Bone":
            target.perk = "meat_bone"
            target.perk_uses = 0
            self.triggers.apply_eats_food(player, target)

        elif name == "Cupcake":
            target.temporary_attack += 3 * cat_mult
            target.temporary_health += 3 * cat_mult
            self.triggers.apply_eats_food(player, target)

        elif name == "Garlic":
            target.perk = "garlic"
            target.perk_uses = 0
            self.triggers.apply_eats_food(player, target)

        elif name == "Cake":
            target.perk = "cake"
            target.perk_uses = 0
            self.triggers.apply_eats_food(player, target)

        elif name == "Bread":
            target.perk = "bread"
            target.perk_uses = 0
            self.triggers.apply_eats_food(player, target)

        elif name == "Salad Bowl":
            _buff_random_team(player, self.rng, amount=2, attack=1 * cat_mult, health=1 * cat_mult)

        elif name == "Canned Food":
            player.shop_attack_bonus += 1
            player.shop_health_bonus += 1
            for slot in player.shop.slots:
                if slot is not None and slot.kind == "pet":
                    slot.bonus_attack += 1
                    slot.bonus_health += 1

        elif name == "Chili":
            target.perk = "chili"
            target.perk_uses = 0
            self.triggers.apply_eats_food(player, target)

        elif name == "Chocolate":
            # Cat does NOT affect Chocolate (per wiki)
            old_level = target.level
            target.experience = min(5, target.experience + 1)
            target.attack = min(50, target.attack + 1)
            target.health = min(50, target.health + 1)
            _update_level(target)
            if target.level > old_level:
                levelled_up = True
                level_up_pet_name = target.name
                self.triggers.apply_fish_level_up(player, target)
            self.triggers.apply_eats_food(player, target)

        elif name == "Sushi":
            _buff_random_team(player, self.rng, amount=3, attack=1 * cat_mult, health=1 * cat_mult)

        elif name == "Steak":
            target.perk = "steak"
            target.perk_uses = 0
            self.triggers.apply_eats_food(player, target)

        elif name == "Melon":
            target.perk = "melon"
            target.perk_uses = 0
            self.triggers.apply_eats_food(player, target)

        elif name == "Mushroom":
            target.perk = "mushroom"
            target.perk_uses = 0
            self.triggers.apply_eats_food(player, target)

        elif name == "Pizza":
            _buff_random_team(player, self.rng, amount=2, attack=2 * cat_mult, health=2 * cat_mult)

        elif name == "Sleeping Pill":
            # Kill the target — triggers Faint, does NOT trigger Eats Food
            idx = next((i for i, p in enumerate(player.team) if p is target), -1)
            if idx >= 0:
                player.team[idx] = None
                target.health = 0
                # In shop phase the "opponent" is the same player (no enemy present)
                self.triggers.apply_faint(target, idx, player, player)

        return ShopActionResult(True, f"Fed {name}.", levelled_up, level_up_pet_name)

    # ------------------------------------------------------------------
    # End turn
    # ------------------------------------------------------------------

    def end_turn(self, player: PlayerState) -> None:
        """Fire end-of-turn triggers and increment the player's turn counter."""
        self.triggers.apply_end_turn(player)
        player.turn += 1


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _merge_instances(target: PetInstance, source: PetInstance) -> None:
    """Merge source into target following wiki XP rules.

    XP gained = source.experience + 1 (for the merge itself).
    Stats = max(target, source) + 1 for both attack and health.
    Level 2 at 2 XP total, Level 3 at 5 XP total (max).
    """
    target.experience = min(5, target.experience + source.experience + 1)
    target.level = 3 if target.experience >= 5 else 2 if target.experience >= 2 else 1
    target.attack = min(50, max(target.attack, source.attack) + 1)
    target.health = min(50, max(target.health, source.health) + 1)
    # Perk: target's perk prevails if both have one; otherwise the existing perk survives
    if target.perk is None and source.perk is not None:
        target.perk = source.perk
        target.perk_uses = source.perk_uses


def _push_team_back(player: PlayerState, from_index: int) -> None:
    """Push pets at from_index toward lower indices to create an empty slot at from_index.

    Finds the nearest empty slot at or below from_index and shifts all pets
    between that empty slot and from_index one step toward lower indices.
    If no empty slot exists below, searches above (shifts up instead).

    Example: team=[A,B,_,C,D], from_index=3 (C's slot)
        → nearest empty below = index 2
        → shift: team[2]=team[3]=C, team[3]=None
        → result: [A,B,C,_,D] → caller places new pet at index 3
    """
    team = player.team

    # Look for nearest empty at or below from_index
    empty_below = None
    for i in range(from_index, -1, -1):
        if team[i] is None:
            empty_below = i
            break

    if empty_below is not None and empty_below < from_index:
        # Shift range [empty_below, from_index-1] one step toward lower indices
        for i in range(empty_below, from_index):
            team[i] = team[i + 1]
        team[from_index] = None
        return

    # No empty slot at or below — find nearest empty above from_index
    empty_above = None
    for i in range(from_index + 1, len(team)):
        if team[i] is None:
            empty_above = i
            break

    if empty_above is not None:
        # Shift range [from_index+1, empty_above] one step toward higher indices
        for i in range(empty_above, from_index, -1):
            team[i] = team[i - 1]
        team[from_index] = None


def _update_level(pet: PetInstance) -> None:
    """Recompute level from current experience."""
    pet.level = 3 if pet.experience >= 5 else 2 if pet.experience >= 2 else 1


def _buff_random_team(
    player: PlayerState,
    rng: SeededRNG,
    amount: int,
    attack: int,
    health: int,
) -> None:
    candidates = [pet for pet in player.team if pet is not None and pet.health > 0]
    if not candidates:
        return
    amount = min(amount, len(candidates))
    chosen = rng.sample(candidates, amount)
    for pet in chosen:
        pet.attack = min(50, pet.attack + attack)
        pet.health = min(50, pet.health + health)
