from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIKI_ROOT = PROJECT_ROOT / "sap_wiki"
SUMMARY_PATHS = {
    "pets": WIKI_ROOT / "pets_summary.txt",
    "foods": WIKI_ROOT / "foods_summary.txt",
    "tokens": WIKI_ROOT / "tokens_summary.txt",
}
DATA_DUMP_ROOT = WIKI_ROOT / "superautopets_wiki_dump"
ICON_ROOTS = {
    "pets": DATA_DUMP_ROOT / "icons" / "pets",
    "foods": DATA_DUMP_ROOT / "icons" / "foods",
    "tokens": DATA_DUMP_ROOT / "icons" / "tokens",
}

PETS_BY_TIER = {
    1: ("Duck", "Beaver", "Pigeon", "Otter", "Pig", "Ant", "Mosquito", "Fish", "Cricket", "Horse"),
    2: ("Snail", "Crab", "Swan", "Rat", "Hedgehog", "Peacock", "Flamingo", "Worm", "Kangaroo", "Spider"),
    3: ("Dodo", "Badger", "Dolphin", "Giraffe", "Elephant", "Camel", "Rabbit", "Ox", "Dog", "Sheep"),
    4: ("Skunk", "Hippo", "Bison", "Blowfish", "Turtle", "Squirrel", "Penguin", "Deer", "Whale", "Parrot"),
    5: ("Scorpion", "Crocodile", "Rhino", "Monkey", "Armadillo", "Cow", "Seal", "Rooster", "Shark", "Turkey"),
    6: ("Leopard", "Boar", "Tiger", "Wolverine", "Gorilla", "Dragon", "Mammoth", "Cat", "Snake", "Fly"),
}

FOODS_BY_TIER = {
    1: ("Apple", "Honey"),
    2: ("Sleeping Pill", "Meat Bone", "Cupcake"),
    3: ("Garlic", "Salad Bowl", "Cake"),
    4: ("Bread", "Canned Food", "Pear"),
    5: ("Chili", "Chocolate", "Sushi"),
    6: ("Steak", "Melon", "Mushroom", "Pizza"),
}

TOKEN_NAMES = (
    "Bread Crumbs",
    "Zombie Cricket",
    "Dirty Rat",
    "Better Apple",
    "Best Apple",
    "Ram",
    "Bus",
    "Peanut",
    "Milk",
    "Better Milk",
    "Best Milk",
    "Coconut",
    "Zombie Fly",
)

SHOP_SLOT_LAYOUT = ("pet", "pet", "pet", "pet", "pet", "buffer", "buffer", "food", "food")


def safe_asset_name(name: str) -> str:
    return name.replace(" ", "_")


def icon_path(kind: str, name: str) -> Path:
    return ICON_ROOTS[kind] / f"{safe_asset_name(name)}.png"


def unlock_tier_for_turn(turn: int) -> int:
    return max(1, min(6, (turn + 1) // 2))


def initial_lives_for_player_count(player_count: int) -> int:
    return 6 if player_count == 2 else 5


def ordered_names_by_tier(mapping: dict[int, tuple[str, ...]]) -> tuple[str, ...]:
    ordered: list[str] = []
    for tier in sorted(mapping):
        ordered.extend(mapping[tier])
    return tuple(ordered)


ALL_PET_NAMES = ordered_names_by_tier(PETS_BY_TIER)
ALL_FOOD_NAMES = ordered_names_by_tier(FOODS_BY_TIER)


def tier_for_name(name: str, mapping: dict[int, tuple[str, ...]]) -> int | None:
    for tier, names in mapping.items():
        if name in names:
            return tier
    return None


def shop_slot_layout_for_turn(turn: int) -> tuple[str, ...]:
    if turn >= 9:
        pet_slots, food_slots = 5, 2
    elif turn >= 5:
        pet_slots, food_slots = 4, 2
    else:
        pet_slots, food_slots = 3, 1
    buffer_slots = 9 - pet_slots - food_slots
    return ("pet",) * pet_slots + ("buffer",) * buffer_slots + ("food",) * food_slots
