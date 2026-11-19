"""Bios: a 2-3 sentence life and a 1-2 sentence description of looks, written by the instruct model, for the Codex.

    python -m world.bios load        # adopt Danny's own bios from world/bios.yaml (they are never rewritten)
    python -m world.backfill_people bios [--redo]   # everyone without one (the backfill)

Written when someone is born, comes of age or is promoted (world/life.py queues them in bio_queue; the seasonal
tick writes the queue while the storyteller model is loaded), and once for everyone already in the world.

From: their traits (humours, values, quirks, and for the seed characters what the seed story fixes), their house
and role, their family, their public history (events they took part in), and their appearance record. Never from
private memories or sealed facts. The bio is checked like the chronicles: no out-of-world words, no wrong family
ties; a slip is asked again, and cut if it survives.

people.bio, people.bio_status ('proposed' | 'danny'), people.bio_occasion; the looks go into appearance.description.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from world.db import ROOT, rows

OVERRIDES = ROOT / "world/bios.yaml"

BIO_SYSTEM = (
    "You write entries for the Codex of Corva, an old island city of ten noble houses in an age of oars and sails, oil "
    "lamps, bronze and stone. Corva is its own world: no real places, peoples or gods, nothing modern. Given one person, "
    "write (1) a biography of 2 or 3 sentences: who they are, what they are like, what has marked their life; and (2) a "
    "description of their looks in 1 or 2 sentences, from their appearance record. Plain, vivid prose in the third "
    "person, like an old chronicler's notes: the biography at most 60 words, the looks at most 35 words, each ending on a "
    "full sentence. Use ONLY the facts given: never invent events, titles, relatives or secrets, get every family tie "
    "exactly as given, and do not repeat yourself. What is said of them is a report, not something they did. Show their "
    "nature in plain words (never the words sanguine, choleric, melancholic, phlegmatic, humour, or any numbers), and do not "
    "describe their looks in the biography.")
# looks first: once their appearance has been said, the biography is about their life, not their face
BIO_SCHEMA = {"type": "object", "properties": {"looks": {"type": "string", "maxLength": 300},
                                                "bio": {"type": "string", "maxLength": 480}},
              "required": ["looks", "bio"]}


def facts(con, pid: int, occasion: str) -> str:
    from world.traits import describe
    p = rows(con, "select p.*, m.role, h.name house from people p left join house_members m on m.person_id = p.id "
                  "left join houses h on h.id = m.house_id where p.id = ?", pid)[0]
    year = rows(con, "select max(year) y from storyteller_proposals")[0]["y"] or 0
    t = json.loads(p["traits"]) if p["traits"] else None
    a = json.loads(p["appearance"]) if p["appearance"] else {}
    name = lambda i: rows(con, "select name from people where id = ?", i)[0]["name"]
    parents = [name(r["parent_id"]) for r in rows(con, "select parent_id from lineage where child_id = ?", pid)]
    children = [name(r["child_id"]) for r in rows(con, "select child_id from lineage where parent_id = ?", pid)]
    spouse = [name(r["o"]) for r in rows(con, "select case when person_a = ? then person_b else person_a end o from relationships "
                                              "where kind = 'spouse' and (person_a = ? or person_b = ?)", pid, pid, pid)]
    events = [e["text"] for e in rows(con, "select text, actors from events where sealed = 0 order by id desc")
              if pid in json.loads(e["actors"])][:5]
    from world.portraits import sex_of
    pron = "she, her" if (p["sex"] or sex_of(p["name"])) == "f" else "he, him"
    lines = [f"Name: {p['name']} ({pron}). Age: {year - p['born_year']}. House {p['house'] or 'none'}, {p['role'] or ''}. "
             f"Standing: {'a principal of the city' if p['tier'] == 'principal' else 'a member of the household'}."
             + (" Missing from Corva since the autumn of year 0." if p["absent"] else "") + (" Dead." if not p["alive"] else ""),
             f"Their role, and what is said of them (a claim they made is only a claim): {p['note'] or 'little'}."]
    if t:
        plain = {"sanguine": "cheerful and bold", "choleric": "proud and quick to anger", "melancholic": "brooding and dreamy",
                 "phlegmatic": "calm and steady"}
        nature = describe(t)
        for k, v in plain.items():
            nature = nature.replace(k, v)
        lines.append(f"Their nature: {nature}.")
        if t.get("seed_fixed"):
            lines.append("Fixed parts of their nature (keep them true, in your own words): " + "; ".join(t["seed_fixed"]) + ".")
    lines.append("Family: " + "; ".join(x for x in (f"parents {', '.join(parents)}" if parents else "",
                                                    f"married to {', '.join(spouse)}" if spouse else "",
                                                    f"children {', '.join(children)}" if children else "") if x) + "."
                 if (parents or spouse or children) else "Family: none recorded.")
    if events:
        lines.append("What they have done or had done to them, newest first: " + " ".join(events))
    if a:
        lines.append("Appearance record: " + "; ".join(f"{k}: {a[k]}" for k in ("skin", "build", "face", "hair", "eyes", "marks", "clothing") if a.get(k)) + ".")
    lines.append(f"Written on the occasion of: {occasion}.")
    return "\n".join(lines)


def write_bio(con, llm, pid: int, occasion: str) -> dict | None:
    from world import anachronism
    from world.ties_check import Family, drop_wrong, rewrite_note, wrong_ties
    p = rows(con, "select name, bio_status, appearance from people where id = ?", pid)[0]
    if p["bio_status"] == "danny":
        return None
    user, fam, j = facts(con, pid, occasion), Family(con), {}
    for attempt in range(2):
        j = llm.json(BIO_SYSTEM, user, BIO_SCHEMA, max_new_tokens=220) or {}
        text = f"{j.get('bio', '')} {j.get('looks', '')}"
        bad, wrong = anachronism.find(text), wrong_ties(con, text, fam)
        if not bad and not wrong:
            break
        user += (rewrite_note(wrong) if wrong else "") + (f"\n(Write it again without: {', '.join(bad)}.)" if bad else "")
    from world.report import finish
    bio, looks = finish(str(j.get("bio") or "")), finish(str(j.get("looks") or ""))
    for word in ("sanguine", "choleric", "melancholic", "phlegmatic"):   # the humours' names, if any slipped through
        bio = re.sub(rf"[^.]*\b{word}\b[^.]*\.\s*", "", bio, flags=re.I).strip()
    for field in ("bio", "looks"):
        val = locals()[field]
        val = anachronism.strip(val) if anachronism.find(val) else val
        left = wrong_ties(con, val, fam)
        val = drop_wrong(val, left) if left else val
        if field == "bio":
            bio = val
        else:
            looks = val
    if not bio:
        return None
    a = json.loads(p["appearance"]) if p["appearance"] else {}
    if looks:
        a["description"] = looks
    con.execute("update people set bio = ?, bio_status = 'proposed', bio_occasion = ?, appearance = ? where id = ?",
                (bio, occasion, json.dumps(a) if a else None, pid))
    return {"bio": bio, "looks": looks}


def process_queue(con, llm) -> int:
    """Bios for the season's births, comings of age and promotions (bio_queue)."""
    n = 0
    for q in rows(con, "select * from bio_queue order by id"):
        if write_bio(con, llm, q["person_id"], q["occasion"]):
            n += 1
        con.execute("delete from bio_queue where id = ?", (q["id"],))
    return n


def load_overrides(con) -> int:
    """Danny's own bios (world/bios.yaml: name -> text, or name -> {bio, looks}) replace the model's, for good."""
    if not OVERRIDES.exists():
        return 0
    n = 0
    for name, v in (yaml.safe_load(OVERRIDES.read_text(encoding="utf-8")) or {}).items():
        bio = v if isinstance(v, str) else v.get("bio")
        m = re.search(r"\(p(\d+)\)$", name)
        target = rows(con, "select id, appearance from people where " + ("id = ?" if m else "name = ?"), int(m.group(1)) if m else name)
        if not target or not bio:
            continue
        a = json.loads(target[0]["appearance"]) if target[0]["appearance"] else {}
        if isinstance(v, dict) and v.get("looks"):
            a["description"] = v["looks"]
        con.execute("update people set bio = ?, bio_status = 'danny', appearance = ? where id = ?",
                    (bio.strip(), json.dumps(a) if a else None, target[0]["id"]))
        n += 1
    con.commit()
    return n


def backfill(con, redo: bool = False) -> None:
    """Everyone without a bio: side characters with the quicker 1.5B model, principals with the 3B."""
    import time
    from world.llm import Instruct
    from world.tick import load_rules
    R = load_rules()
    cond = "(bio is null or bio_status = 'proposed')" if redo else "bio is null"
    for tier, key in (("principal", "storyteller"), ("side", "storyteller")):   # the 3B for everyone (the 1.5B's were poor)
        todo = rows(con, f"select id, name from people where tier = ? and {cond} and coalesce(bio_status, '') != 'danny' order by id", tier)
        if not todo:
            continue
        llm = Instruct(R[key]["model"], dtype=R[key].get("dtype", "float32"))
        t0 = time.time()
        for i, p in enumerate(todo):
            write_bio(con, llm, p["id"], "the world's first record of them")
            con.commit()
            if i % 10 == 0:
                print(f"  {tier} {i + 1}/{len(todo)} ({time.time() - t0:.0f}s)", flush=True)
        llm.free()
    print(f"bios: {load_overrides(con)} of Danny's own adopted")


if __name__ == "__main__":
    import sys
    from world.db import connect
    if sys.argv[1] == "load":
        print(f"{load_overrides(connect())} bios adopted from {OVERRIDES.relative_to(ROOT)}")
