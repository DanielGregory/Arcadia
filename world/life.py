"""Life in Corva: births, coming of age, promotion and the deaths of the old (all rates PROPOSED, in rules.yaml life).

Run by the seasonal tick (world/run_season.py):
  births     a married couple of child-bearing age may have a child. The child gets the parents' traits blended
             (world/traits.py blend), their looks (hair, eyes, skin and build from a parent), a name in the house's
             naming style that often honours a grandparent, and a place in the father's house (or the house the
             couple lives in). A bio is queued for the instruct model.
  of age     at 16 (in spring) a person comes of age: an event and a new bio.
  promotion  a side character who keeps acting in the world (two or more events, as actor) rises to principal:
             an event, a new bio, and a portrait is painted (run_day, in Danny's chosen style).
  marriages  unmarried side characters of marrying age (18 to 35) marry into houses that are not hostile to theirs,
             about one a season: an event; both a little warmer (the storyteller still makes the political matches)
  deaths     side characters past 60 may die of age (principals only die by events, for now): an event; their
             spouse and children grow more melancholic (traits.on_death).
"""

from __future__ import annotations

import json
import random
from collections import Counter

from world import traits as TR
from world.db import insert, one, rows

# Each house's naming style (PROPOSED): the first names its children are given, besides their grandparents'
NAMES = {
    "Corvane": (["Marius", "Decimus", "Corvan", "Tullus", "Aulus", "Septimus"], ["Livia", "Aelia", "Cornelia", "Tullia", "Marcia"]),
    "Valerius": (["Gaius", "Lucan", "Flavus", "Quintus", "Servius"], ["Drusilla", "Rhea", "Valeria", "Claudia", "Lavinia"]),
    "Theren": (["Galen", "Tiberon", "Corin", "Petros", "Theon", "Varro"], ["Zoe", "Daphne", "Lysandra", "Cyra", "Xenia", "Maia"]),
    "Aurelian": (["Theodric", "Orin", "Ilias", "Kleon"], ["Iola", "Ismene", "Calla", "Ione", "Selene"]),
    "Marcellan": (["Nikias", "Basil", "Lysias", "Xanthos"], ["Octavia", "Thalia", "Nyssa", "Irene"]),
    "Cassian": (["Rufus", "Felix", "Doros", "Bion"], ["Brenna", "Clio", "Elara", "Sabina"]),
    "Severin": (["Aldric", "Quintus", "Damon", "Silas"], ["Phaedra", "Julia", "Delia", "Fausta"]),
    "Damaris": (["Aulus", "Milo", "Evander", "Titus"], ["Hesione", "Tamsin", "Lavinia", "Delia"]),
    "Veyra": (["Kael", "Orin", "Kleon", "Otho"], ["Ysolde", "Fausta", "Helia", "Maia"]),
    "Solenne": (["Silvan", "Isidor", "Laurent", "Corvin"], ["Seraphine", "Selene", "Ione", "Xenia"]),
}


def age(p, year):
    return year - p["born_year"]


def house_of(con, pid):
    return one(con, "select h.* , m.role from houses h join house_members m on m.house_id = h.id where m.person_id = ?", pid)


def child_name(con, house: str, sex: str, grandparents: list[dict], r: random.Random) -> str:
    """Often a grandparent's first name (if no living relative already carries it); otherwise the house's style."""
    living = {p["name"].split()[0] for p in rows(con, "select p.name from people p join house_members m on m.person_id = p.id "
                                                       "join houses h on h.id = m.house_id where h.name = ? and p.alive = 1", house)}
    from world.portraits import sex_of
    honour = [g["name"].split()[0] for g in grandparents if g and sex_of(g["name"]) == sex and g["name"].split()[0] not in living]
    if honour and r.random() < 0.45:
        first = r.choice(honour)
    else:
        pool = [n for n in NAMES.get(house, (["Theon"], ["Zoe"]))[0 if sex == "m" else 1] if n not in living] or \
               NAMES.get(house, (["Theon"], ["Zoe"]))[0 if sex == "m" else 1]
        first = r.choice(pool)
    return f"{first} {house}"


def inherit_looks(con, mother: dict, father: dict, r: random.Random) -> dict:
    """Hair, eyes, skin and build from one parent or the other (their appearance records), the rest drafted."""
    parents = [json.loads(x["appearance"]) for x in (mother, father) if x and x.get("appearance")]
    pick = lambda field: r.choice([p.get(field) for p in parents if p.get(field)] or [None])
    return {"natural_hair": pick("natural_hair"), "eyes": pick("eyes"), "skin": pick("skin")}


def births(con, R, year, season, r) -> list[int]:
    L = R["life"]
    born = []
    order = ["spring", "summer", "autumn", "winter"]
    now = year * 4 + order.index(season)
    for c in rows(con, "select r.person_a a, r.person_b b, r.year y, r.season s from relationships r where r.kind = 'spouse'"):
        if c["y"] is not None and c["s"] in order and now - (c["y"] * 4 + order.index(c["s"])) < 2:
            continue     # married less than two seasons ago
        pa, pb = one(con, "select * from people where id = ?", c["a"]), one(con, "select * from people where id = ?", c["b"])
        if not pa or not pb or not (pa["alive"] and pb["alive"]) or pa["absent"] or pb["absent"]:
            continue
        from world.portraits import sex_of
        mother, father = (pa, pb) if sex_of(pa["name"]) == "f" else (pb, pa)
        if not (L["mother_age"][0] <= age(mother, year) <= L["mother_age"][1]) or r.random() >= L["birth_chance"]:
            continue
        hf, hm = house_of(con, father["id"]), house_of(con, mother["id"])
        house = hf if hf and hf["role"] != "spouse" else hm          # the house whose blood line the couple belongs to
        sex = "f" if r.random() < 0.5 else "m"
        grand = [one(con, "select name from people where id = ?", g["parent_id"]) for x in (mother, father)
                 for g in rows(con, "select parent_id from lineage where child_id = ?", x["id"])]
        name = child_name(con, house["name"], sex, grand, r)
        mt, ft = TR.load(con, mother["id"]), TR.load(con, father["id"])
        t = TR.blend(mt, ft, house["name"], r)
        d = TR.derive(t)
        pid = insert(con, "people", year=year, season=season, name=name, born_year=year, origin="Corva", household=house["name"],
                     openness=d["openness"], caution=d["caution"], warmth=d["warmth"], pride=d["pride"], piety=d["piety"],
                     dream_temperament=d["dream_temperament"], health=1.0, place_id=house["seat_place_id"], alive=1, tier="side",
                     proposed=1, sex=sex, traits=json.dumps(t), note=f"born in the {season} of year {year}")
        looks = inherit_looks(con, mother, father, r)
        looks = {k: v for k, v in looks.items() if v}
        app = {"status": "proposed", "born_year": year, "sex": sex, "build": "a newborn", "face": "a baby's round face",
               "hair": looks.get("natural_hair", "dark") + " baby hair", "eyes": looks.get("eyes", "dark"),
               "skin": looks.get("skin", "olive"), "natural_hair": looks.get("natural_hair"), "marks": "no marks of note",
               "clothing": "swaddling bands"}
        con.execute("update people set appearance = ? where id = ?", (json.dumps(app), pid))
        insert(con, "house_members", house_id=house["id"], person_id=pid, role="child", joined_year=year, joined_season=season)
        for parent in (mother, father):
            insert(con, "lineage", parent_id=parent["id"], child_id=pid, kind="blood")
        insert(con, "events", year=year, season=season, kind="birth", place_id=house["seat_place_id"], actors=[mother["id"], father["id"], pid],
               houses=[house["id"]], outcome="success", facts={}, text=f"A child, {name}, was born to {mother['name']} and {father['name']}.")
        insert(con, "bio_queue", person_id=pid, occasion="birth", year=year, season=season)
        born.append(pid)
    return born


def coming_of_age(con, R, year, season) -> list[int]:
    if season != "spring":
        return []
    out = []
    for p in rows(con, "select p.*, m.house_id from people p join house_members m on m.person_id = p.id "
                       "where p.alive = 1 and ? - p.born_year = ?", year, R["population"]["adult_age"]):
        insert(con, "events", year=year, season=season, kind="coming_of_age", actors=[p["id"]], houses=[p["house_id"]],
               outcome="success", facts={}, text=f"{p['name']} came of age.")
        insert(con, "bio_queue", person_id=p["id"], occasion="coming of age", year=year, season=season)
        out.append(p["id"])
    return out


def promotions(con, R, year, season) -> list[int]:
    """A side character who keeps acting (events as the named actor) rises to principal, while there is room."""
    L = R["life"]
    n_principals = one(con, "select count(*) n from people where tier = 'principal' and alive = 1")["n"]
    if n_principals >= L["max_principals"]:
        return []
    acted = Counter()
    for e in rows(con, "select actors, text from events where sealed = 0"):
        for a in json.loads(e["actors"])[:1]:
            acted[a] += 1
    out = []
    for pid, n in acted.most_common():
        if n < L["promote_after_events"] or len(out) >= L["promotions_per_season"]:
            break
        p = one(con, "select p.*, m.house_id, h.name house from people p join house_members m on m.person_id = p.id "
                     "join houses h on h.id = m.house_id where p.id = ?", pid)
        if not p or p["tier"] != "side" or not p["alive"] or p["absent"] or age(p, year) < R["population"]["adult_age"]:
            continue
        con.execute("update people set tier = 'principal', promoted_from_crowd = 1 where id = ?", (pid,))
        insert(con, "events", year=year, season=season, kind="promotion", actors=[pid], houses=[p["house_id"]], outcome="success",
               facts={"events_as_actor": n}, text=f"{p['name']} has risen to prominence in House {p['house']}.")
        insert(con, "bio_queue", person_id=pid, occasion="promotion", year=year, season=season)
        out.append(pid)
    return out


def marriages(con, R, year, season, r) -> list[int]:
    from world.portraits import sex_of
    from world.tick import feeling
    L = R["life"]
    if r.random() >= L["marriages_per_season"]:
        return []
    lo, hi = L["marrying_age"]
    free = [p for p in rows(con, "select p.*, m.house_id from people p join house_members m on m.person_id = p.id where p.alive = 1 "
                                 "and p.absent = 0 and p.tier = 'side' and ? - p.born_year between ? and ? and p.id not in "
                                 "(select person_a from relationships where kind in ('spouse', 'betrothed', 'talks')) and p.id not in "
                                 "(select person_b from relationships where kind in ('spouse', 'betrothed', 'talks'))", year, lo, hi)]
    r.shuffle(free)
    for a in free:
        for b in free:
            if a["id"] == b["id"] or a["house_id"] == b["house_id"] or sex_of(a["name"]) == sex_of(b["name"]):
                continue
            if feeling(con, a["house_id"], b["house_id"]) < -0.2 or feeling(con, b["house_id"], a["house_id"]) < -0.2:
                continue
            insert(con, "relationships", year=year, season=season, person_a=a["id"], person_b=b["id"], kind="spouse", strength=0.6)
            ev = insert(con, "events", year=year, season=season, kind="wedding", actors=[a["id"], b["id"]],
                        houses=[a["house_id"], b["house_id"]], outcome="success", facts={},
                        text=f"{a['name']} and {b['name']} were married.")
            for x in (a, b):
                TR.nudge(con, x["id"], {"values.love": 0.05, "humors.sanguine": 0.03}, year, season, ev, "a wedding")
            return [a["id"], b["id"]]
    return []


SEED_SIDE = {"Philo", "Dion", "Hesper"}   # the seed story's witnesses: they don't die of age (like the principals)


def deaths(con, R, year, season, r) -> list[int]:
    L = R["life"]
    out = []
    for p in rows(con, "select p.*, m.house_id from people p left join house_members m on m.person_id = p.id "
                       "where p.alive = 1 and p.tier = 'side' and p.absent = 0 and ? - p.born_year >= ?", year, L["old_age"]):
        if p["name"] in SEED_SIDE:
            continue
        if r.random() < (age(p, year) - L["old_age"] + 1) * L["death_per_year_past_old_age"]:
            con.execute("update people set alive = 0, died_year = ?, place_id = null where id = ?", (year, p["id"]))
            ev = insert(con, "events", year=year, season=season, kind="death", actors=[p["id"]], houses=[p["house_id"]] if p["house_id"] else [],
                        outcome="success", facts={}, text=f"{p['name']} died, at {age(p, year)}.")
            TR.on_death(con, p, ev, year, season)
            out.append(p["id"])
    return out
