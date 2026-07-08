from sap_engine.cpu.shop_slots import (
    insert_shop_offer_from_left,
    insert_shop_offer_from_right,
    reposition_frozen_offers_for_roll,
)
from sap_engine.models import PlayerState, ShopOffer, ShopState
from sap_engine.paths import shop_slot_layout_for_turn


def _layout_turn_1() -> tuple[str, ...]:
    return shop_slot_layout_for_turn(1)


def _offer(name: str, *, frozen: bool = False, kind: str = "pet") -> ShopOffer:
    return ShopOffer(kind=kind, name=name, tier=1, frozen=frozen)


def _slots(*names: str | None) -> list[ShopOffer | None]:
    return [_offer(name) if name else None for name in names]


def test_insert_pet_uses_leftmost_empty_slot_when_nothing_to_push() -> None:
    player = PlayerState(name="P", shop=ShopState(slots=[None, _offer("A"), _offer("B")]))
    assert insert_shop_offer_from_left(player, _offer("New"))
    assert player.shop.slots[0].name == "New"
    assert player.shop.slots[1].name == "A"


def test_insert_pet_pushes_through_gap_from_the_left() -> None:
    player = PlayerState(name="P", shop=ShopState(slots=[_offer("A"), None, _offer("B")]))
    assert insert_shop_offer_from_left(player, _offer("New"))
    assert [slot.name if slot else None for slot in player.shop.slots] == ["New", "A", "B"]


def test_insert_food_uses_rightmost_empty_slot_when_nothing_to_push() -> None:
    player = PlayerState(name="P", shop=ShopState(slots=[None, _offer("Apple", kind="food"), None]))
    assert insert_shop_offer_from_right(player, _offer("Honey", kind="food"))
    assert player.shop.slots[2].name == "Honey"
    assert player.shop.slots[1].name == "Apple"


def test_insert_food_pushes_through_gap_from_the_right() -> None:
    player = PlayerState(name="P", shop=ShopState(slots=[_offer("A"), None, _offer("B", kind="food")]))
    assert insert_shop_offer_from_right(player, _offer("Honey", kind="food"))
    assert [slot.name if slot else None for slot in player.shop.slots] == ["A", "B", "Honey"]


def test_insert_pet_full_shop_evicts_rightmost_unfrozen() -> None:
    player = PlayerState(name="P", shop=ShopState(slots=[_offer("A"), _offer("B"), _offer("C")]))
    assert insert_shop_offer_from_left(player, _offer("New"))
    assert [slot.name if slot else None for slot in player.shop.slots] == ["New", "A", "B"]


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


def test_insert_pet_full_shop_evicts_eighth_when_ninth_is_frozen() -> None:
    slots = _slots("A", "B", "C", "D", "E", "F", "G", "H", "I")
    slots[8].frozen = True
    player = PlayerState(name="P", shop=ShopState(slots=slots))
    assert insert_shop_offer_from_left(player, _offer("New"))
    names = [slot.name if slot else None for slot in player.shop.slots]
    assert names[0] == "New"
    assert names[7] == "G"
    assert names[8] == "I"
    assert "H" not in names


def test_insert_pet_full_shop_evicts_seventh_when_eighth_and_ninth_are_frozen() -> None:
    slots = _slots("A", "B", "C", "D", "E", "F", "G", "H", "I")
    slots[7].frozen = True
    slots[8].frozen = True
    player = PlayerState(name="P", shop=ShopState(slots=slots))
    assert insert_shop_offer_from_left(player, _offer("New"))
    names = [slot.name if slot else None for slot in player.shop.slots]
    assert names[0] == "New"
    assert names[6] == "F"
    assert names[7] == "H"
    assert names[8] == "I"
    assert "G" not in names


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


def test_roll_repositions_frozen_pet_from_buffer_to_pet_field() -> None:
    layout = _layout_turn_1()
    slots: list[ShopOffer | None] = [_offer("A"), _offer("B"), _offer("C"), None, None, _offer("Frozen", frozen=True), None, None, _offer("Apple", kind="food")]
    reposition_frozen_offers_for_roll(slots, layout)
    assert slots[0].name == "Frozen"
    assert slots[0].frozen is True
    assert slots[5] is None


def test_roll_repositions_frozen_food_from_buffer_to_food_field() -> None:
    layout = _layout_turn_1()
    slots: list[ShopOffer | None] = [_offer("A"), _offer("B"), _offer("C"), None, _offer("Honey", kind="food", frozen=True), None, None, None, None]
    reposition_frozen_offers_for_roll(slots, layout)
    assert slots[8].name == "Honey"
    assert slots[8].frozen is True
    assert slots[4] is None


def test_roll_clears_unfrozen_offers_before_repositioning_frozen() -> None:
    layout = _layout_turn_1()
    slots: list[ShopOffer | None] = [_offer("A"), None, _offer("C"), None, None, _offer("Frozen", frozen=True), None, None, None]
    reposition_frozen_offers_for_roll(slots, layout)
    assert slots[0].name == "Frozen"
    assert slots[1] is None
    assert slots[2] is None

