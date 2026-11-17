"""Place every dream as a star, and find the first constellations.

1. UMAP squeezes the 384-dimensional embeddings down to 2 dimensions while
   keeping neighbours neighbours: dreams that were close in meaning-space end
   up close on the page. (It is a map, not a measurement: distances between
   far-apart groups mean little, closeness within a group means a lot.)
2. K-means groups the 2D points into clusters: the early constellations.
3. Each constellation is named by its most characteristic symbols: images
   that are common inside it and rarer outside ("lift"), e.g. "sea · ship · shore".

A new dream (the daily job) is not re-mapped with UMAP; it is placed among its
nearest neighbours in embedding space (place_new), so the sky stays stable
from day to day. Re-run the full layout (daily/memory_sync.py) now and then.
"""

from __future__ import annotations

import math
import random
from collections import Counter

SEED = 42


def layout(vectors):
    """(n, 2) positions in 0.05..0.95 from (n, 384) unit vectors."""
    import numpy as np
    import umap

    n = len(vectors)
    reducer = umap.UMAP(n_neighbors=min(15, max(2, n - 1)), min_dist=0.35, metric="cosine", random_state=SEED)
    xy = reducer.fit_transform(vectors)
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    return 0.05 + 0.9 * (xy - lo) / np.maximum(hi - lo, 1e-9)


def clusters(xy, k: int | None = None):
    """Cluster label per star. k defaults to about sqrt(n/3), at least 3."""
    from sklearn.cluster import KMeans

    k = k or max(3, round(math.sqrt(len(xy) / 3)))
    return KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(xy)


def name_constellations(labels, symbols: list[dict[str, int]], xy, top: int = 3) -> list[dict]:
    """Label each cluster by the symbols with the highest lift (and at least 2 dreams in it)."""
    import numpy as np

    n = len(labels)
    overall = Counter(s for syms in symbols for s in syms)  # dreams mentioning each symbol
    out = []
    for c in sorted(set(labels.tolist())):
        idx = np.where(labels == c)[0]
        inside = Counter(s for i in idx for s in symbols[i])
        scored = []
        for sym, k in inside.items():
            if k < 2:
                continue
            lift = (k / len(idx)) / (overall[sym] / n)
            scored.append((lift * math.log1p(k), sym))
        names = [s for _, s in sorted(scored, reverse=True)[:top]] or [s for s, _ in inside.most_common(top)]
        cx, cy = xy[idx].mean(axis=0)
        out.append({"id": int(c), "label": " · ".join(names), "symbols": names, "x": float(cx), "y": float(cy),
                    "size": int(len(idx))})
    return out


def place_new(neighbours: list[dict], seed: int = 0) -> tuple[float, float, int | None]:
    """Position for a new star from its nearest dreams ([{sky_x, sky_y, constellation, similarity}]):
    a similarity-weighted average, nudged a little so stars never sit exactly on top of each other.
    Plain Python (no numpy), so the light daily publisher can run it."""
    rng = random.Random(seed)
    pts = [n for n in neighbours if n.get("sky_x") is not None]
    if not pts:
        return rng.uniform(0.1, 0.9), rng.uniform(0.1, 0.9), None
    w = [max(p["similarity"], 0.01) ** 2 for p in pts]
    x = sum(wi * p["sky_x"] for wi, p in zip(w, pts)) / sum(w)
    y = sum(wi * p["sky_y"] for wi, p in zip(w, pts)) / sum(w)
    x, y = (min(0.97, max(0.03, v + rng.gauss(0, 0.012))) for v in (x, y))
    votes = Counter(p["constellation"] for p in pts[:5] if p.get("constellation") is not None)
    return x, y, (votes.most_common(1)[0][0] if votes else None)
