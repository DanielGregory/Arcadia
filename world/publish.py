"""Publish the sandbox world (local SQLite) to Supabase's sandbox_* tables, for the site to read.

    python -m world.publish              # replace the snapshot with the sandbox as it is now
    python -m world.publish --dry_run    # build it and print the counts, upload nothing

The site's sandbox modes read ONLY these tables: the 3D island (/world/?world=sandbox), the review
page's Chronicle tab, the sandbox Sky and the wallpaper preview. This script is the engine's only
way out: the site never writes to them (the publishable key may only read them).

What leaves the sandbox, and what never does:
  * houses, places (with their PROPOSED positions on the island, world/placements.py), people with
    where they are now, events, beliefs, dreams, clients, chronicles, vital signs: published;
  * sealed_facts, memories (the private truths live there), sealed events and every event's facts
    column: never;
  * the absent (Livia and Soren): published without a place. Where they are is sealed;
  * anything said by someone who privately knows where the lovers are, if it names that place:
    held back (it would be them giving the secret away, which only the engine may decide by an event).
The check runs without ever printing the sealed place.

Dream stars: every dream of the sandbox is embedded (all-MiniLM-L6-v2, like the production Sky)
and laid out by meaning with UMAP, so similar dreams sit together; each star keeps its dreamer
and house.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daily"))

from world.db import connect, one, rows  # noqa: E402
from world.placements import ESTATES, place_positions  # noqa: E402

# Tables in the order they are cleared and refilled, with the column that every row has (for
# PostgREST's "delete where <col> is not null", which is how it deletes all rows).
TABLES = [("sandbox_places", "id"), ("sandbox_houses", "id"), ("sandbox_people", "id"), ("sandbox_events", "id"),
          ("sandbox_beliefs", "id"), ("sandbox_dreams", "id"), ("sandbox_house_clients", "id"),
          ("sandbox_chronicles", "id"), ("sandbox_house_feelings", "from_house"), ("sandbox_vital_signs", "year"),
          ("sandbox_portrait_candidates", "id"), ("sandbox_lineage", "id"), ("sandbox_relationships", "id"), ("sandbox_legends", "id"), ("sandbox_symbols", "symbol"),
          ("sandbox_world", "id")]
PUBLIC_TIES = ("spouse", "betrothed", "kin", "friend", "rival", "teacher")   # never 'lover' (the Codex shows only public ties)


# --- the secret, guarded ---------------------------------------------------------------------------------
def secret_guard(con):
    """A function that says whether a text from a given author would give the sealed place away.

    Only people who privately know (a private memory naming the place) can give it away; anyone else
    naming that place is guessing, and a guess is a belief, which is fine to show."""
    s = one(con, "select value from sealed_facts where key = 'lovers_location'")
    if not s:
        return lambda author, text: False
    place = one(con, "select name from places where id = ?", json.loads(s["value"])["place_id"])
    name = (place or {}).get("name", "").lower()
    bare = name.removeprefix("the ")
    knowers = {m["person_id"] for m in rows(con, "select person_id, text from memories where private = 1")
               if name and bare in m["text"].lower()}

    def leaks(author, text):
        return bool(name) and author in knowers and bare in (text or "").lower()
    return leaks


# --- dream stars ---------------------------------------------------------------------------------------------
def star_positions(dreams: list[dict]) -> dict[str, tuple[float, float]]:
    """(x, y) in 0.05..0.95 per dream id, by meaning (embeddings + UMAP), as in the production Sky."""
    if len(dreams) < 4:
        return {d["id"]: (0.5, 0.5) for d in dreams}
    from engine.memory.embed import embed
    from engine.memory.sky import layout
    vecs = embed([d["text"] for d in dreams])
    xy = layout(vecs)
    return {d["id"]: (round(float(x), 4), round(float(y), 4)) for d, (x, y) in zip(dreams, xy)}


# --- the snapshot ----------------------------------------------------------------------------------------------
def build(con) -> dict[str, list[dict]]:
    leaks = secret_guard(con)
    held_back = 0
    clock = one(con, "select year, season, max(tick) tick from storyteller_proposals")
    pos = place_positions()

    places = []
    for p in rows(con, "select id, name, kind, parent_id from places"):
        xz = pos.get(p["name"])
        places.append({**p, "x": xz[0] if xz else None, "z": xz[1] if xz else None, "placement_proposed": True})

    houses = []
    for h in rows(con, "select id, name, claim, land, land_kind, seat_place_id, head_id, food, goods, materials, proposed from houses"):
        e = ESTATES.get(h["name"], {})
        at = e.get("at")
        houses.append({**h, "proposed": bool(h["proposed"]), "color": e.get("color"),
                       "estate_x": at[0] if at else None, "estate_z": at[1] if at else None,
                       "estate_radius": e.get("r"), "estate_proposed": True})

    from world.portraits import sex_of
    people = [{**p, "alive": bool(p["alive"]), "absent": bool(p["absent"]), "proposed": bool(p["proposed"]),
               "place_id": None if p["absent"] else p["place_id"], "sex": p["sex"] or sex_of(p["name"]),
               "appearance": json.loads(p["appearance"]) if p["appearance"] else None}
              for p in rows(con, "select p.id, p.name, p.tier, m.house_id, m.role, p.place_id, p.alive, p.absent, p.proposed, "
                                 "p.dream_temperament, p.born_year, p.note, p.sex, p.portrait, p.portrait_ref, p.appearance from people p "
                                 "left join house_members m on m.person_id = p.id and m.left_year is null")]
    house_of = {p["id"]: p["house_id"] for p in people}

    events = [{**e, "actors": json.loads(e["actors"]), "houses": json.loads(e["houses"])}
              for e in rows(con, "select id, year, season, kind, place_id, actors, houses, outcome, text from events where sealed = 0")]

    beliefs = []
    for b in rows(con, "select b.id, b.year, b.season, b.holder_id, b.subject_type, b.subject_id, b.interpretation, b.confidence, "
                       "b.source_type, b.about_house, b.stance from beliefs b join people p on p.id = b.holder_id where p.absent = 0"):
        if leaks(b["holder_id"], b["interpretation"]):
            held_back += 1
            continue
        beliefs.append(b)

    dreams = rows(con, "select id, year, season, dreamer_id, tag, text, recalled, shared_with from dreams order by id")
    interp = {r["subject_id"]: r["n"] for r in rows(con, "select subject_id, count(distinct holder_id) n from beliefs "
                                                         "where subject_type = 'dream' group by subject_id")}
    told = {}
    for m in rows(con, "select source_id, person_id, text from memories where source_type = 'dream' and private = 0 "
                       "and text like '(as told)%' and told_by is null order by id"):
        if not leaks(m["person_id"], m["text"]):
            told.setdefault(m["source_id"], m["text"][len("(as told) "):])
    stars = star_positions(dreams)
    out_dreams = []
    for d in dreams:
        shared = json.loads(d["shared_with"] or "[]")
        x, y = stars[d["id"]]
        out_dreams.append({**d, "recalled": bool(d["recalled"]), "shared_with": shared, "house_id": house_of.get(d["dreamer_id"]),
                           "discussed": len(shared) + interp.get(d["id"], 0), "retelling": told.get(d["id"]),
                           "sky_x": x, "sky_y": y})

    clients = rows(con, "select id, year, season, house_id, count, loyalty, gained, lost from house_clients")

    chronicles = []
    for c in rows(con, "select id, year, season, author_id, kind, text, title from chronicles"):
        if leaks(c["author_id"], c["text"]):
            held_back += 1
            continue
        chronicles.append(c)
    # before the chroniclers (seasons 1 to 3): each season's or year's whole chronicle, as an unsigned entry
    have = {(c["year"], c["kind"]) for c in chronicles if c["kind"] == "chronicle"}
    for md in sorted((ROOT / "docs").glob("chronicle_*.md")):
        y = None
        if md.stem.startswith("chronicle_year"):
            y = int(md.stem.removeprefix("chronicle_year"))
        elif md.stem.startswith("chronicle_season"):
            y = {1: 0, 2: 1, 3: 1}.get(int(md.stem.removeprefix("chronicle_season")))
        if y is not None and (y, "chronicle") not in have:
            chronicles.append({"id": 1_000_000 + len(chronicles), "year": y, "season": None, "author_id": None, "kind": "chronicle",
                               "title": "The engine's chronicle (before the chroniclers)", "text": md.read_text(encoding="utf-8")})

    feelings = [{**f, "feeling": round(f["feeling"], 3)} for f in rows(
        con, "select m.house_id from_house, b.about_house to_house, sum(b.stance * b.confidence) / sum(b.confidence) feeling, "
             "count(*) beliefs from beliefs b join house_members m on m.person_id = b.holder_id and m.left_year is null "
             "where b.about_house is not null and b.stance is not null and b.confidence > 0 group by m.house_id, b.about_house")]

    vitals = [{**v, "stats": json.loads(v["stats"])} for v in rows(con, "select year, season, stats from vital_signs")]

    # for the Codex: family lines, public ties, the houses' legends, and the images that recur in dreams
    lineage = rows(con, "select id, parent_id, child_id, kind from lineage")
    ties = [r for r in rows(con, "select id, person_a, person_b, kind, strength from relationships") if r["kind"] in PUBLIC_TIES]
    legends = [{**l, "proposed": bool(l["proposed"])} for l in rows(con, "select id, house_id, title, text, proposed from legends")]
    from engine.memory.symbols import extract
    seen_sym = {}
    for d in dreams:
        for sym in extract(d["text"]):
            e = seen_sym.setdefault(sym, {"symbol": sym, "dreams": 0, "dream_ids": [], "first_year": d["year"], "first_season": d["season"]})
            e["dreams"] += 1
            e["dream_ids"].append(d["id"])
    symbols = sorted(seen_sym.values(), key=lambda e: -e["dreams"])

    print(f"held back {held_back} item(s) that would have named the sealed place")
    return {"sandbox_places": places, "sandbox_houses": houses, "sandbox_people": people, "sandbox_events": events,
            "sandbox_beliefs": beliefs, "sandbox_dreams": out_dreams, "sandbox_house_clients": clients,
            "sandbox_chronicles": chronicles, "sandbox_house_feelings": feelings, "sandbox_vital_signs": vitals,
            "sandbox_portrait_candidates": rows(con, "select id, person_id, k, seed, prompt, image, made_at from portrait_candidates"),
            "sandbox_lineage": lineage, "sandbox_relationships": ties, "sandbox_legends": legends, "sandbox_symbols": symbols,
            "sandbox_world": [{"id": 1, "year": clock["year"], "season": clock["season"], "tick": clock["tick"]}]}


def upload(snapshot: dict[str, list[dict]]) -> None:
    from memory_sync import client
    sb = client()
    for table, col in TABLES:      # clear everything first, then refill: the snapshot replaces the old one
        sb.session.delete(f"{sb.url}/rest/v1/{table}?{col}=not.is.null", timeout=60).raise_for_status()
    for table, _ in TABLES:
        data = snapshot[table]
        for i in range(0, len(data), 500):
            r = sb.session.post(f"{sb.url}/rest/v1/{table}", json=data[i:i + 500],
                                headers={"Prefer": "return=minimal", "Content-Type": "application/json"}, timeout=120)
            if r.status_code >= 300:
                sys.exit(f"{table}: {r.status_code} {r.text[:300]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry_run", action="store_true")
    ap.add_argument("--db", type=Path, help="another sandbox file (default data/world/sandbox.db)")
    args = ap.parse_args()
    con = connect(args.db) if args.db else connect()
    snap = build(con)
    for t, data in snap.items():
        print(f"  {t:24s} {len(data):5d} rows")
    if not args.dry_run:
        upload(snap)
        print("published")


if __name__ == "__main__":
    main()
