"""How new is a dream? Used to choose the morning's dream (daily/morning_job.py).

Choosing works in two stages:

  1. A FLOOR. Coherence (the editor's 1-10 rating of whether a dream holds one
     thread) only has to clear COHERENCE_FLOOR. It no longer decides the winner:
     a perfectly coherent dream that repeats last week is worse than a strange one.
  2. NOVELTY decides, with luck. Each dream that clears the floor gets
        novelty = how far its embedding is from the last ~30 chosen dreams
                + a bonus for symbols (images) never or rarely seen before
     and the winner is drawn at random with weight exp(novelty / TEMPERATURE),
     so the strangest dreams win often but not always.

Every number is logged in the day's record (candidate fields + "selection"), so
the knobs below can be tuned from real mornings.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

COHERENCE_FLOOR = 4.4    # the editor's 1-10 rating; ~ the top third of candidates (Nov 2026 runs)
MIN_ELIGIBLE = 3         # if fewer clear the floor, the top 3 by coherence go through anyway
RECENT = 30              # compare against this many recent chosen dreams
NEIGHBOURS = 3           # embedding novelty = 1 - mean similarity to the 3 closest of them
NEW_SYMBOL = 0.12        # bonus per image never seen in Arcadia's memory
RARE_SYMBOL = 0.04       # bonus per image seen in <= RARE_MAX dreams
RARE_MAX = 3
SYMBOL_CAP = 0.30
TEMPERATURE = 0.05       # lower = the most novel dream wins more surely; higher = more even odds


def recent_chosen(before_day: str, n: int = RECENT) -> list[str]:
    """Texts of the last n chosen morning dreams before `before_day` (from the committed records)."""
    rows = []
    for path in sorted((ROOT / "daily/mornings").glob("*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        if r["day"] < before_day:
            rows.append(r.get("as_remembered") or r["raw"])
    return rows[-n:]


def symbol_counts() -> Counter:
    """In how many remembered dreams each symbol appears (every dream the repo knows of)."""
    from engine.memory.collect import all_dreams
    from engine.memory.symbols import extract

    counts: Counter = Counter()
    for d in all_dreams():
        counts.update(extract(d.get("remembered") or d["text"]).keys())
    return counts


def score_novelty(candidates: list[dict], day: str, device: str = "cpu") -> dict:
    """Adds emb_novelty, new_symbols, rare_symbols, symbol_bonus and novelty to each candidate.
    Returns a summary for the log. If the embedding model is unavailable, novelty is symbols only."""
    from engine.memory.symbols import extract

    reference = recent_chosen(day)
    reference_kind = "recent chosen dreams"
    if len(reference) < NEIGHBOURS:  # early days: compare against everything remembered so far
        from engine.memory.collect import all_dreams

        reference = [d.get("remembered") or d["text"] for d in all_dreams() if (d.get("day") or "") < day]
        reference_kind = "all remembered dreams (fewer than 3 chosen so far)"
    counts = symbol_counts()

    emb_ok = True
    try:
        from engine.memory.embed import embed

        cand_vecs = embed([c["text"] for c in candidates], device=device)
        ref_vecs = embed(reference, device=device) if reference else None
    except Exception as err:  # noqa: BLE001
        emb_ok, reason = False, f"{type(err).__name__}: {err}"

    for k, c in enumerate(candidates):
        if emb_ok and ref_vecs is not None and len(ref_vecs):
            sims = sorted((float(v) for v in ref_vecs @ cand_vecs[k]), reverse=True)[:NEIGHBOURS]
            c["emb_novelty"] = round(1 - sum(sims) / len(sims), 4)
        else:
            c["emb_novelty"] = 0.0
        syms = extract(c["text"]).keys()
        c["new_symbols"] = sorted(s for s in syms if counts[s] == 0)
        c["rare_symbols"] = sorted(s for s in syms if 0 < counts[s] <= RARE_MAX)
        c["symbol_bonus"] = round(min(SYMBOL_CAP, NEW_SYMBOL * len(c["new_symbols"]) + RARE_SYMBOL * len(c["rare_symbols"])), 4)
        c["novelty"] = round(c["emb_novelty"] + c["symbol_bonus"], 4)
    return {"reference": reference_kind, "reference_size": len(reference),
            "embeddings": "ok" if emb_ok else f"unavailable ({reason}); novelty from symbols only"}


def pick(eligible: list[dict], seed: int) -> tuple[dict, list[dict]]:
    """Weighted random draw: weight = exp(novelty / TEMPERATURE). Returns (winner, eligible ordered
    winner first, then by weight) and writes each candidate's weight and chance into it."""
    top = max(c["novelty"] for c in eligible)
    weights = [math.exp((c["novelty"] - top) / TEMPERATURE) for c in eligible]  # minus top: no overflow
    total = sum(weights)
    for c, w in zip(eligible, weights):
        c["chance"] = round(w / total, 4)
    rng = random.Random(f"pick-{seed}")
    winner = rng.choices(eligible, weights=weights, k=1)[0]
    rest = sorted((c for c in eligible if c is not winner), key=lambda c: -c["chance"])
    return winner, [winner, *rest]
