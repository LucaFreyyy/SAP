from __future__ import annotations

from dataclasses import dataclass

from ..models import BattleOutcome, GameState, Phase, PlayerState, ShopState
from ..paths import initial_lives_for_player_count
from ..registry import DataRegistry
from ..rng import SeededRNG
from ..triggers import TriggerEngine
from .battle import BattleEngine
from .shop import ShopEngine


@dataclass(slots=True)
class TurnResult:
    phase: Phase
    battle_result: BattleOutcome | None = None
    battle_pending: bool = False


class CpuGameEngine:
    def __init__(self, registry: DataRegistry, rng: SeededRNG | None = None) -> None:
        self.registry = registry
        self.rng = rng or SeededRNG()
        self.triggers = TriggerEngine(registry, self.rng)
        self.shop = ShopEngine(registry, self.rng)
        self.battle = BattleEngine(self.triggers)

    def new_game(self, player_names: list[str]) -> GameState:
        lives = initial_lives_for_player_count(len(player_names))
        players = [PlayerState(name=name, health=lives, gold=0, shop=ShopState()) for name in player_names]
        state = GameState(phase=Phase.SHOP, players=players, turn=1, active_player_index=0, rng_seed=self.rng.seed)
        self.start_shop_turn(state, 0)
        return state

    def end_shop_turn(self, state: GameState) -> TurnResult:
        current_index = state.active_player_index
        current_player = state.players[current_index]
        self.shop.end_turn(current_player)

        if current_index < len(state.players) - 1:
            self.start_shop_turn(state, current_index + 1)
            return TurnResult(phase=Phase.SHOP)

        state.phase = Phase.BATTLE
        state.battle_pending = True
        return TurnResult(phase=Phase.BATTLE, battle_pending=True)

    def resolve_battle_and_start_next_round(self, state: GameState) -> TurnResult:
        state.battle_pending = False
        state.phase = Phase.BATTLE
        result = self.battle.resolve(state)
        state.turn += 1
        self.start_shop_turn(state, 0)
        return TurnResult(phase=Phase.SHOP, battle_result=result.outcome)

    def start_shop_turn(self, state: GameState, player_index: int) -> None:
        state.active_player_index = player_index
        player = state.players[player_index]
        player.turn = state.turn
        player.gold = 10

        # Life-gain rule (wiki §1): a player who lost any lives in the first 2 turns
        # automatically regains 1 life at the start of turn 3.
        if state.turn == 3 and player.losses > 0:
            player.health += 1

        self.shop.refresh(player)
        self.triggers.apply_start_of_turn(player)
