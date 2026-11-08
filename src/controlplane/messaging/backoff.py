from __future__ import annotations

import random

_rng = random.SystemRandom()


def backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with jitter. attempt is 1-based."""
    ceiling = min(cap, base * (2 ** (attempt - 1)))
    return _rng.uniform(ceiling / 2, ceiling)
