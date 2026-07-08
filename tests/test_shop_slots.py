from sap_engine.cpu.shop_slots import insert_shop_offer_from_left, insert_shop_offer_from_right
from sap_engine.models import PlayerState, ShopOffer, ShopState


def _offer(name: str, *, frozen: bool = False, kind: str = "pet") -> ShopOffer:
    return ShopOffer(kind=kind, name=name, tier=1, frozen=frozen)


def test_insert_pet_uses_leftmost_empty_slot() -> None:
    player = PlayerState(name="P", shop=ShopState(slots=[_offer("A"), None, _offer("B"), None]))
    assert insert_shop_offer_from_left(player, _offer("New"))
    assert player.shop.slots[1].name == "New"
    assert player.shop.slots[0].name == "A"


def test_insert_food_uses_rightmost_empty_slot() -> None:
    player = PlayerState(name="P", shop=ShopState(slots=[None, _offer("Apple", kind="food"), None]))
    assert insert_shop_offer_from_right(player, _offer("Honey", kind="food"))
    assert player.shop.slots[2].name == "Honey"


def test_insert_pet_full_shop_evicts_rightmost_unfrozen() -> None:
    player = PlayerState(
        name="P",
        shop=ShopState(slots=[_offer("A"), _offer("B"), _offer("C")]),
    )
    assert insert_shop_offer_from_left(player, _offer("New"))
    assert player.shop.slots[0].name == "New"
    assert player.shop.slots[1].name == "A"
    assert player.shop.slots[2].name == "B"


def test_insert_pet_skips_frozen_slots_without_moving_them() -> None:
    player = PlayerState(
        name="P",
        shop=ShopState(slots=[_offer("A", frozen=True), _offer("B"), _offer("C")]),
    )
    assert insert_shop_offer_from_left(player, _offer("New"))
    assert player.shop.slots[0].name == "A"
    assert player.shop.slots[0].frozen is True
    assert player.shop.slots[1].name == "New"
    assert player.shop.slots[2].name == "B"


def test_insert_pet_all_frozen_full_shop_fails() -> None:
    player = PlayerState(
        name="P",
        shop=ShopState(slots=[_offer("A", frozen=True), _offer("B", frozen=True)]),
    )
    assert not insert_shop_offer_from_left(player, _offer("New"))
    assert player.shop.slots[0].name == "A"
    assert player.shop.slots[1].name == "B"


def test_insert_food_all_frozen_full_shop_fails() -> None:
    player = PlayerState(
        name="P",
        shop=ShopState(slots=[_offer("A", frozen=True, kind="food"), _offer("B", frozen=True, kind="food")]),
    )
    assert not insert_shop_offer_from_right(player, _offer("Honey", kind="food"))
