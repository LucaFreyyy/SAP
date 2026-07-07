from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .models import FoodDefinition, PetDefinition, TokenDefinition
from .paths import ALL_FOOD_NAMES, ALL_PET_NAMES, FOODS_BY_TIER, PETS_BY_TIER, TOKEN_NAMES, SUMMARY_PATHS, icon_path, safe_asset_name, tier_for_name


def _parse_summary_entries(text: str, names: tuple[str, ...]) -> dict[str, str]:
    if not text.strip():
        return {}
    escaped_names = sorted((re.escape(name) for name in names), key=len, reverse=True)
    pattern = re.compile(rf"^(?P<name>{'|'.join(escaped_names)}):(?P<body>.*?)(?=^(?:{'|'.join(escaped_names)}):|\Z)", re.M | re.S)
    entries: dict[str, str] = {}
    for match in pattern.finditer(text):
        entries[match.group("name")] = match.group("body").strip()
    return entries


def _first_line_and_rest(content: str) -> tuple[str, str]:
    lines = content.splitlines()
    if not lines:
        return "", ""
    return lines[0].strip(), "\n".join(lines[1:]).strip()


def _parse_pet_entry(name: str, content: str) -> PetDefinition:
    first_line, rest = _first_line_and_rest(content)
    attack = 0
    health = 0
    if "/" in first_line:
        raw_attack, raw_health = first_line.split("/", 1)
        try:
            attack = int(raw_attack.strip())
            health = int(raw_health.strip())
        except ValueError:
            attack = 0
            health = 0
    ability_lines = tuple(line.strip() for line in rest.splitlines() if line.strip().startswith("level_"))
    tier = tier_for_name(name, PETS_BY_TIER) or 0
    return PetDefinition(
        name=name,
        tier=tier,
        attack=attack,
        health=health,
        ability_text=ability_lines,
        description=rest,
        icon_file=f"{safe_asset_name(name)}.png",
    )


def _parse_food_entry(name: str, content: str) -> FoodDefinition:
    first_line, rest = _first_line_and_rest(content)
    tier = tier_for_name(name, FOODS_BY_TIER) or 0
    return FoodDefinition(
        name=name,
        tier=tier,
        effect=first_line,
        description=rest,
        icon_file=f"{safe_asset_name(name)}.png",
    )


def _parse_token_entry(name: str, content: str) -> TokenDefinition:
    first_line, rest = _first_line_and_rest(content)
    return TokenDefinition(
        name=name,
        effect=first_line,
        description=rest,
        icon_file=f"{safe_asset_name(name)}.png",
    )


@dataclass(slots=True)
class DataRegistry:
    pets: dict[str, PetDefinition]
    foods: dict[str, FoodDefinition]
    tokens: dict[str, TokenDefinition]

    @classmethod
    def load(cls, root: Path | None = None) -> "DataRegistry":
        root = root or SUMMARY_PATHS["pets"].parent
        pets = _parse_summary_entries((root / "pets_summary.txt").read_text(encoding="utf-8"), ALL_PET_NAMES)
        foods = _parse_summary_entries((root / "foods_summary.txt").read_text(encoding="utf-8"), ALL_FOOD_NAMES)
        tokens = _parse_summary_entries((root / "tokens_summary.txt").read_text(encoding="utf-8"), TOKEN_NAMES)

        pet_defs = {name: _parse_pet_entry(name, body) for name, body in pets.items()}
        food_defs = {name: _parse_food_entry(name, body) for name, body in foods.items()}
        token_defs = {name: _parse_token_entry(name, body) for name, body in tokens.items()}
        return cls(pets=pet_defs, foods=food_defs, tokens=token_defs)

    def pet_pool(self, max_tier: int) -> list[PetDefinition]:
        return [pet for pet in self.pets.values() if pet.tier <= max_tier]

    def food_pool(self, max_tier: int) -> list[FoodDefinition]:
        return [food for food in self.foods.values() if food.tier <= max_tier]

    def pet_icon(self, name: str) -> Path:
        return icon_path("pets", name)

    def food_icon(self, name: str) -> Path:
        return icon_path("foods", name)

    def token_icon(self, name: str) -> Path:
        return icon_path("tokens", name)


def load_registry() -> DataRegistry:
    return DataRegistry.load()
