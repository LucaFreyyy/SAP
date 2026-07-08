"""Shop slot insertion helpers (wiki §4).

Pets enter from the left, food from the right.
Uses the next free slot when available. When the shop is full, cascades toward
the opposite end and evicts the last movable item. Frozen slots are never moved.
If every slot is occupied and frozen, insertion is skipped.
"""
from __future__ import annotations

from ..models import PlayerState, ShopOffer


def insert_shop_offer_from_left(player: PlayerState, offer: ShopOffer) -> bool:
    """Insert a pet offer from the left side of the shop."""
    return _insert_offer(player, offer, from_left=True)


def insert_shop_offer_from_right(player: PlayerState, offer: ShopOffer) -> bool:
    """Insert a food offer from the right side of the shop."""
    return _insert_offer(player, offer, from_left=False)


def _insert_offer(player: PlayerState, offer: ShopOffer, *, from_left: bool) -> bool:
    slots = player.shop.slots
    if not slots:
        return False

    indices = range(len(slots)) if from_left else range(len(slots) - 1, -1, -1)

    for index in indices:
        if slots[index] is None:
            slots[index] = offer
            return True

    if all(slot is not None and slot.frozen for slot in slots):
        return False

    carry: ShopOffer | None = offer
    for index in indices:
        if carry is None:
            break
        current = slots[index]
        if current is None:
            slots[index] = carry
            carry = None
        elif current.frozen:
            continue
        else:
            slots[index] = carry
            carry = current

    return True
