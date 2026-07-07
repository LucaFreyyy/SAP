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


@dataclass(slots=True)
class PetInstance:
    definition: PetDefinition
    attack: int | None = None
    health: int | None = None
    level: int = 1
    experience: int = 0
    temporary_attack: int = 0
    temporary_health: int = 0

    def __post_init__(self) -> None:
        if self.attack is None:
            self.attack = self.definition.attack
        if self.health is None:
            self.health = self.definition.health

    @property
    def name(self) -> str:
        return self.definition.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition": self.definition.name,
            "attack": self.attack,
            "health": self.health,
            "level": self.level,
            "experience": self.experience,
            "temporary_attack": self.temporary_attack,
            "temporary_health": self.temporary_health,
        }


@dataclass(slots=True)
class ShopOffer:
    kind: str
    name: str
    tier: int
    frozen: bool = False
    icon_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "tier": self.tier,
            "frozen": self.frozen,
            "icon_file": self.icon_file,
        }


@dataclass(slots=True)
class ShopState:
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
        }


@dataclass(slots=True)
class BattleSnapshot:
    attacker_name: str | None = None
    defender_name: str | None = None
    step_index: int = 0
    finished: bool = False
    outcome: BattleOutcome = BattleOutcome.ONGOING

    def to_dict(self) -> dict[str, Any]:
        return {
            "attacker_name": self.attacker_name,
            "defender_name": self.defender_name,
            "step_index": self.step_index,
            "finished": self.finished,
            "outcome": self.outcome.value,
        }


@dataclass(slots=True)
class GameState:
    phase: Phase
    players: list[PlayerState]
    turn: int = 1
    active_player_index: int = 0
    battle_pending: bool = False
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
            "last_battle_result": self.last_battle_result.value,
            "battle": self.battle.to_dict(),
            "rng_seed": self.rng_seed,
            "players": [player.to_dict() for player in self.players],
        }
