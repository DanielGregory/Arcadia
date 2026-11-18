"""Phase 2: put every dream into Arcadia's memory (Supabase + pgvector) and lay out the Sky.

    python daily/memory_sync.py              # full rebuild: collect, embed, symbols, UMAP sky, constellations
    python daily/memory_sync.py --dry_run    # do everything but upload
    python daily/memory_sync.py --similar "a ship on the stairs of the temple"   # search the memory

Full rebuild (run it now and then; it re-draws the whole sky):
  1. collect every dream (engine/memory/collect.py)
  2. embed each one on the CPU (engine/memory/embed.py, all-MiniLM-L6-v2)
  3. extract its symbols (engine/memory/symbols.py)
  4. UMAP the embeddings into the 2D sky and name the constellations (engine/memory/sky.py)
  5. upsert the world tables dreams / symbols / symbol_occurrences, and sky_constellations

Daily (add_dreams, called by daily/morning.py after the wallpaper is published):
each new dream arrives already embedded (the Kaggle job did it) and is placed
among its nearest neighbours, so the sky doesn't reshuffle every morning.

Needs SUPABASE_SECRET_KEY (environment or .env), like the other daily scripts.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daily"))
from engine.memory.embed import to_pg  # noqa: E402
from engine.memory.symbols import extract  # noqa: E402
from upload_review import DEFAULT_URL, Supabase, load_env  # noqa: E402

DREAM_COLUMNS = ("id", "run", "kind", "tag", "prompt", "text", "remembered", "day")


def client(dry_run: bool = False) -> Supabase:
    load_env()
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not key and not dry_run:
        sys.exit("SUPABASE_SECRET_KEY is not set (put it in .env)")
    return Supabase(os.environ.get("SUPABASE_URL", DEFAULT_URL), key or "", dry_run)


def rpc(sb: Supabase, name: str, args: dict) -> list[dict]:
    r = sb.session.post(f"{sb.url}/rest/v1/rpc/{name}", json=args, timeout=60)
    r.raise_for_status()
    return r.json()


def select(sb: Supabase, query: str) -> list[dict]:
    """Every row of a query, paging through Supabase's 1000-rows-per-request limit."""
    rows = []
    while True:
        r = sb.session.get(f"{sb.url}/rest/v1/{query}", headers={"Range": f"{len(rows)}-{len(rows) + 999}"}, timeout=60)
        r.raise_for_status()
        page = r.json()
        rows += page
        if len(page) < 1000:
            return rows


def delete_all(sb: Supabase, table: str, column: str) -> None:
    if sb.dry_run:
        return
    sb.session.delete(f"{sb.url}/rest/v1/{table}?{column}=not.is.null", timeout=60).raise_for_status()


def upload_symbols(sb: Supabase, dream_symbols: dict[str, dict[str, int]]) -> None:
    """Upsert each dream's symbols (world tables `symbols` and `symbol_occurrences`), then recompute
    each symbol's totals (frequency = mentions, dreams = dreams it appears in)."""
    rows = [(d, s, n) for d, syms in dream_symbols.items() for s, n in syms.items()]
    labels = sorted({s for _, s, _ in rows})
    first = {}
    for d, s, _ in rows:
        first.setdefault(s, d)
    if sb.dry_run:
        print(f"  would upsert {len(labels)} symbols and {len(rows)} occurrences")
        return
    known = {r["label"]: r for r in select(sb, "symbols?select=id,label,first_seen_dream")}
    new = [{"label": s, "first_seen_dream": first[s]} for s in labels if s not in known]
    if new:
        sb.upsert("symbols", new, on_conflict="label")
        known = {r["label"]: r for r in select(sb, "symbols?select=id,label,first_seen_dream")}
    sb.upsert("symbol_occurrences", [{"symbol_id": known[s]["id"], "dream_id": d, "mentions": n} for d, s, n in rows],
              on_conflict="symbol_id,dream_id")
    links = select(sb, "symbol_occurrences?select=symbol_id,mentions&dream_id=not.is.null")
    dreams, mentions = Counter(), Counter()
    for r in links:
        dreams[r["symbol_id"]] += 1
        mentions[r["symbol_id"]] += r["mentions"]
    sb.upsert("symbols", [{"label": r["label"], "dreams": dreams[r["id"]], "frequency": mentions[r["id"]]}
                          for r in known.values()], on_conflict="label")


def rebuild(dry_run: bool) -> None:
    import numpy as np

    from engine.memory.collect import all_dreams
    from engine.memory.embed import embed
    from engine.memory.sky import clusters, layout, name_constellations

    dreams = all_dreams()
    print(f"{len(dreams)} dreams: {dict(Counter(d['kind'] for d in dreams))}")
    vecs = embed([d["text"] for d in dreams])
    symbols = [extract(d["remembered"] or d["text"]) for d in dreams]
    xy = layout(np.asarray(vecs))
    labels = clusters(xy)
    constellations = name_constellations(labels, symbols, xy)
    for c in constellations:
        print(f"  constellation {c['id']}: {c['label']:<34} {c['size']:3d} stars")
    top = Counter(s for syms in symbols for s in syms).most_common(12)
    print("most common symbols:", ", ".join(f"{s} {n}" for s, n in top))

    sb = client(dry_run)
    rows = [{**{k: d.get(k) for k in DREAM_COLUMNS}, "embedding": to_pg(v), "sky_x": float(p[0]), "sky_y": float(p[1]),
             "constellation": int(c)} for d, v, p, c in zip(dreams, vecs, xy, labels)]
    for i in range(0, len(rows), 100):
        sb.upsert("dreams", rows[i:i + 100])
    upload_symbols(sb, {d["id"]: s for d, s in zip(dreams, symbols)})
    delete_all(sb, "sky_constellations", "id")
    sb.upsert("sky_constellations", constellations)
    print("dry run: nothing uploaded" if dry_run else f"uploaded {len(rows)} dreams to the memory")


def add_dreams(dreams: list[dict], sb: Supabase | None = None) -> None:
    """Add new dreams that already carry an 'embedding' (list of 384 floats), placing each in the sky
    among its nearest neighbours. Used by daily/morning.py."""
    from engine.memory.sky import place_new

    sb = sb or client()
    rows, syms = [], {}
    for k, d in enumerate(dreams):
        near = rpc(sb, "match_dreams", {"query_embedding": to_pg(d["embedding"]), "match_count": 6})
        near = [n for n in near if n["id"] != d["id"]]
        if near:
            pos = {r["id"]: r for r in select(sb, "dreams?select=id,sky_x,sky_y,constellation&id=in.("
                                                  + ",".join(f'"{n["id"]}"' for n in near) + ")")}
            for n in near:
                n.update(pos.get(n["id"], {}))
        x, y, c = place_new(near, seed=k)
        rows.append({**{key: d.get(key) for key in DREAM_COLUMNS}, "embedding": to_pg(d["embedding"]),
                     "sky_x": x, "sky_y": y, "constellation": c})
        syms[d["id"]] = d.get("symbols") or extract(d.get("remembered") or d["text"])
    sb.upsert("dreams", rows)
    upload_symbols(sb, syms)
    print(f"  memory: added {len(rows)} dreams to the sky")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--similar", help="print the dreams most similar to this text")
    parser.add_argument("-k", type=int, default=5)
    args = parser.parse_args()
    if args.similar:
        from engine.memory.embed import embed

        for m in rpc(client(), "match_dreams", {"query_embedding": to_pg(embed([args.similar])[0]), "match_count": args.k}):
            print(f"{m['similarity']:.3f}  {m['id']:<28} <{m['tag']}> {m['text'][:110]}")
        return
    rebuild(args.dry_run)


if __name__ == "__main__":
    main()
