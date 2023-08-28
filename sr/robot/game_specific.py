"""Game specific code."""
from __future__ import annotations

from typing import Iterable

# Marker sizes are in mm
MARKER_SIZES: dict[Iterable[int], int] = {
    range(100): 150,  # arena boundaries
    range(100, 200): 80,  # Everything else is a token
}
