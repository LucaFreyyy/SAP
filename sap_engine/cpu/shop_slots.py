"""Shop slot insertion helpers (wiki §4).

Pets enter from the left, food from the right.
Always cascades from the entry side: new items push existing offers toward
the opposite end. Frozen slots never move. When the shop is full, the offer
at the opposite end is evicted; if that slot is frozen, walk inward until an
unfrozen offer can be removed. If every slot is occupied and frozen, skip.
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

    full = all(slot is not None for slot in slots)
    if full and not _can_evict(slots, from_left=from_left):
        return False

    indices = range(len(slots)) if from_left else range(len(slots) - 1, -1, -1)
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

    if carry is not None and full:
        # Evicted offer from the far end (or the rightmost movable slot).
        return True
    return carry is None


def _can_evict(slots: list[ShopOffer | None], *, from_left: bool) -> bool:
    indices = range(len(slots) - 1, -1, -1) if from_left else range(len(slots))
    return any(slots[index] is not None and not slots[index].frozen for index in indices)


def reposition_frozen_offers_for_roll(
    slots: list[ShopOffer | None],
    layout: tuple[str, ...],
) -> None:
    """Remove unfrozen offers, then pack frozen pets left and frozen foods right."""
    frozen_pets: list[ShopOffer] = []
    frozen_foods: list[ShopOffer] = []

    for index, offer in enumerate(slots):
        if offer is None:
            continue
        if offer.frozen:
            if offer.kind == "pet":
                frozen_pets.append(offer)
            elif offer.kind == "food":
                frozen_foods.append(offer)
            slots[index] = None
        else:
            slots[index] = None

    pet_indices = [index for index, kind in enumerate(layout) if kind == "pet"]
    food_indices = [index for index, kind in enumerate(layout) if kind == "food"]
    buffer_indices = [index for index, kind in enumerate(layout) if kind == "buffer"]

    for index, offer in zip(pet_indices, frozen_pets):
        slots[index] = offer

    remaining_pets = frozen_pets[len(pet_indices):]
    for index, offer in zip(reversed(food_indices), frozen_foods):
        slots[index] = offer

    remaining_foods = frozen_foods[len(food_indices):]
    free_buffers = [index for index in buffer_indices if slots[index] is None]
    for index, offer in zip(free_buffers, remaining_pets):
        slots[index] = offer
    free_buffers = [index for index in buffer_indices if slots[index] is None]
    for index, offer in zip(reversed(free_buffers), remaining_foods):
        slots[index] = offer

