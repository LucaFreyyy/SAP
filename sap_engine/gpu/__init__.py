"""GPU-facing abstractions for a future batched simulator."""

from dataclasses import dataclass
from typing import Protocol


class BatchGameState(Protocol):
    """Protocol for batched state backends such as PyTorch or JAX."""


@dataclass(slots=True)
class GpuGameEngine:
    backend: str = "torch"

    def simulate_batch(self, state: BatchGameState) -> BatchGameState:
        return state
