from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Phase(str, Enum):
    SHOP = "shop"
    BATTLE = "battle"
    TRANSITION = "transition"


class BattleOutcome(str, Enum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
    ONGOING = "ongoing"


class TriggerType(str, Enum):
    START_OF_TURN = "start_of_turn"
    BUY = "buy"
    EATS_FOOD = "eats_food"
    END_TURN = "end_turn"
    START_OF_BATTLE = "start_of_battle"
    BEFORE_ATTACK = "before_attack"
    AFTER_ATTACK = "after_attack"
    FRIEND_AHEAD_ATTACKS = "friend_ahead_attacks"
    HURT = "hurt"
    FAINT = "faint"
    FRIEND_AHEAD_FAINTS = "friend_ahead_faints"
    FRIEND_FAINTS = "friend_faints"
    FRIEND_SUMMONED = "friend_summoned"
    KNOCK_OUT = "knock_out"
    LEVELS_UP = "levels_up"
    SELL = "sell"


@dataclass(slots=True)
class PetDefinition:
    name: str
    tier: int
    attack: int
    health: int
    ability_text: tuple[str, ...] = ()
    description: str = ""
    icon_file: str | None = None


@dataclass(slots=True)
class FoodDefinition:
    name: str
    tier: int
    effect: str
    description: str = ""
    icon_file: str | None = None


@dataclass(slots=True)
class TokenDefinition:
    name: str
    tier: int | None = None
    effect: str = ""
    description: str = ""
    icon_file: str | None = None


# Valid perk names
PERK_NAMES = frozenset({
    "honey",       # summon 1/1 Bee on faint
    "melon",       # block 20 damage once
    "garlic",      # take 2 less damage (min 2)
    "meat_bone",   # attack with +3 bonus damage
    "steak",       # attack with +20 bonus once
    "chili",       # deal 5 damage to 2nd enemy after attacking
    "mushroom",    # come back as 1/1 on faint
    "cake",        # sell value +1 at end of turn
    "bread",       # gain +7 health until next turn (end turn)
    "peanut",      # instantly knock out any enemy this pet hurts
    "coconut",     # block any damage once (token perk)
})


@dataclass(slots=True)
class PetInstance:
    definition: PetDefinition
    attack: int | None = None
    health: int | None = None
    level: int = 1
    experience: int = 0
    temporary_attack: int = 0
    temporary_health: int = 0
    perk: str | None = None            # active food perk (see PERK_NAMES)
    perk_uses: int = 0                 # how many times perk has been consumed (for one-time perks)
    copied_ability: str | None = None  # Parrot: copied pet name until next turn
    knock_out_count: int = 0           # for Hippo's 3x/battle limit
    ability_uses: int = 0              # per-battle use counter (Snake 5/turn, Fly 3/turn, Gorilla N/turn)

    def __post_init__(self) -> None:
        if self.attack is None:
            self.attack = self.definition.attack
        if self.health is None:
            self.health = self.definition.health

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def tier(self) -> int:
        return self.definition.tier

    @property
    def effective_attack(self) -> int:
        """Base attack plus temporary attack buffs."""
        return self.attack + self.temporary_attack

    @property
    def effective_health(self) -> int:
        """Base health plus temporary health buffs."""
        return self.health + self.temporary_health

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition": self.definition.name,
            "attack": self.attack,
            "health": self.health,
            "level": self.level,
            "experience": self.experience,
            "temporary_attack": self.temporary_attack,
            "temporary_health": self.temporary_health,
            "perk": self.perk,
            "perk_uses": self.perk_uses,
            "copied_ability": self.copied_ability,
        }


@dataclass(slots=True)
class ShopOffer:
    kind: str           # "pet", "food", or "buffer"
    name: str
    tier: int
    frozen: bool = False
    icon_file: str | None = None
    bonus_attack: int = 0   # extra attack applied when this pet is bought (Duck sell, Canned Food)
    bonus_health: int = 0   # extra health applied when this pet is bought (Duck sell, Canned Food, Worm)
    cost_override: int | None = None  # override the standard 3-gold cost (e.g., Worm Apple at 2 gold)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "tier": self.tier,
            "frozen": self.frozen,
            "icon_file": self.icon_file,
            "bonus_attack": self.bonus_attack,
            "bonus_health": self.bonus_health,
            "cost_override": self.cost_override,
        }


@dataclass(slots=True)
class ShopState:
    # 9 slots: pets | buffers | foods (layout varies by turn)
    slots: list[ShopOffer | None] = field(default_factory=lambda: [None] * 9)
    tier: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "slots": [slot.to_dict() if slot else None for slot in self.slots]}


@dataclass(slots=True)
class PlayerState:
    name: str
    team: list[PetInstance | None] = field(default_factory=lambda: [None] * 5)
    shop: ShopState = field(default_factory=ShopState)
    gold: int = 10
    health: int = 5
    last_battle_result: BattleOutcome = BattleOutcome.ONGOING
    turn: int = 1
    wins: int = 0
    losses: int = 0
    # Permanent shop buffs from Canned Food (applied to all current & future shop pets)
    shop_attack_bonus: int = 0
    shop_health_bonus: int = 0
    # Squirrel food cost discount this turn
    food_cost_discount: int = 0
    # Rabbit's "eats food" trigger works 3 times per turn
    rabbit_count_this_turn: int = 0
    # Action counter for tiebreaker (25-round game)
    actions: int = 0
    # Wolverine: cumulative hurt events this battle (fires every 4)
    hurt_count_this_battle: int = 0
    # Dragon: tier-1 pet buy trigger, max 4 fires per shop turn
    dragon_buys_this_turn: int = 0
    # Cat: food stat multiplier remaining uses this shop turn
    cat_food_uses_this_turn: int = 0

    def compact_team(self) -> list[PetInstance]:
        return [pet for pet in self.team if pet is not None]

    def first_empty_team_slot(self) -> int | None:
        for index, pet in enumerate(self.team):
            if pet is None:
                return index
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "team": [pet.to_dict() if pet else None for pet in self.team],
            "shop": self.shop.to_dict(),
            "gold": self.gold,
            "health": self.health,
            "last_battle_result": self.last_battle_result.value,
            "turn": self.turn,
            "wins": self.wins,
            "losses": self.losses,
            "shop_attack_bonus": self.shop_attack_bonus,
            "shop_health_bonus": self.shop_health_bonus,
            "food_cost_discount": self.food_cost_discount,
            "actions": self.actions,
        }


@dataclass(slots=True)
class BattleSnapshot:
    attacker_name: str | None = None
    defender_name: str | None = None
    step_index: int = 0
    finished: bool = False
    outcome: BattleOutcome = BattleOutcome.ONGOING
    # Store snapshots of team states at each step for replay
    step_history: list[dict] = field(default_factory=list)
    current_step: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacker_name": self.attacker_name,
            "defender_name": self.defender_name,
            "step_index": self.step_index,
            "finished": self.finished,
            "outcome": self.outcome.value,
            "step_history": self.step_history,
            "current_step": self.current_step,
        }


@dataclass(slots=True)
class GameState:
    phase: Phase
    players: list[PlayerState]
    turn: int = 1
    active_player_index: int = 0
    battle_pending: bool = False
    finished: bool = False
    winner_index: int | None = None
    finish_reason: str | None = None
    last_battle_result: BattleOutcome = BattleOutcome.ONGOING
    battle: BattleSnapshot = field(default_factory=BattleSnapshot)
    rng_seed: int | None = None

    def current_player(self) -> PlayerState:
        return self.players[self.active_player_index]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "turn": self.turn,
            "active_player_index": self.active_player_index,
            "battle_pending": self.battle_pending,
            "finished": self.finished,
            "winner_index": self.winner_index,
            "finish_reason": self.finish_reason,
            "last_battle_result": self.last_battle_result.value,
            "battle": self.battle.to_dict(),
            "rng_seed": self.rng_seed,
            "players": [player.to_dict() for player in self.players],
        }
