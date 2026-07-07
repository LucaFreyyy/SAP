from __future__ import annotations

import random
from typing import Sequence, TypeVar

T = TypeVar("T")


class SeededRNG:
    """Thin wrapper around random.Random so the core engine can swap to GPU RNG later."""

    def __init__(self, seed: int | None = None) -> None:
        self._random = random.Random(seed)
        self.seed = seed

    def randint(self, start: int, end: int) -> int:
        return self._random.randint(start, end)

    def choice(self, values: Sequence[T]) -> T:
        return self._random.choice(list(values))

    def sample(self, values: Sequence[T], count: int) -> list[T]:
        return self._random.sample(list(values), count)

    def shuffle(self, values: list[T]) -> None:
        self._random.shuffle(values)

    def random(self) -> float:
        return self._random.random()

    def weighted_choice(self, values: Sequence[T], weights: Sequence[float]) -> T:
        selected = self._random.choices(list(values), weights=list(weights), k=1)
        return selected[0]
