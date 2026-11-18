"""Where the engine's places and the houses' estates sit on the 3D island (all PROPOSED).

The world engine knows places by name ("the summit", "the Theren hills"); the 3D island
(site/world) knows metres. This file is the bridge: one position per place, in the island's own
coordinates (x east, z south, metres; Corva's quay is near x = 0, z = 0; north is -z). Nothing here
is a decision by Danny: every position is marked PROPOSED in the sandbox tables, to be moved.

Two ways of saying where something is:
  * inside Corva, by (s, z): s metres inland from the shore line at z, the same coordinates the
    city layout uses (site/world/js/world/layout.js: at(s, z) = (coastX(z) - s, z)). Corva is
    small: the quay to the summit is about 120 m, the city runs ~150 m along the shore;
  * out on the island, by (x, z) directly, read off the island's features (villages, the peak).

Estates have a radius: a town house is a few metres, a landed estate in the hills a few hundred.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "site/world/assets/island/features-1717.json"
PEAK = (-4100, 600)        # the central mountain (terrain.js PEAK)


def coast_x(z: float) -> float:
    """The shore line of Corva's bay at z (a copy of terrain.js coastX)."""
    import math
    return 10 + (0.0028 if z > 0 else 0.0011) * z * z - 6 * math.sin(z / 37)


def city(s: float, z: float) -> tuple[float, float]:
    """A point s metres inland from Corva's shore at z."""
    return (round(coast_x(z) - s, 1), z)


def villages() -> dict[str, tuple[float, float]]:
    f = json.loads(FEATURES.read_text())
    return {v["name"]: (v["x"], v["z"]) for v in f["villages"]}


def place_positions() -> dict[str, tuple[float, float] | None]:
    """Place name -> (x, z), or None for places off the island (the mainland, the open sea)."""
    v = villages()
    P = {
        # Corva (PROPOSED: matched to the 3D city's quay, temples and summit)
        "the harbour": city(4, 12),
        "the sea temple": city(13, -38),             # the columned temple on the quay
        "the market": city(42, 4),
        "the terraces": city(72, -36),
        "the council hall": city(16, 22),            # the long colonnade on the quay
        "the summit": city(118, -14),                # the summit temple and citadel hill
        "the western gate": city(165, 4),            # where the city ends inland
        "the north shore shipyards": city(6, -165),
        # the island
        "the quarries": (-420, -520),                # the north ridge behind the city
        "the Theren hills": (-1650, 520),            # olive terraces between Corva and Melissa
        "Mount Aetos": PEAK,
        "the mountain sheepfolds": (PEAK[0] + 520, PEAK[1] - 380),
        "the northern road": (-900, -1150),          # the road north out of Corva
        "the north coast coves": (-2600, -2650),
        **v,                                         # Elaia, Ampelos, Kryoneri, Platanos, Melissa
        # off the island: not drawn as places (the horizon islands stand in for them)
        "the eastern islands": None, "the mainland": None, "the open sea": None,
    }
    # the houses' seats
    P.update({
        "the Corvane house on the summit": city(126, 6),
        "the Valerius house above the shipyards": city(38, -150),
        "the Theren farmhouse in the hills": (-1720, 470),
        "the Marcellan counting house on the quay": city(9, 42),
        "the Cassian yard by the quarries": (-380, -470),
        "the hall of judgment": city(46, 20),
        "the Damaris house by the western gate": city(158, 22),
        "the Veyra steadings on the mountain": (PEAK[0] + 420, PEAK[1] - 260),
        "the Solenne house in the upper city": city(98, -52),
    })
    return P


# Each house's estate: the land it holds, as a centre and radius (PROPOSED), and its lantern colour.
# The centre is usually the seat; the radius says how far its land reaches.
ESTATES = {
    "Corvane":   {"at": city(124, -4), "r": 40, "color": "#e8b34a"},     # the upper city and citadel hill
    "Valerius":  {"at": city(24, -150), "r": 70, "color": "#4f9fe0"},    # shipyards along the north shore
    "Theren":    {"at": (-1700, 480), "r": 520, "color": "#8fbf5a"},     # olive and vineyard land in the hills
    "Aurelian":  {"at": city(90, -30), "r": 35, "color": "#f2ede0"},     # the temple lands below the summit
    "Marcellan": {"at": city(8, 30), "r": 35, "color": "#d9783a"},       # warehouses and wharves
    "Cassian":   {"at": (-420, -500), "r": 260, "color": "#a3998c"},     # the quarries on the north ridge
    "Severin":   {"at": city(46, 18), "r": 20, "color": "#9a6ad6"},      # a hall and gardens by the market
    "Damaris":   {"at": city(158, 22), "r": 22, "color": "#4fc0a8"},     # house and herb gardens by the gate
    "Veyra":     {"at": (PEAK[0] + 300, PEAK[1] - 150), "r": 900, "color": "#c0503e"},  # pastures on Mount Aetos
    "Solenne":   {"at": city(98, -52), "r": 10, "color": "#d68fb0"},     # one old house in the upper city
}
