"""Give everyone already in the world their traits, appearance and bio (run once, after traits were introduced).

    python -m world.backfill_people traits       # traits for all (seed-fixed for the eight), derived numbers recomputed
    python -m world.backfill_people appearance   # appearance drafts for the eight seed characters (inherited where possible)
    python -m world.backfill_people bios         # a bio and an appearance description for everyone (the instruct models)

Re-runnable: traits and appearance are only made for people who have none; bios only for people without one
(or with --redo, for proposed ones). Everything made here is PROPOSED, except what the seed story states about the
eight seed characters (docs/seed_history.md), which is fixed (traits.seed_fixed lists it).
"""

from __future__ import annotations

import json
import random
import sys

from world import traits as TR
from world.db import connect, rows

# The eight seed characters. Fixed: what docs/seed_history.md (and Danny's summary of it) states. The rest of each
# record is filled in like everyone else's (seed_fixed names the fixed parts).
SEED = {
    "Livia Corvane": {"humors": {"sanguine": 0.42, "choleric": 0.3, "melancholic": 0.15, "phlegmatic": 0.13},
                      "values": {"love": 0.9, "family": 0.3, "honor": 0.3, "ambition": 0.55, "faith": 0.3, "wealth": 0.2},
                      "quirks": ["headstrong"], "seed_fixed": ["clever", "spirited", "defiant: unwilling to be a bargaining piece"]},
    "Lucan Valerius": {"humors": {"choleric": 0.45, "phlegmatic": 0.4, "sanguine": 0.1, "melancholic": 0.05},
                       "values": {"honor": 0.95, "family": 0.8, "ambition": 0.6, "faith": 0.5, "love": 0.3, "wealth": 0.4},
                       "quirks": ["keeps every promise"],
                       "seed_fixed": ["proud", "disciplined", "dutiful", "neither cruel nor dishonorable"]},
    "Soren of the Harbor": {"humors": {"sanguine": 0.45, "choleric": 0.3, "phlegmatic": 0.15, "melancholic": 0.1},
                            "values": {"love": 0.9, "family": 0.75, "honor": 0.6, "ambition": 0.3, "faith": 0.3, "wealth": 0.1},
                            "quirks": ["keeps every promise"], "seed_fixed": ["courageous", "witty", "stubbornly loyal"]},
    "Marius Corvane": {"humors": {"choleric": 0.35, "melancholic": 0.3, "phlegmatic": 0.25, "sanguine": 0.1},
                       "values": {"honor": 0.9, "family": 0.7, "ambition": 0.6, "faith": 0.4, "love": 0.4, "wealth": 0.5},
                       "seed_fixed": ["aging"]},
    "Galen Theren": {"humors": {"phlegmatic": 0.4, "melancholic": 0.3, "sanguine": 0.2, "choleric": 0.1},
                     "values": {"family": 0.85, "love": 0.7, "honor": 0.6, "faith": 0.4, "ambition": 0.3, "wealth": 0.4},
                     "dispositions": {"suspicion": 0.55}, "quirks": ["keeps secrets"], "seed_fixed": ["kind", "guarded"]},
    "Tiberon Theren": {"humors": {"choleric": 0.35, "melancholic": 0.35, "phlegmatic": 0.2, "sanguine": 0.1},
                       "values": {"family": 0.6, "honor": 0.65, "ambition": 0.6, "faith": 0.3, "love": 0.3, "wealth": 0.4},
                       "quirks": ["holds grudges"], "seed_fixed": ["resentful of Soren (never acted on it)"]},
    "Neria": {"humors": {"melancholic": 0.5, "phlegmatic": 0.25, "sanguine": 0.15, "choleric": 0.1},
              "values": {"love": 0.7, "faith": 0.5, "family": 0.5, "honor": 0.4, "ambition": 0.2, "wealth": 0.2},
              "dispositions": {"fear": 0.85}, "quirks": ["keeps secrets"], "seed_fixed": ["fearful of discovery"]},
    "Theodric Aurelian": {"seed_fixed": ["high priest of the sea temple"]},   # the seed says no more: the rest procedural
}


def do_traits(con) -> int:
    n = 0
    for p in rows(con, "select p.*, h.name house from people p left join house_members m on m.person_id = p.id "
                       "left join houses h on h.id = m.house_id order by p.id"):
        if p["traits"]:
            continue
        r = random.Random(f"traits-{p['id']}")
        t = TR.from_legacy(p, p["house"] or "Theren", r)
        s = SEED.get(p["name"])
        if s:
            if "humors" in s:
                t["humors"] = TR.norm(s["humors"])
            t["values"].update(s.get("values", {}))
            t["dispositions"].update(s.get("dispositions", {}))
            if "quirks" in s:
                t["quirks"] = s["quirks"]
            t["seed_fixed"] = s["seed_fixed"]
        TR.save(con, p["id"], t)
        n += 1
    con.commit()
    return n


def do_appearance(con) -> int:
    """The eight's appearance: drafted like everyone's (inherited hair and eyes from a parent where one is known),
    now that Danny has said he won't write them; seed facts kept (ages, Soren's sea life, Marius aging)."""
    import yaml
    from world.appearance import PATH, draft_one, load_yaml
    have = load_yaml()
    year = rows(con, "select max(year) y from storyteller_proposals")[0]["y"] or 0
    n = 0
    for name in [k for k, v in have.items() if v.get("status") == "danny" and not v.get("build")]:
        p = rows(con, "select p.*, m.role, h.name house from people p join house_members m on m.person_id = p.id "
                      "join houses h on h.id = m.house_id where p.name = ?", name)[0]
        par = rows(con, "select l.parent_id from lineage l where l.child_id = ?", p["id"])
        parent = None
        for x in par:
            q = rows(con, "select name from people where id = ?", x["parent_id"])[0]["name"]
            if q in have and have[q].get("natural_hair"):
                parent = {"hair_colour": have[q]["natural_hair"], "eye_colour": have[q].get("eyes")}
        d = draft_one(p, p["house"], p["role"], year, parent)
        if name == "Soren of the Harbor":
            d["marks"] = "rope-burned hands and skin browned by sea wind; " + d["marks"]
            d["clothing"] = "a harbour pilot's sea-stained tunic and a short cloak, an olive-green Theren cord at the wrist (House Theren: olive green)"
        d["status"] = "proposed"
        have[name] = {**have[name], **d}
        n += 1
    text = PATH.read_text()
    header = "".join(l for l in text.splitlines(True) if l.startswith("#"))
    PATH.write_text(header + "\n" + yaml.safe_dump(have, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    return n


if __name__ == "__main__":
    con = connect()
    what = sys.argv[1]
    if what == "traits":
        print(f"traits for {do_traits(con)} people")
    elif what == "appearance":
        print(f"appearance drafted for {do_appearance(con)} seed characters")
    elif what == "bios":
        from world.bios import backfill
        backfill(con, redo="--redo" in sys.argv)
