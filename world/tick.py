"""One seasonal tick of the world engine, end to end (offline sandbox, v0).

    advance   the season turns: houses' land yields, everyone eats, clients are fed or not
    dream     every named person dreams (run 5), in the voice of their temperament, often from an
              image in their own memories; two townsfolk "rumor dreams" of unknown origin
    recall    most dreams are forgotten on waking (by temperament and vividness); some remembered
              dreams are told to someone close: those are "shared"
    interpret only shared dreams are interpreted (the most salient first), by the dreamer, through
              the instruct model: a belief (and maybe an intention); the listener takes it up too
    propose   one storyteller call per house: the house's state, its legends, its members' beliefs
              and intentions -> up to 2 proposed actions, as JSON
    validate  the engine checks every proposal against the rules (config/rules.yaml): rejected
              (with the rule broken), or rolled: success, partial, failure
    record    accepted outcomes become events, written from templates (never the storyteller's words)
    update    beliefs (witnesses and hearsay, with stances toward houses), old beliefs fade and
              reopen, client loyalty and defections, vital signs

Every model call and every step is timed into `runtimes`. Private truths and the sealed location
are used by the rules where they apply and never written into anything a report prints.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections import Counter, defaultdict

import yaml

from world.db import ROOT, insert, one, rows

SEASONS = ["spring", "summer", "autumn", "winter"]
FLIGHT_IMAGES = ("ring", "gold", "star", "sea", "gate", "harbour", "harbor", "ship", "sail", "two", "night", "water", "festival")
OPENINGS_BY_LAND = {
    "city": "The upper city at dusk,", "ships": "The ships in the harbour,", "groves": "The olive terraces in the hills,",
    "temple": "The temple steps,", "trade": "The wharves at dawn,", "quarries": "The quarry under the ridge,",
    "law": "The hall of judgment,", "healing": "The herb garden by the gate,", "herds": "The mountain at night,",
    "faded": "An old house with shuttered windows,",
}
MEMORY_OPENINGS = [("ring", "A gold ring"), ("festival", "The harbour at night,"), ("star", "Two stars over the sea,"),
                   ("gate", "The western gate,")]


def load_rules() -> dict:
    return yaml.safe_load((ROOT / "config/rules.yaml").read_text())


class Clock:
    """Times each step (and counts model calls) into the runtimes table."""
    def __init__(self, con, year, season):
        self.con, self.year, self.season, self.calls = con, year, season, 0
        self.log = []

    def step(self, name):
        clock = self

        class _S:
            def __enter__(s):
                s.t, s.c = time.time(), clock.calls
                print(f"[{name}]", flush=True)
                return s

            def __exit__(s, *exc):
                dt, n = time.time() - s.t, clock.calls - s.c
                clock.log.append((name, dt, n))
                insert(clock.con, "runtimes", year=clock.year, season=clock.season, step=name, seconds=round(dt, 1), calls=n)
                print(f"  {name}: {dt:.1f} s, {n} model calls", flush=True)
        return _S()


def next_time(con) -> tuple[int, str, int]:
    last = one(con, "select year, season from vital_signs order by year desc, "
                    "case season when 'spring' then 0 when 'summer' then 1 when 'autumn' then 2 else 3 end desc limit 1")
    if not last:
        return 0, "winter", 1    # the Flight was the autumn of year 0; the first tick is that winter
    i = SEASONS.index(last["season"]) + 1
    year = last["year"] + (1 if i == 4 else 0)
    tick = one(con, "select count(*) n from vital_signs")["n"] + 1
    return year, SEASONS[i % 4], tick


def people(con, where="1=1", *args):
    return rows(con, "select p.*, h.name house, h.id house_id, m.role from people p join house_members m on m.person_id = p.id "
                     "and m.left_year is null join houses h on h.id = m.house_id where p.alive = 1 and " + where, *args)


def age(p, year):
    return year - p["born_year"]


# --- 1. advance ------------------------------------------------------------------------------------------
def advance(con, R, year, season):
    report = {}
    for h in rows(con, "select * from houses"):
        y = R["houses"]["yield"][h["land_kind"]]
        f = R["houses"]["season_yield"][season]
        members = one(con, "select count(*) n from house_members m join people p on p.id = m.person_id "
                           "where m.house_id = ? and p.alive = 1 and p.absent = 0", h["id"])["n"]
        clients = latest_clients(con, h["id"])
        need = members * R["houses"]["member_food"] + clients["count"] * R["clients"]["food_per_client"]
        food = h["food"] + y["food"] * f - need
        fed = food >= 0
        con.execute("update houses set food = ?, goods = ?, materials = ? where id = ?",
                    (round(max(0.0, food), 2), round(h["goods"] + y["goods"] * f, 2), round(h["materials"] + y["materials"] * f, 2), h["id"]))
        report[h["name"]] = {"fed": fed, "food": round(max(0.0, food), 1), "need": round(need, 1)}
    return report


def latest_clients(con, house_id):
    if house_id is None:
        return one(con, "select * from house_clients where house_id is null order by id desc limit 1")
    return one(con, "select * from house_clients where house_id = ? order by id desc limit 1", house_id)


# --- 2. dream ---------------------------------------------------------------------------------------------
def vividness(text: str, closed: bool) -> float:
    w = text.split()
    if not w:
        return 0.0
    distinct = len(set(x.lower() for x in w)) / len(w)
    return round(min(1.0, 0.25 + 0.35 * min(1.0, len(w) / 80) + 0.25 * distinct + (0.15 if closed else 0)), 2)


def dream_all(con, R, year, season, clock, r):
    import torch
    from engine.sample import cut_to_last_sentence, generate_dream, load

    D = R["dreaming"]
    model, tok, _ = load(str(ROOT / D["model"]), "cpu")
    dreamers = rows(con, "select p.*, h.land_kind from people p join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                         "where p.alive = 1 and (? - p.born_year) >= 5", year)
    out = []
    for i, p in enumerate(dreamers + [None] * D["rumor_dreams"]):
        temper = p["dream_temperament"] if p else "mystic"
        tag = D["tag"][temper]
        if r.random() < D["random_tag_chance"]:
            tag = r.choice(sorted(set(D["tag"].values())))
        opening = ""
        if p and r.random() < D["opening_chance"]:
            mems = rows(con, "select text from memories where person_id = ? and private = 0 order by vividness desc limit 3", p["id"])
            options = [o for k, o in MEMORY_OPENINGS for m in mems if k in m["text"].lower()]
            options.append(OPENINGS_BY_LAND[p["land_kind"]])
            opening = r.choice(options)
        torch.manual_seed(year * 10000 + SEASONS.index(season) * 1000 + i)
        text, closed = generate_dream(model, tok, opening, D["max_tokens"], "cpu", tag=tag, **D["settings"])
        text = cut_to_last_sentence(text) or text
        did = f"y{year}-{season}-{p['id'] if p else 'rumor' + str(i)}"
        v = vividness(text, closed)
        insert(con, "dreams", id=did, year=year, season=season, dreamer_id=p["id"] if p else None, run="run5",
               kind="world" if p else "rumor", tag=tag, prompt=opening, text=text, vividness=v)
        out.append({"id": did, "person": p, "tag": tag, "text": text, "vividness": v, "temper": temper})
    del model
    return out


# --- 3. recall and share ------------------------------------------------------------------------------------
def recall_and_share(con, R, dreams, r, year, season):
    D = R["dreaming"]
    remembered, shared = [], []
    for d in dreams:
        p = d["person"]
        if p is None:                       # a rumor dream: nobody owns it; it goes round the town
            con.execute("update dreams set recalled = 1 where id = ?", (d["id"],))
            remembered.append(d)
            continue
        chance = D["recall"][d["temper"]] * (1 - D["vividness_weight"] + D["vividness_weight"] * d["vividness"])
        rec = r.random() < chance
        con.execute("update dreams set recalled = ? where id = ?", (1 if rec else 0, d["id"]))
        if not rec:
            continue
        remembered.append(d)
        insert(con, "memories", year=year, season=season, person_id=p["id"], source_type="dream", source_id=d["id"],
               text=d["text"][:300], vividness=d["vividness"])
        if p["absent"]:
            continue                        # away from Corva: there is nobody here to tell (PROPOSED)
        tell = D["share_base"] + D["share_warmth"] * p["warmth"] + (D["share_mystic_bonus"] if d["temper"] == "mystic" else 0)
        if r.random() < tell:
            close = rows(con, "select case when person_a = ? then person_b else person_a end other, strength from relationships "
                              "where (person_a = ? or person_b = ?) and strength > 0", p["id"], p["id"], p["id"])
            close = [c for c in close if one(con, "select alive, absent from people where id = ?", c["other"]) == {"alive": 1, "absent": 0}]
            if not close:
                close = [{"other": m["person_id"], "strength": 0.4} for m in rows(
                    con, "select m.person_id from house_members m join people q on q.id = m.person_id where m.house_id = "
                         "(select house_id from house_members where person_id = ?) and q.id != ? and q.alive = 1 and q.absent = 0", p["id"], p["id"])]
            if close:
                listener = r.choices([c["other"] for c in close], weights=[max(0.05, c["strength"]) for c in close])[0]
                con.execute("update dreams set shared_with = ? where id = ?", (json.dumps([listener]), d["id"]))
                d["listener"] = listener
                shared.append(d)
    return remembered, shared


# --- 4. interpret ---------------------------------------------------------------------------------------------
HOUSE_NAMES = ["Corvane", "Valerius", "Theren", "Aurelian", "Marcellan", "Cassian", "Severin", "Damaris", "Veyra", "Solenne"]
INTERPRET_SYSTEM = (
    "You speak for one person in Corva, an old island city of ten noble houses, in an age of oars and sails, oil lamps, "
    "bronze and stone. They know NOTHING modern: no cars, machines, offices, schools, money in dollars, telephones or the "
    "like. Corva remembers one thing above all: at the autumn festival of the sea, Livia Corvane and Soren of the Harbor "
    "(raised by House Theren) vanished together; nobody knows where. You are given the person and a dream they told to "
    "someone. First retell the dream as THIS PERSON would tell it, in Corva's own terms: anything modern becomes what they "
    "would see in it (a car might be 'a beast of iron that ran without horses'; an office 'a great hall of scribes'). Then say "
    "what the dream means to them, in the first person, from their own beliefs and fears: their opinion, not a fact.")

INTERPRET_SCHEMA = {
    "type": "object",
    "properties": {
        "retelling": {"type": "string", "maxLength": 240},
        "interpretation": {"type": "string", "maxLength": 240},
        "confidence": {"type": "number"},
        "about_house": {"type": "string", "enum": HOUSE_NAMES + ["none"]},
        "stance": {"type": "number"},
        "intention": {"type": "string", "maxLength": 140},
    },
    "required": ["retelling", "interpretation", "confidence", "about_house", "stance", "intention"],
}


def parse_json(text: str):
    """The model's JSON, forgivingly: one object, or several to merge (the 1.5B model often splits its
    answer across two), or, failing that, the fields it managed to write before running out of room."""
    def load(t):
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            try:
                return json.loads(re.sub(r",\s*([}\]])", r"\1", t))
            except json.JSONDecodeError:
                return None
    whole = re.search(r"\{.*\}", text, re.S)
    if whole and (j := load(whole.group(0))) is not None:
        return j
    merged = {}
    for m in re.finditer(r"\{[^{}]*\}", text):
        j = load(m.group(0))
        if isinstance(j, dict):
            merged.update(j)
    if merged:
        return merged
    # cut off mid-answer: salvage the string fields that are complete
    found = dict(re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', text))
    return found or None


def person_sketch(con, p) -> str:
    beliefs = rows(con, "select interpretation from beliefs where holder_id = ? order by confidence desc limit 4", p["id"])
    house = one(con, "select h.name, h.claim from houses h join house_members m on m.house_id = h.id where m.person_id = ?", p["id"])
    role = one(con, "select role from house_members where person_id = ?", p["id"])["role"]
    traits = ", ".join(f"{k} {p[k]:.1f}" for k in ("openness", "caution", "warmth", "pride", "piety"))
    return (f"{p['name']}, {role} of House {house['name']} (its right: {house['claim']})"
            f"{'; ' + p['note'] if p.get('note') else ''}. Temperament: {p['dream_temperament']}. Traits: {traits}. "
            f"Believes: " + " / ".join(b["interpretation"] for b in beliefs))


def interpret(con, R, shared, llm, clock, year, season):
    I = R["interpretation"]
    houses = {h["name"]: h["id"] for h in rows(con, "select id, name from houses")}

    def salience(d):
        t = d["text"].lower()
        return d["vividness"] + 0.15 * sum(k in t for k in FLIGHT_IMAGES) + (0.3 if d["person"]["tier"] == "principal" else 0) \
            + (0.2 if d["temper"] == "mystic" else 0)

    out = []
    for d in sorted(shared, key=salience, reverse=True)[: I["max_per_season"]]:
        p = one(con, "select * from people where id = ?", d["person"]["id"])
        listener = one(con, "select * from people where id = ?", d["listener"])
        user = f"The person: {person_sketch(con, p)}\n\nThe dream they had this {season} and told to {listener['name']}:\n\"{d['text'][:700]}\""
        clock.calls += 1
        j = llm.json(INTERPRET_SYSTEM, user, INTERPRET_SCHEMA, max_new_tokens=I["max_new_tokens"]) or {}
        text = str(j.get("interpretation") or "").strip()
        if not text:
            out.append({"dream": d, "raw": getattr(llm, "last_raw", ""), "ok": False})
            continue
        try:
            conf = max(0.05, min(1.0, float(j.get("confidence") or 0.5)))
        except (TypeError, ValueError):
            conf = 0.5
        about = houses.get(str(j.get("about_house") or ""))
        try:
            stance = max(-1.0, min(1.0, float(j.get("stance")))) if about else None
        except (TypeError, ValueError):
            stance = None
        retelling = str(j.get("retelling") or "").strip()
        insert(con, "beliefs", year=year, season=season, holder_id=p["id"], subject_type="dream", subject_id=d["id"],
               interpretation=text, confidence=round(conf, 2), source_type="own_dream", about_house=about, stance=stance)
        lc = conf * I["listener_trust"] * (0.5 + listener["warmth"] / 2)
        insert(con, "beliefs", year=year, season=season, holder_id=listener["id"], subject_type="dream", subject_id=d["id"],
               interpretation=text, confidence=round(max(0.05, min(1.0, lc)), 2), source_type="told_by", source_person=p["id"],
               about_house=about, stance=stance * 0.7 if stance is not None else None)
        if retelling:   # the dream as they remember and tell it, in Corva's terms
            insert(con, "memories", year=year, season=season, person_id=p["id"], source_type="dream", source_id=d["id"],
                   text=f"(as told) {retelling}", vividness=0.85)
            insert(con, "memories", year=year, season=season, person_id=listener["id"], source_type="dream", source_id=d["id"],
                   told_by=p["id"], text=f"(as told) {retelling}", vividness=0.6)
        intention = str(j.get("intention") or "").strip()
        if intention and intention.lower() not in ("null", "none", ""):
            insert(con, "memories", year=year, season=season, person_id=p["id"], source_type="dream", source_id=d["id"],
                   text=f"I mean to: {intention}", vividness=0.8)
        out.append({"dream": d, "retelling": retelling, "interpretation": text, "confidence": conf, "about": j.get("about_house"),
                    "stance": stance, "intention": intention or None, "listener": listener["name"], "ok": True})
    return out


# --- 5. propose ---------------------------------------------------------------------------------------------
EXAMPLE_ACTIONS = ["search", "accuse", "bribe", "spread a rumour", "feast", "propose a marriage", "threaten",
                   "form an alliance", "pray", "flee", "investigate", "confess"]
STORY_SYSTEM = (
    "You are the storyteller of Corva, an old island city of ten noble houses, in an age of oars and sails. You do not "
    "decide what happens: you propose what ONE house's people might do this season, and the world's rules decide whether "
    "it works. First answer the strategy question about the Flight (Livia Corvane and Soren of the Harbor vanished at the "
    "autumn festival). Then propose up to {n} actions, each by one member who can act (by their id, e.g. \"p12\") or by the "
    "house as a whole (\"h3\"), driven by that person's drives. Any action a person of that age could take is allowed; some "
    "ideas: {examples}. Prefer actions not already taken this season by other houses. Say only what people DO, never what "
    "anything means (no omens, signs, fate or the will of the gods). Use the true family ties given; do not invent others.")


def proposal_schema(actor_ids, target_ids, place_names, n):
    return {
        "type": "object",
        "properties": {
            "strategy": {"type": "string", "maxLength": 200},
            "proposals": {"type": "array", "minItems": 1, "maxItems": n, "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "maxLength": 40},
                    "actor": {"type": "string", "enum": actor_ids},
                    "target": {"type": "string", "enum": target_ids + ["none"]},
                    "place": {"type": "string", "enum": place_names + ["none"]},
                    "why": {"type": "string", "maxLength": 180},
                },
                "required": ["kind", "actor", "target", "place", "why"]}},
        },
        "required": ["strategy", "proposals"],
    }


def true_ties(con, ids) -> list[str]:
    """The real relationships among (and of) the given people: what the model may say about who is whose."""
    ids = set(ids)
    out = []
    for l in rows(con, "select a.name pa, b.name ch, l.kind, a.id aid, b.id bid from lineage l join people a on a.id = l.parent_id "
                       "join people b on b.id = l.child_id"):
        if l["aid"] in ids or l["bid"] in ids:
            out.append(f"{l['ch']} is the {'fostered ' if l['kind'] == 'fostered' else ''}child of {l['pa']}")
    for r in rows(con, "select a.name na, b.name nb, r.kind, a.id aid, b.id bid from relationships r join people a on a.id = r.person_a "
                       "join people b on b.id = r.person_b where r.kind in ('spouse', 'betrothed', 'rival', 'teacher')"):
        if r["aid"] in ids or r["bid"] in ids:
            out.append({"spouse": f"{r['na']} and {r['nb']} are married", "betrothed": f"{r['na']} was betrothed to {r['nb']}",
                        "rival": f"{r['na']} and {r['nb']} are rivals", "teacher": f"{r['na']} teaches {r['nb']}"}[r["kind"]])
    for m in rows(con, "select p.name, m.role, h.name house, p.id from house_members m join people p on p.id = m.person_id "
                       "join houses h on h.id = m.house_id where m.role in ('head', 'heir', 'servant', 'retainer', 'fosterling')"):
        if m["id"] in ids:
            out.append(f"{m['name']} is the {m['role']} of House {m['house']}")
    return sorted(set(out))


def house_context(con, R, h, year, season, drives, used_kinds, last_events, legends_n) -> tuple[str, list, list, list]:
    members = people(con, "h.id = ? and p.absent = 0", h["id"])
    adults = [m for m in members if age(m, year) >= R["population"]["adult_age"]]
    absent = rows(con, "select p.name from people p join house_members m on m.person_id = p.id where m.house_id = ? and p.absent = 1", h["id"])
    clients = latest_clients(con, h["id"])
    legends = rows(con, "select title, text from legends where house_id = ? or house_id is null order by house_id is null limit ?", h["id"], legends_n)
    feel = rows(con, "select hh.name, sum(b.stance * b.confidence) / sum(b.confidence) f from beliefs b "
                     "join house_members m on m.person_id = b.holder_id join houses hh on hh.id = b.about_house "
                     "where m.house_id = ? and b.stance is not null and b.about_house != ? group by hh.name order by f", h["id"], h["id"])
    others = rows(con, "select id, name from houses where id != ? order by id", h["id"])
    principals_elsewhere = rows(con, "select p.id, p.name, hh.name house from people p join house_members m on m.person_id = p.id "
                                     "join houses hh on hh.id = m.house_id where p.tier = 'principal' and p.alive = 1 and p.absent = 0 and hh.id != ?", h["id"])
    lines = [f"House {h['name']} (h{h['id']}). Its hereditary right: {h['claim']}. Its land: {h['land']}.",
             f"Season: {season} of year {year}. Stores: food {h['food']:.0f}, goods {h['goods']:.0f}, materials {h['materials']:.0f}. "
             f"Clients: {clients['count']} townsfolk, loyalty {clients['loyalty']:.2f}.",
             "Members who can act (id, name, role, age, drives this season):"]
    for m in adults[:9]:
        d = drives.get(m["id"])
        lines.append(f"  p{m['id']} {m['name']} ({m['role']}, {age(m, year)})" + (": " + "; ".join(d) if d else ""))
    if absent:
        lines.append("Missing from Corva: " + ", ".join(a["name"] for a in absent) + " (whereabouts unknown to everyone).")
    lines.append("Other houses: " + ", ".join(f"h{o['id']} {o['name']}" for o in others) + ".")
    lines.append("Notable people of other houses: " + ", ".join(f"p{p['id']} {p['name']} ({p['house']})" for p in principals_elsewhere) + ".")
    if legends:
        lines.append("Legends the house tells: " + " | ".join(f"{l['title']}: {l['text']}" for l in legends))
    if feel:
        lines.append("How the house feels toward others (-1 to 1): " + ", ".join(f"{f['name']} {f['f']:+.2f}" for f in feel))
    ties = true_ties(con, [m["id"] for m in adults] + [p["id"] for p in principals_elsewhere])
    lines.append("True family ties: " + "; ".join(ties[:30]) + ".")
    lines.append("Recent events in Corva: " + " ".join(last_events))
    if used_kinds:
        lines.append("Already done this season by other houses: " + ", ".join(f"{k} x{n}" for k, n in used_kinds.most_common()) + ".")
    lines.append(f"Strategy question: what is House {h['name']} trying to achieve about the Flight this season, and why?")
    actor_ids = [f"p{m['id']}" for m in adults] + [f"h{h['id']}"]
    target_ids = [f"h{o['id']}" for o in others] + [f"p{p['id']}" for p in principals_elsewhere] + \
                 [f"p{m['id']}" for m in members if m["id"] not in {a["id"] for a in adults}] + [f"p{m['id']}" for m in adults]
    places = [p["name"] for p in rows(con, "select name from places where kind != 'house'")]
    return "\n".join(lines), actor_ids, sorted(set(target_ids)), places


def family_of(R, kind: str) -> str:
    k = kind.lower()
    for fam, spec in R["validation"]["kinds"].items():
        if any(w in k for w in spec.get("words", [])):
            return fam
    return "other"


def propose(con, R, llm, clock, year, season, tick, drives):
    S = R["storyteller"]
    system = STORY_SYSTEM.format(n=S["proposals_per_house"], examples=", ".join(EXAMPLE_ACTIONS))
    last_events = [e["text"] for e in rows(con, "select text from events where sealed = 0 order by id desc limit 8")][::-1]
    used = Counter()
    out = []
    for h in rows(con, "select * from houses order by id"):
        ctx, actor_ids, target_ids, places = house_context(con, R, h, year, season, drives, used, last_events, S["legends_in_context"])
        schema = proposal_schema(actor_ids, target_ids, places, S["proposals_per_house"])
        j, note = None, ""
        for attempt in range(1 + S["retries"]):
            clock.calls += 1
            j = llm.json(system, ctx + note, schema, max_new_tokens=S["max_new_tokens"])
            props = (j or {}).get("proposals") if isinstance(j, dict) else None
            bad = [] if not isinstance(props, list) else [p for p in props if not isinstance(p, dict) or p.get("actor") not in actor_ids]
            if isinstance(props, list) and props and not bad:
                break
            note = ("\n(Your last reply could not be used: " + ("it was not complete JSON" if not isinstance(props, list) or not props
                    else "an actor was not one of the ids listed") + ". Use only the listed ids.)")
        props = (j or {}).get("proposals") if isinstance(j, dict) else None
        strategy = str((j or {}).get("strategy") or "") if isinstance(j, dict) else ""
        if not isinstance(props, list) or not props:
            out.append({"house": h, "raw": getattr(llm, "last_raw", ""), "proposal": None, "strategy": strategy})
            continue
        for p in props[: S["proposals_per_house"]]:
            if isinstance(p, dict):
                out.append({"house": h, "raw": "", "proposal": p, "strategy": strategy})
                used[family_of(R, str(p.get("kind") or ""))] += 1
    return out


# --- 6. validate and 7. record ---------------------------------------------------------------------------------
TEMPLATES = {   # by family; {verb} is the storyteller's own name for the action (sanitized) for "other"
    "search": "{actor} searched {place} for Livia Corvane and Soren of the Harbor",
    "investigate": "{actor} made inquiries{about}",
    "accuse": "{actor} accused {target} before the city",
    "threaten": "{actor} threatened {target}",
    "demand": "{actor} made demands of {target}",
    "rumor": "{actor} spread a rumour about {target}",
    "bribe": "{actor} paid a bribe to {target}",
    "petition": "{actor} brought a petition before the council",
    "judge": "{actor} sat in judgment on a matter of {target}",
    "rite": "{actor} held a rite at the sea temple",
    "feast": "{actor} gave a feast for the clients of House {house}",
    "gift": "{actor} sent a gift to {target}",
    "marriage": "{actor} proposed a marriage between House {house} and {target}",
    "alliance": "{actor} proposed an alliance to {target}",
    "trade": "{actor} sent a trading venture to {place}",
    "guard": "{actor} posted guards at {place}",
    "build": "{actor} had building work done at {place}",
    "work_land": "{actor} set House {house}'s people to work on its land",
    "insult": "{actor} slighted {target} in public",
    "flee": "{actor} left Corva",
    "confess": "{actor} confessed something to {target}",
    "withdraw": "{actor} kept to {pronoun} own affairs",
    "other": "{actor} tried to {verb}",
}
OUTCOME_TAIL = {"success": ".", "partial": ", with mixed results.", "failure": ", and it came to nothing."}
TRAIT_FOR = {"search": "openness", "investigate": "caution", "accuse": "pride", "threaten": "pride", "demand": "pride",
             "rumor": "openness", "bribe": "caution", "petition": "pride", "judge": "caution", "rite": "piety", "feast": "warmth",
             "gift": "warmth", "marriage": "warmth", "alliance": "warmth", "trade": "openness", "guard": "caution",
             "build": "caution", "work_land": "caution", "insult": "pride", "flee": "openness", "confess": "warmth",
             "withdraw": "caution", "other": "openness"}
NEEDS_TARGET = {"accuse", "threaten", "demand", "rumor", "bribe", "gift", "marriage", "alliance", "insult", "confess"}
NEEDS_PLACE = {"search", "trade", "guard", "build"}


def resolve_id(con, ref: str):
    """'p12' -> ('person', row), 'h3' -> ('house', row), else (None, None)."""
    ref = str(ref or "").strip().lower()
    if ref.startswith("p") and ref[1:].isdigit():
        r = one(con, "select p.*, m.house_id from people p join house_members m on m.person_id = p.id where p.id = ?", int(ref[1:]))
        return ("person", r) if r else (None, None)
    if ref.startswith("h") and ref[1:].isdigit():
        r = one(con, "select * from houses where id = ?", int(ref[1:]))
        return ("house", r) if r else (None, None)
    return None, None


def validate_and_record(con, R, items, year, season, tick, r):
    V = R["validation"]
    places = {p["name"].lower(): p for p in rows(con, "select * from places")}
    sealed = json.loads(one(con, "select value from sealed_facts where key = 'lovers_location'")["value"])
    acted, fam_count, results = set(), Counter(), []
    for it in items:
        h, p = it["house"], it["proposal"]
        status = reason = rule = ev = None
        family = None
        payload = dict(p or {"unparsed": (it.get("raw") or "")[:400]})
        payload["strategy"] = it.get("strategy", "")
        if p is None:
            status, reason, rule = "rejected", "the storyteller's reply could not be used, even after a retry", "unreadable"
        else:
            kind = str(p.get("kind") or "").strip()
            family = family_of(R, kind)
            payload["family"] = family
            akind, actor = resolve_id(con, p.get("actor"))
            tkind, target = resolve_id(con, p.get("target")) if p.get("target") not in (None, "none") else (None, None)
            place = places.get(str(p.get("place") or "").lower()) if p.get("place") not in (None, "none") else None
            if akind == "house":              # the house acts as a whole: its head carries it out
                house_row = actor
                actor = one(con, "select p.*, m.house_id from people p join house_members m on m.person_id = p.id where p.id = ?", house_row["head_id"])
            text_all = " ".join(str(v) for v in p.values())
            if any(re.search(pat, text_all, re.I) for pat in V["meaning_patterns"]):
                status, reason, rule = "rejected", "the proposal says what something means (the hard rule)", "asserts a meaning"
            elif not actor:
                status, reason, rule = "rejected", f"'{p.get('actor')}' is not a person or house id", "no such actor"
            elif not actor["alive"]:
                status, reason, rule = "rejected", f"{actor['name']} is dead", "actor dead"
            elif actor["absent"]:
                status, reason, rule = "rejected", f"{actor['name']} is not in Corva", "actor absent"
            elif year - actor["born_year"] < R["population"]["adult_age"]:
                status, reason, rule = "rejected", f"{actor['name']} is too young to act", "actor a child"
            elif actor["house_id"] != h["id"]:
                status, reason, rule = "rejected", f"{actor['name']} does not belong to House {h['name']}", "not of this house"
            elif V["one_action_per_actor"] and actor["id"] in acted:
                status, reason, rule = "rejected", f"{actor['name']} already acts this season", "already acting"
            elif family in NEEDS_TARGET and not target:
                status, reason, rule = "rejected", f"'{kind}' needs someone to aim at", "no target"
            elif target and tkind == "house" and target["id"] == h["id"] and family in NEEDS_TARGET:
                status, reason, rule = "rejected", "a house cannot aim this at itself", "aimed at itself"
            elif target and tkind == "person" and (not target["alive"] or target["absent"]):
                status, reason, rule = "rejected", f"{target['name']} is not in Corva", "target absent"
            elif family in NEEDS_PLACE and not place:
                status, reason, rule = "rejected", f"'{kind}' needs a place", "no place"
            else:
                spec = V["kinds"][family]
                short = [k for k, v in spec.get("cost", {}).items() if h[k] < v]
                if short:
                    status, reason, rule = "rejected", f"House {h['name']} lacks {', '.join(short)}", "cannot afford"
                else:
                    for k, v in spec.get("cost", {}).items():
                        con.execute(f"update houses set {k} = {k} - ? where id = ?", (v, h["id"]))
                        h[k] -= v
                    chance = spec["base"] * V["season_factor"].get(season, {}).get(family, 1.0)
                    chance += (actor[TRAIT_FOR[family]] - 0.5) * 2 * V["trait_weight"] * spec["base"]
                    thouse = target if tkind == "house" else (one(con, "select h.* from houses h join house_members m on m.house_id = h.id "
                                                                      "where m.person_id = ?", target["id"]) if target else None)
                    if family in ("alliance", "marriage") and thouse:
                        chance += 0.3 * feeling(con, thouse["id"], h["id"])
                    chance *= V["repeat_penalty"] ** fam_count[family]          # the same move again this season is weaker
                    fam_count[family] += 1
                    roll = r.random()
                    outcome = "success" if roll < chance else "partial" if roll < chance + spec["partial"] else "failure"
                    acted.add(actor["id"])
                    facts = {"kind_named": kind, "family": family, "chance": round(chance, 2), "roll": round(roll, 2),
                             "why_given": str(p.get("why") or "")[:200]}
                    sealed_hit = False
                    if family == "search":
                        right = place["id"] == sealed["place_id"]
                        found = right and outcome == "success" and r.random() < V["search_find_chance"] / spec["base"]
                        sealed_hit = found
                        facts["found"] = "a trace" if found else "no trace"
                        if not found and outcome == "success":
                            outcome = "failure"
                    target_name = (f"House {target['name']}" if tkind == "house" else target["name"]) if target else "Corva"
                    verb = re.sub(r"[^a-z ]", "", kind.lower()).strip()[:40] or "act"
                    about = f" about {target_name}" if target else (f" at {place['name']}" if place else "")
                    text = TEMPLATES[family].format(actor=actor["name"], house=h["name"], target=target_name, about=about,
                                                    place=place["name"] if place else "Corva", verb=verb,
                                                    pronoun="the house's" if akind == "house" else "their")
                    if family == "search":
                        text += " and found a trace of them." if sealed_hit else " and found no trace of them."
                    else:
                        text += OUTCOME_TAIL[outcome]
                    involved = [h["id"]] + ([thouse["id"]] if thouse and thouse["id"] != h["id"] else [])
                    ev = insert(con, "events", year=year, season=season, kind=family, place_id=place["id"] if place else None,
                                actors=[actor["id"]] + ([target["id"]] if tkind == "person" else []), houses=involved,
                                outcome=outcome, facts=facts, text=text, sealed=1 if sealed_hit else 0)
                    status = {"success": "accepted", "partial": "partial", "failure": "failed"}[outcome]
                    reason = f"rolled {roll:.2f} against {chance:.2f}"
                    effects(con, R, family, outcome, h, thouse, actor, target if tkind == "person" else None, ev, year, season, r)
        pid = insert(con, "storyteller_proposals", year=year, season=season, tick=tick, house_id=h["id"],
                     kind=str((p or {}).get("kind") or "?"), payload=payload, wording=json.dumps(p or {}, ensure_ascii=False),
                     status=status, reason=reason, rule_broken=rule, event_id=ev)
        if ev:
            con.execute("update events set proposal_id = ? where id = ?", (pid, ev))
        results.append({"house": h["name"], "proposal": p, "family": family, "status": status, "reason": reason, "rule": rule,
                        "event": ev, "strategy": it.get("strategy", "")})
    return results


def feeling(con, house_from, house_to) -> float:
    f = one(con, "select sum(b.stance * b.confidence) / sum(b.confidence) f from beliefs b join house_members m on m.person_id = b.holder_id "
                 "where m.house_id = ? and b.about_house = ? and b.stance is not null", house_from, house_to)
    return f["f"] or 0.0


# --- 8. update: beliefs, house feelings (through beliefs), clients ------------------------------------------
STANCE_TEXT = {
    "demand": ("House {a} made demands of us.", "House {t} owes us."),
    "accuse": ("House {a} accused us before the whole city.", "House {t} is guilty, and we said so."),
    "threaten": ("House {a} threatened us.", "House {t} needed a warning."),
    "rumor": ("House {a} spreads lies about us.", "The city should know what House {t} is."),
    "bribe": ("House {a} paid us well.", "House {t} can be bought."),
    "insult": ("House {a} slighted us in public.", "House {t} deserved the slight."),
    "gift": ("House {a} honoured us with a gift.", "We showed House {t} our goodwill."),
    "alliance": ("House {a} offered us their hand.", "We offered House {t} our hand."),
    "marriage": ("House {a} offered a marriage between our houses.", "We offered House {t} a marriage."),
    "judge": ("The judges of {a} sat over our affairs.", "We judged a matter of House {t}."),
    "investigate": ("House {a} pries into our affairs as if we were guilty.", "We pressed House {t} for the truth."),
}


def effects(con, R, family, outcome, h, thouse, actor, tperson, ev, year, season, r):
    B, Cl = R["beliefs"], R["clients"]
    weight = {"success": 1.0, "partial": 0.6, "failure": 0.3}[outcome]
    if family in B["stance"] and thouse and thouse["id"] != h["id"]:
        s = B["stance"][family]
        t_text, a_text = STANCE_TEXT[family]
        for m in rows(con, "select p.id, p.born_year from people p join house_members m on m.person_id = p.id "
                           "where m.house_id = ? and p.alive = 1 and p.absent = 0", thouse["id"]):
            if year - m["born_year"] < 10:
                continue
            conf = B["witness_confidence"] if tperson and m["id"] == tperson["id"] else B["hearsay_confidence"]
            insert(con, "beliefs", year=year, season=season, holder_id=m["id"], subject_type="event", subject_id=str(ev),
                   interpretation=t_text.format(a=h["name"]), confidence=round(conf * weight + 0.1, 2), source_type="told_by",
                   about_house=h["id"], stance=s["target_to_actor"])
        if s["actor_to_target"]:
            insert(con, "beliefs", year=year, season=season, holder_id=actor["id"], subject_type="event", subject_id=str(ev),
                   interpretation=a_text.format(t=thouse["name"]), confidence=B["witness_confidence"], source_type="witnessed",
                   about_house=thouse["id"], stance=s["actor_to_target"])
        for a_id, b_id in ((h["id"], thouse["id"]), (thouse["id"], h["id"])):   # old wounds reopen
            con.execute("update beliefs set confidence = min(1.0, confidence + ?) where about_house = ? and holder_id in "
                        "(select person_id from house_members where house_id = ?) and stance < 0", (B["reopen_boost"] * weight, b_id, a_id))
        if family in ("accuse", "insult", "rumor") and outcome != "failure":
            add_loyalty(con, thouse["id"], Cl["scandal_loyalty"] * weight)
    if family == "feast" and outcome != "failure":
        add_loyalty(con, h["id"], Cl["feast_loyalty"] * weight)
        draw_unattached(con, h["id"], Cl["join_from_unattached"] * weight)
    if family == "rite" and outcome != "failure":
        add_loyalty(con, h["id"], Cl["rite_loyalty"] * weight)
        draw_unattached(con, h["id"], Cl["join_from_unattached"] * weight * 0.5)
    if family == "work_land" and outcome != "failure":
        con.execute("update houses set food = food + ? where id = ?", (3 * weight, h["id"]))
    if family == "trade" and outcome != "failure":
        con.execute("update houses set goods = goods + ? where id = ?", (3 * weight, h["id"]))
    if family == "build" and outcome != "failure":
        add_loyalty(con, h["id"], 0.02 * weight)
    if family in ("gift", "bribe") and thouse and outcome != "failure":
        con.execute("update houses set goods = goods + ? where id = ?", (2 if family == "gift" else 3, thouse["id"]))
    if family == "flee" and outcome == "success":
        # they leave Corva; where they go is not recorded (nobody saw)
        con.execute("update people set absent = 1, place_id = null where id = ?", (actor["id"],))
    if family == "confess" and tperson and outcome != "failure":
        # what they confess passes privately: their private memories become the listener's (never printed)
        for m in rows(con, "select * from memories where person_id = ? and private = 1", actor["id"]):
            insert(con, "memories", year=year, season=season, person_id=tperson["id"], source_type="told_by", source_id=m["source_id"],
                   told_by=actor["id"], text=m["text"], vividness=0.9 * weight, private=1)
    if family == "investigate" and tperson and outcome == "success":
        # pressing someone who holds a private truth: sometimes they let something slip (privately, to the investigator)
        for m in rows(con, "select * from memories where person_id = ? and private = 1", tperson["id"]):
            if r.random() < 0.35:
                insert(con, "memories", year=year, season=season, person_id=actor["id"], source_type="told_by", source_id=m["source_id"],
                       told_by=tperson["id"], text=m["text"], vividness=0.7, private=1)


PENDING = {}   # house id -> {"loyalty": delta, "gained": n, "lost": n}; applied once at the end of the tick


def add_loyalty(con, house_id, delta):
    PENDING.setdefault(house_id, {"loyalty": 0.0, "gained": 0, "lost": 0})["loyalty"] += delta


def draw_unattached(con, house_id, share):
    un = latest_clients(con, None)
    n = int(round((un["count"] - sum(v["gained"] for v in PENDING.values())) * share))
    if n > 0:
        PENDING.setdefault(house_id, {"loyalty": 0.0, "gained": 0, "lost": 0})["gained"] += n


def update_clients(con, R, year, season, fed, r):
    C = R["clients"]
    to_unattached = 0
    drawn = 0
    for h in rows(con, "select * from houses"):
        last = latest_clients(con, h["id"])
        pend = PENDING.get(h["id"], {"loyalty": 0.0, "gained": 0, "lost": 0})
        loyalty = last["loyalty"] + (C["loyalty_fed"] if fed[h["name"]]["fed"] else C["loyalty_hungry"]) + pend["loyalty"]
        loyalty = max(0.0, min(1.0, loyalty))
        lost = int(round(last["count"] * C["defect_rate"])) if loyalty < C["defect_below"] else 0
        count = last["count"] + pend["gained"] - lost
        to_unattached += lost
        drawn += pend["gained"]
        insert(con, "house_clients", year=year, season=season, house_id=h["id"], count=count, loyalty=round(loyalty, 3),
               gained=pend["gained"], lost=lost)
    un = latest_clients(con, None)
    insert(con, "house_clients", year=year, season=season, house_id=None, count=un["count"] - drawn + to_unattached,
           loyalty=None, gained=to_unattached, lost=drawn)
    PENDING.clear()


def fade_beliefs(con, R):
    # inter-house beliefs fade slowly (reopened ones were lifted already this tick)
    con.execute("update beliefs set confidence = round(confidence * ?, 3) where about_house is not null", (R["beliefs"]["fade_per_season"],))


# --- 9. vital signs ---------------------------------------------------------------------------------------------
def vital_signs(con, year, season, dreams, remembered, shared, interp, results, clock):
    flight = one(con, "select id from events where kind = 'departure'")["id"]
    views = Counter(b["interpretation"] for b in rows(con, "select interpretation from beliefs where subject_type = 'event' and subject_id = ?", str(flight)))
    total = sum(views.values()) or 1
    diversity = 1 - sum((n / total) ** 2 for n in views.values())       # Gini-Simpson: 0 one view .. 1 many
    status = Counter(x["status"] for x in results)
    feelings = rows(con, "select a.name a, b.name b, sum(x.stance * x.confidence) / sum(x.confidence) f, count(*) n from beliefs x "
                         "join house_members m on m.person_id = x.holder_id join houses a on a.id = m.house_id "
                         "join houses b on b.id = x.about_house where x.stance is not null and a.id != b.id group by a.name, b.name")
    clients = {(c["name"] or "(unattached)"): {"count": c["count"], "loyalty": c["loyalty"]} for c in rows(
        con, "select h.name, c.count, c.loyalty from house_clients c left join houses h on h.id = c.house_id where c.year = ? and c.season = ?", year, season)}
    stats = {
        "population": {"principals": one(con, "select count(*) n from people where alive = 1 and tier = 'principal'")["n"],
                       "side": one(con, "select count(*) n from people where alive = 1 and tier = 'side'")["n"],
                       "absent": one(con, "select count(*) n from people where absent = 1")["n"], "townsfolk": 200},
        "dreams": {"dreamed": len(dreams), "remembered": len(remembered), "shared": len(shared), "interpreted": sum(1 for i in interp if i["ok"])},
        "beliefs": one(con, "select count(*) n from beliefs")["n"],
        "flight_views": len(views), "flight_belief_diversity": round(diversity, 2),
        "proposals": dict(status), "acceptance_rate": round((status["accepted"] + status["partial"]) / max(1, len(results)), 2),
        "action_types_proposed": dict(Counter(x["family"] for x in results if x["family"])),
        "action_types_resolved": dict(Counter(x["family"] for x in results if x["event"])),
        "action_names_proposed": dict(Counter(str((x["proposal"] or {}).get("kind", "")).lower() for x in results if x["proposal"])),
        "rejection_reasons": dict(Counter(x["rule"] for x in results if x["rule"])),
        "clients": clients,
        "coldest_feelings": sorted(({"from": f["a"], "to": f["b"], "feeling": round(f["f"], 2)} for f in feelings), key=lambda x: x["feeling"])[:6],
        "warmest_feelings": sorted(({"from": f["a"], "to": f["b"], "feeling": round(f["f"], 2)} for f in feelings), key=lambda x: -x["feeling"])[:4],
        "runtime": {name: round(s, 1) for name, s, _ in clock.log}, "model_calls": clock.calls,
    }
    insert(con, "vital_signs", year=year, season=season, stats=stats)
    return stats
