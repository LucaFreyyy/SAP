from sap_engine.models import BattleOutcome, GameState, Phase, PlayerState, ShopState


def test_game_state_round_trip_structure() -> None:
    state = GameState(
        phase=Phase.SHOP,
        players=[PlayerState(name="Alpha", health=6, shop=ShopState()), PlayerState(name="Beta", health=6, shop=ShopState())],
        turn=3,
        last_battle_result=BattleOutcome.WIN,
        rng_seed=123,
    )

    payload = state.to_dict()
    assert payload["phase"] == "shop"
    assert payload["turn"] == 3
    assert payload["players"][0]["health"] == 6
    assert payload["last_battle_result"] == "win"
