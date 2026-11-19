"""Each person's fixed physical description: what they look like, so every portrait of them agrees.

    python -m world.appearance draft     # write drafts (PROPOSED) into world/appearance.yaml for anyone not yet in it
    python -m world.appearance load      # copy world/appearance.yaml into the engine's records (people.appearance)

world/appearance.yaml is the source, like docs/seed_history.md: plain text that Danny edits. Every entry has
  status:   proposed (a draft by the engine, to be rewritten freely) | danny (Danny writes it) | written (settled)
  born_year, and the age it describes (the portrait prompt uses the person's age in the year it is painted)
  build, face, hair, eyes, marks (distinguishing marks), clothing (the colours of their house and station)
Danny writes Livia, Soren, Lucan, Marius, Galen, Tiberon, Neria and Theodric himself: their entries start as
stubs (status: danny, fields empty), and nobody is painted until their stub is filled in.

The drafts are composed from the person's house, role, age and the public note about them, with a seeded
choice of features (the same person always gets the same draft). Family resemblance: children take their hair
and eyes after a parent when one is known.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from world.db import connect, rows  # noqa: E402

PATH = ROOT / "world/appearance.yaml"
DANNY = ["Livia Corvane", "Soren of the Harbor", "Lucan Valerius", "Marius Corvane", "Galen Theren", "Tiberon Theren",
         "Neria", "Theodric Aurelian"]
FIELDS = ["skin", "build", "face", "hair", "eyes", "marks", "clothing"]

# --- the house's colours and dress, by station (PROPOSED) -------------------------------------------------------
HOUSE_DRESS = {
    "Corvane": ("black and deep gold", "a long black robe banded in gold, a gold signet ring", "plain black wool with a gold-thread hem"),
    "Valerius": ("sea blue and bronze", "a sea-blue cloak pinned with a bronze clasp over a white tunic", "a short blue tunic and a bronze-studded belt"),
    "Theren": ("olive green and undyed linen", "an olive-green wool mantle over undyed linen", "a green-bordered working tunic, sleeves rolled"),
    "Aurelian": ("white and sea blue", "white priestly robes with a sea-blue stole and a shell pendant", "a plain white temple tunic with a blue cord"),
    "Marcellan": ("saffron orange and brown", "rich saffron-orange robes, rings on several fingers", "a brown tunic with an orange sash and a purse at the belt"),
    "Cassian": ("stone grey and rust", "a grey tunic with a rust-red border, dusted with stone", "a grey leather apron over a rough tunic"),
    "Severin": ("violet and pale linen", "a violet judge's mantle over pale linen", "pale linen with a violet cord at the waist"),
    "Damaris": ("teal and white", "teal healer's robes with a white headcloth, a satchel of herbs", "a teal smock, a bundle of dried herbs at the belt"),
    "Veyra": ("rust red and fur", "rust-red hunter's leathers with a fur collar", "a red wool cloak over leathers, a horn at the belt"),
    "Solenne": ("faded rose and silver", "faded rose silk, once very fine, now worn at the seams, an old silver brooch", "a rose-dyed tunic, much mended"),
}
BUILD = {"m": ["tall and lean", "broad-shouldered and heavy", "short and wiry", "of middling height, solid", "rangy and long-limbed",
               "stocky, thick through the chest"],
         "f": ["tall and slender", "small and quick", "sturdy and broad-hipped", "of middling height, straight-backed", "slight and wiry",
               "full-figured and strong"]}
FACE = ["a long face with a high forehead", "a broad face with heavy cheekbones", "a narrow face and a sharp chin", "a round, open face",
        "a strong hooked nose", "a square jaw", "deep-set features", "a wide mouth quick to smile", "a thin, severe mouth"]
HAIR = ["black", "dark brown", "chestnut", "auburn", "light brown", "dark, tightly curled"]
HAIR_STYLE = {"m": ["cropped short", "worn to the shoulder", "tied back", "thick and unruly"],
              "f": ["braided and pinned up", "worn long and loose", "bound in a plain cloth", "coiled at the nape"]}
SKIN = ["olive", "light olive", "deep olive", "warm brown", "deep brown", "sun-darkened bronze", "pale, quick to burn", "ruddy",
        "golden brown", "tawny"]
EYES = ["dark brown", "black", "hazel", "grey", "green", "amber-brown"]
MARKS = ["a thin scar through the left eyebrow", "a crooked nose, once broken", "a mole on the right cheek", "deep lines at the eyes",
         "calloused, ink-stained fingers", "a missing fingertip on the left hand", "a burn scar on the back of one hand",
         "a gap between the front teeth", "freckles across the nose", "no marks of note"]
ROLE_MARKS = {"Cassian": "stone-cut scars across the knuckles", "Veyra": "a weathered, windburned face", "Valerius": "skin browned by sea wind",
              "Theren": "sun-browned forearms", "Damaris": "hands that smell of rosemary and myrrh"}


def pick(seq, key: str, salt: str):
    return seq[int(hashlib.sha1((key + salt).encode()).hexdigest(), 16) % len(seq)]


def sex_of(name: str) -> str:
    from world.portraits import sex_of as s
    return s(name)


def draft_one(p: dict, house: str, role: str, year: int, parent: dict | None) -> dict:
    age = year - p["born_year"]
    sex = sex_of(p["name"])
    k = p["name"]
    hair = (parent or {}).get("hair_colour") or pick(HAIR, k, "hair")
    hair_words = (f"{hair}, {pick(HAIR_STYLE[sex], k, 'style')}" if age < 45 else
                  f"{hair} going grey, {pick(HAIR_STYLE[sex], k, 'style')}" if age < 60 else
                  f"white, {pick(HAIR_STYLE[sex], k, 'style')}")
    if sex == "m" and age >= 18:
        hair_words += ", " + pick(["clean-shaven", "a short beard", "a full beard", "a trimmed beard"], k, "beard")
    colours, high, low = HOUSE_DRESS[house]
    station = high if role in ("head", "heir", "spouse") or p["tier"] == "principal" else low
    marks = pick(MARKS, k, "marks")
    if house in ROLE_MARKS and role not in ("child",):
        marks = ROLE_MARKS[house] + ("" if marks == "no marks of note" else "; " + marks)
    if age < 12:
        build = "a child, small for their age" if pick([0, 1], k, "small") else "a child, tall for their age"
    else:
        build = pick(BUILD[sex], k, "build") + (", stooped a little with age" if age >= 65 else "")
    return {"status": "proposed", "born_year": p["born_year"], "age_in_year": {year: age}, "sex": sex,
            "skin": pick(SKIN, k, "skin"), "build": build, "face": pick(FACE, k, "face") + (", weathered" if age >= 50 else ""),
            "hair": hair_words, "eyes": (parent or {}).get("eye_colour") or pick(EYES, k, "eyes"), "marks": marks,
            "clothing": f"{station} (House {house}: {colours})", "natural_hair": hair}


def load_yaml() -> dict:
    return yaml.safe_load(PATH.read_text(encoding="utf-8")) or {} if PATH.exists() else {}


def draft() -> None:
    con = connect()
    year = rows(con, "select max(year) y from storyteller_proposals")[0]["y"] or 0
    have = load_yaml()
    people = rows(con, "select p.*, m.role, h.name house from people p join house_members m on m.person_id = p.id "
                       "join houses h on h.id = m.house_id order by p.born_year")
    parents = {}
    for l in rows(con, "select parent_id, child_id from lineage"):
        parents.setdefault(l["child_id"], l["parent_id"])
    made = {}
    out = dict(have)
    from collections import Counter
    dup = Counter(p["name"] for p in people)
    key = lambda p: p["name"] if dup[p["name"]] == 1 else f"{p['name']} (p{p['id']})"   # two Julias: told apart by id
    for p in people:   # eldest first, so parents are drafted before their children
        p["key"] = key(p)
        if p["key"] in have and have[p["key"]].get("status") == "proposed" and not have[p["key"]].get("skin"):
            have[p["key"]]["skin"] = pick(SKIN, p["name"], "skin")   # older drafts get the newer field
        if p["key"] in have:
            made[p["id"]] = {"hair_colour": have[p["key"]].get("natural_hair"), "eye_colour": have[p["key"]].get("eyes")}
            continue
        if p["name"] in DANNY:
            out[p["key"]] = {"status": "danny", "born_year": p["born_year"], "age_in_year": {year: year - p["born_year"]},
                              "sex": sex_of(p["name"]), **{f: "" for f in FIELDS}}
            continue
        par = made.get(parents.get(p["id"]))
        d = draft_one(p, p["house"], p["role"], year, par)
        out[p["key"]] = d
        made[p["id"]] = {"hair_colour": d["natural_hair"], "eye_colour": d["eyes"]}
    header = ("# Physical descriptions of Corva's people: the fixed record every portrait is built from.\n"
              "# status: proposed (an engine draft: rewrite freely) | danny (Danny writes it; empty until then) | written (settled)\n"
              "# age_in_year: the age this describes, by year (the portrait uses their age in the year it is painted).\n"
              "# natural_hair: their hair colour before any grey (their children are drafted with it).\n"
              "# scene: (optional) what their character card shows them doing, with the prop of their role; it leads the card's prompt.\n"
              "# Change anything; then: python -m world.appearance load\n\n")
    order = {p["key"]: (p["tier"] != "principal", p["house"], p["born_year"]) for p in people}
    text = yaml.safe_dump({k: out[k] for k in sorted(out, key=lambda n: order.get(n, (True, "", 0)))},
                          sort_keys=False, allow_unicode=True, width=120)
    PATH.write_text(header + text, encoding="utf-8")
    print(f"{PATH.relative_to(ROOT)}: {len(out)} people ({sum(v['status'] == 'danny' for v in out.values())} for Danny to write)")


def load() -> None:
    """The engine adopts the descriptions: people.appearance (JSON) for everyone in the file who has one."""
    con = connect()
    n = 0
    for name, d in load_yaml().items():
        if d.get("status") == "danny" and not any(d.get(f) for f in FIELDS):
            continue
        rec = {k: v for k, v in d.items() }
        import re
        m = re.search(r"\(p(\d+)\)$", name)
        cur = (con.execute("update people set appearance = ? where id = ?", (json.dumps(rec, ensure_ascii=False), int(m.group(1)))) if m
               else con.execute("update people set appearance = ? where name = ?", (json.dumps(rec, ensure_ascii=False), name)))
        n += cur.rowcount
    con.commit()
    print(f"{n} descriptions on their people's records")


if __name__ == "__main__":
    {"draft": draft, "load": load}[sys.argv[1]]()
