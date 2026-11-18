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
INTERPRET_SYSTEM = (
    "You speak for one person in Corva, an old island city of ten noble houses. Corva remembers one thing above all this "
    "season: at the autumn festival of the sea, Livia Corvane and Soren of the Harbor (raised by House Theren) vanished "
    "together; nobody knows where. You will be given the person and a dream they had and told to someone. Say what the "
    "dream means TO THIS PERSON, in their own voice, from their own beliefs and fears. It is their opinion, not a fact. "
    "Reply with JSON only: {\"interpretation\": one or two sentences in the first person, \"confidence\": 0.0-1.0, "
    "\"about_house\": one of Corvane, Valerius, Theren, Aurelian, Marcellan, Cassian, Severin, Damaris, Veyra, Solenne or null, "
    "\"stance\": -1.0 (against that house) to 1.0 (for it) or null, \"intention\": something they now mean to do, or null}")


def parse_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
        except json.JSONDecodeError:
            return None


def person_sketch(con, p) -> str:
    beliefs = rows(con, "select interpretation from beliefs where holder_id = ? order by confidence desc limit 4", p["id"])
    house = one(con, "select h.name, h.claim from houses h join house_members m on m.house_id = h.id where m.person_id = ?", p["id"])
    traits = ", ".join(f"{k} {p[k]:.1f}" for k in ("openness", "caution", "warmth", "pride", "piety"))
    return (f"{p['name']}, {p.get('note') or p['role'] if 'role' in p else ''} of House {house['name']} "
            f"(its right: {house['claim']}). Temperament: {p['dream_temperament']}. Traits: {traits}. "
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
        p["role"] = one(con, "select role from house_members where person_id = ?", p["id"])["role"]
        user = f"The person: {person_sketch(con, p)}\n\nThe dream they had this {season} and told to " \
               f"{one(con, 'select name from people where id = ?', d['listener'])['name']}:\n\"{d['text'][:700]}\""
        clock.calls += 1
        raw = llm.chat(INTERPRET_SYSTEM, user, max_new_tokens=I["max_new_tokens"])
        j = parse_json(raw) or {}
        text = str(j.get("interpretation") or "").strip()
        if not text:
            out.append({"dream": d, "raw": raw, "ok": False})
            continue
        conf = float(j.get("confidence") or 0.5)
        about = houses.get(str(j.get("about_house") or "").strip())
        stance = j.get("stance")
        stance = max(-1.0, min(1.0, float(stance))) if isinstance(stance, (int, float)) and about else None
        insert(con, "beliefs", year=year, season=season, holder_id=p["id"], subject_type="dream", subject_id=d["id"],
               interpretation=text, confidence=round(max(0.05, min(1.0, conf)), 2), source_type="own_dream",
               about_house=about, stance=stance)
        listener = one(con, "select * from people where id = ?", d["listener"])
        lc = conf * I["listener_trust"] * (0.5 + listener["warmth"] / 2)
        insert(con, "beliefs", year=year, season=season, holder_id=listener["id"], subject_type="dream", subject_id=d["id"],
               interpretation=text, confidence=round(max(0.05, min(1.0, lc)), 2), source_type="told_by", source_person=p["id"],
               about_house=about, stance=stance * 0.7 if stance is not None else None)
        intention = str(j.get("intention") or "").strip() or None
        if intention and intention.lower() not in ("null", "none"):
            insert(con, "memories", year=year, season=season, person_id=p["id"], source_type="dream", source_id=d["id"],
                   text=f"I mean to: {intention}", vividness=0.8)
        out.append({"dream": d, "interpretation": text, "confidence": conf, "about": j.get("about_house"), "stance": stance,
                    "intention": intention, "listener": listener["name"], "ok": True})
    return out


# --- 5. propose ---------------------------------------------------------------------------------------------
STORY_SYSTEM = (
    "You are the storyteller of Corva, an old island city of ten noble houses. You do not decide what happens: you "
    "propose what one house might DO this season, and the world's rules decide whether it works. Propose actions by "
    "named, adult members who are in Corva. Only these kinds: {kinds}. Places you may name: {places}. "
    "Never say what anything means (no omens, signs, fate or gods' wishes): only what people do. "
    "Reply with JSON only: {{\"proposals\": [{{\"kind\": ..., \"actor\": full name, \"target_house\": a house name or null, "
    "\"target_person\": a full name or null, \"place\": a place name or null, \"why\": a short reason from the house's point "
    "of view}}]}} with at most {n} proposals.")


def house_context(con, R, h, year, season, intentions_by_person, last_events) -> str:
    members = people(con, "h.id = ? and p.absent = 0", h["id"])
    adults = [m for m in members if age(m, year) >= R["population"]["adult_age"]]
    absent = rows(con, "select p.name from people p join house_members m on m.person_id = p.id where m.house_id = ? and p.absent = 1", h["id"])
    clients = latest_clients(con, h["id"])
    legends = rows(con, "select title, text from legends where house_id = ? or house_id is null order by house_id is null limit ?",
                   h["id"], R["storyteller"]["legends_in_context"])
    feel = rows(con, "select hh.name, sum(b.stance * b.confidence) / sum(b.confidence) f from beliefs b "
                     "join house_members m on m.person_id = b.holder_id join houses hh on hh.id = b.about_house "
                     "where m.house_id = ? and b.stance is not null and b.about_house != ? group by hh.name order by f", h["id"], h["id"])
    beliefs = rows(con, "select p.name, b.interpretation, b.confidence from beliefs b join people p on p.id = b.holder_id "
                        "join house_members m on m.person_id = p.id where m.house_id = ? and p.tier = 'principal' and p.absent = 0 "
                        "order by b.year desc, b.confidence desc limit 6", h["id"])
    lines = [f"House {h['name']}. Its hereditary right: {h['claim']}. Its land: {h['land']}.",
             f"Season: {season} of year {year}. Stores: food {h['food']:.0f}, goods {h['goods']:.0f}, materials {h['materials']:.0f}. "
             f"Clients: {clients['count']} townsfolk, loyalty {clients['loyalty']:.2f}.",
             "Members in Corva who can act: " + "; ".join(f"{m['name']} ({m['role']}, {age(m, year)})" for m in adults[:8]) + "."]
    if absent:
        lines.append("Missing from Corva: " + ", ".join(a["name"] for a in absent) + " (whereabouts unknown).")
    if legends:
        lines.append("Legends the house tells: " + " | ".join(f"{l['title']}: {l['text']}" for l in legends))
    if feel:
        lines.append("How the house feels toward others (from -1 to 1): " + ", ".join(f"{f['name']} {f['f']:+.2f}" for f in feel))
    if beliefs:
        lines.append("What its people believe: " + " / ".join(f"{b['name']}: \"{b['interpretation']}\"" for b in beliefs))
    ints = [f"{m['name']}: {intentions_by_person[m['id']]}" for m in adults if m["id"] in intentions_by_person]
    if ints:
        lines.append("Intentions after their dreams: " + " / ".join(ints))
    lines.append("Recent events in Corva: " + " ".join(last_events))
    return "\n".join(lines)


def propose(con, R, llm, clock, year, season, tick):
    kinds = ", ".join(R["validation"]["kinds"])
    places = ", ".join(p["name"] for p in rows(con, "select name from places where kind != 'house'"))
    system = STORY_SYSTEM.format(kinds=kinds, places=places, n=R["storyteller"]["proposals_per_house"])
    intentions = {}
    for m in rows(con, "select person_id, text from memories where year = ? and season = ? and text like 'I mean to:%'", year, season):
        intentions[m["person_id"]] = m["text"][len("I mean to: "):]
    last_events = [e["text"] for e in rows(con, "select text from events where sealed = 0 order by id desc limit 8")][::-1]
    out = []
    for h in rows(con, "select * from houses order by id"):
        ctx = house_context(con, R, h, year, season, intentions, last_events)
        clock.calls += 1
        raw = llm.chat(system, ctx, max_new_tokens=R["storyteller"]["max_new_tokens"])
        j = parse_json(raw)
        props = (j or {}).get("proposals") if isinstance(j, dict) else None
        if not isinstance(props, list):
            out.append({"house": h, "raw": raw, "proposal": None})
            continue
        for p in props[: R["storyteller"]["proposals_per_house"]]:
            if isinstance(p, dict):
                out.append({"house": h, "raw": raw, "proposal": p})
    return out


# --- 6. validate and 7. record ---------------------------------------------------------------------------------
TEMPLATES = {
    "search": "{actor} searched {place} for Livia Corvane and Soren of the Harbor",
    "question": "{actor} questioned {target_person}",
    "demand": "{actor} demanded satisfaction from House {target_house}",
    "accuse": "{actor} accused House {target_house} before the city",
    "petition": "{actor} brought a petition before the council",
    "judge": "{actor} sat in judgment on a dispute involving House {target_house}",
    "rite": "{actor} held a rite at the sea temple",
    "feast": "{actor} gave a feast for the clients of House {house}",
    "gift": "{actor} sent a gift to House {target_house}",
    "marriage_offer": "{actor} offered House {target_house} a marriage between the houses",
    "alliance": "{actor} proposed an alliance to House {target_house}",
    "trade": "{actor} sent a trading venture to {place}",
    "guard": "{actor} posted guards at {place}",
    "build": "{actor} had building work done at {place}",
    "work_land": "{actor} set House {house}'s people to work on its land",
    "insult": "{actor} slighted House {target_house} in public",
    "withdraw": "{actor} kept House {house} to its own affairs",
}
OUTCOME_TAIL = {"success": ".", "partial": ", with mixed results.", "failure": ", and it came to nothing."}
TRAIT_FOR = {"search": "openness", "question": "caution", "demand": "pride", "accuse": "pride", "petition": "pride",
             "judge": "caution", "rite": "piety", "feast": "warmth", "gift": "warmth", "marriage_offer": "warmth",
             "alliance": "warmth", "trade": "openness", "guard": "caution", "build": "caution", "work_land": "caution",
             "insult": "pride", "withdraw": "caution"}
NEEDS_TARGET_HOUSE = {"demand", "accuse", "gift", "marriage_offer", "alliance", "insult", "judge"}


def validate_and_record(con, R, items, year, season, tick, r, strangeness_used=0):
    V = R["validation"]
    houses = {h["name"].lower(): h for h in rows(con, "select * from houses")}
    places = {p["name"].lower(): p for p in rows(con, "select * from places")}
    sealed = json.loads(one(con, "select value from sealed_facts where key = 'lovers_location'")["value"])
    acted = set()
    results = []
    for it in items:
        h, p, raw = it["house"], it["proposal"], it["raw"]
        status, reason, rule, ev = None, None, None, None
        payload = p or {"unparsed": raw[:400]}
        wording = json.dumps(p, ensure_ascii=False) if p else raw[:400]

        def reject(rule_name, why):
            return "rejected", why, rule_name

        if p is None:
            status, reason, rule = reject("unreadable", "the storyteller's reply was not valid JSON")
        else:
            kind = str(p.get("kind") or "").strip().lower().replace(" ", "_")
            actor_name = str(p.get("actor") or "").strip()
            actor = one(con, "select p.*, m.house_id from people p join house_members m on m.person_id = p.id where lower(p.name) = lower(?)", actor_name)
            tp_name = str(p.get("target_person") or "").strip()
            tperson = one(con, "select * from people where lower(name) = lower(?)", tp_name) if tp_name and tp_name.lower() not in ("null", "none") else None
            th_name = str(p.get("target_house") or "").strip().lower().removeprefix("house ").strip()
            thouse = houses.get(th_name)
            pl_name = str(p.get("place") or "").strip().lower()
            place = places.get(pl_name) or places.get("the " + pl_name)
            text_all = " ".join(str(v) for v in p.values())
            if any(re.search(pat, text_all, re.I) for pat in V["meaning_patterns"]):
                status, reason, rule = reject("asserts a meaning", "the proposal says what something means (the hard rule)")
            elif kind not in V["kinds"]:
                status, reason, rule = reject("unknown kind", f"'{kind}' is not an action the world knows")
            elif not actor:
                status, reason, rule = reject("no such person", f"nobody called '{actor_name}' lives in Corva")
            elif not actor["alive"]:
                status, reason, rule = reject("actor dead", f"{actor['name']} is dead")
            elif actor["absent"]:
                status, reason, rule = reject("actor absent", f"{actor['name']} is not in Corva")
            elif year - actor["born_year"] < R["population"]["adult_age"]:
                status, reason, rule = reject("actor a child", f"{actor['name']} is too young to act")
            elif actor["house_id"] != h["id"]:
                status, reason, rule = reject("not of this house", f"{actor['name']} does not belong to House {h['name']}")
            elif V["one_action_per_actor"] and actor["id"] in acted:
                status, reason, rule = reject("already acting", f"{actor['name']} already acts this season")
            elif kind in NEEDS_TARGET_HOUSE and not thouse:
                status, reason, rule = reject("no target house", f"a {kind} needs a house to aim at")
            elif thouse and thouse["id"] == h["id"] and kind in NEEDS_TARGET_HOUSE:
                status, reason, rule = reject("aimed at itself", f"a house cannot {kind} itself")
            elif kind == "question" and (not tperson or not tperson["alive"]):
                status, reason, rule = reject("no such person", "the person to question is not in the record")
            elif kind == "question" and tperson["absent"]:
                status, reason, rule = reject("target absent", f"{tperson['name']} is not in Corva to be questioned")
            elif kind in ("search", "trade", "guard", "build") and not place:
                status, reason, rule = reject("no such place", f"'{p.get('place')}' is not a place in the record")
            else:
                spec = V["kinds"][kind]
                costs = spec.get("cost", {})
                short = [k for k, v in costs.items() if h[k] < v]
                if short:
                    status, reason, rule = reject("cannot afford", f"House {h['name']} lacks {', '.join(short)}")
                else:
                    for k, v in costs.items():
                        con.execute(f"update houses set {k} = {k} - ? where id = ?", (v, h["id"]))
                        h[k] -= v
                    chance = spec["base"] * V["season_factor"].get(season, {}).get(kind, 1.0)
                    chance += (actor[TRAIT_FOR[kind]] - 0.5) * 2 * V["trait_weight"] * spec["base"]
                    if kind in ("alliance", "marriage_offer") and thouse:
                        chance += 0.3 * feeling(con, thouse["id"], h["id"])
                    roll = r.random()
                    outcome = "success" if roll < chance else "partial" if roll < chance + spec["partial"] else "failure"
                    acted.add(actor["id"])
                    sealed_hit = False
                    facts = {"chance": round(chance, 2), "roll": round(roll, 2), "why_given": str(p.get("why") or "")[:200]}
                    if kind == "search":
                        # the rules know where the lovers are; the record only says whether a trace turned up
                        right = place["id"] == sealed["place_id"]
                        found = right and outcome == "success" and r.random() < V["search_find_chance"] / spec["base"]
                        if found:
                            sealed_hit = True
                            facts["found"] = "a trace"
                        else:
                            outcome = "failure" if outcome == "success" else outcome
                            facts["found"] = "no trace"
                    fill = {"actor": actor["name"], "house": h["name"], "target_house": thouse["name"] if thouse else "",
                            "target_person": tperson["name"] if tperson else "", "place": place["name"] if place else "Corva"}
                    text = TEMPLATES[kind].format(**fill) + (" and found no trace of them." if kind == "search" and not sealed_hit
                                                             else " and found a trace of them." if sealed_hit else OUTCOME_TAIL[outcome])
                    involved = [h["id"]] + ([thouse["id"]] if thouse else [])
                    ev = insert(con, "events", year=year, season=season, kind=kind, place_id=place["id"] if place else None,
                                actors=[actor["id"]] + ([tperson["id"]] if tperson else []), houses=involved,
                                outcome=outcome, facts=facts, text=text, sealed=1 if sealed_hit else 0)
                    status = {"success": "accepted", "partial": "partial", "failure": "failed"}[outcome]
                    reason = f"rolled {roll:.2f} against {chance:.2f}" + ("" if kind != "search" else "; searched")
                    effects(con, R, kind, outcome, h, thouse, actor, tperson, ev, year, season)
        pid = insert(con, "storyteller_proposals", year=year, season=season, tick=tick, house_id=h["id"],
                     kind=str((p or {}).get("kind") or "?"), payload=payload, wording=wording, status=status,
                     reason=reason, rule_broken=rule, event_id=ev)
        if ev:
            con.execute("update events set proposal_id = ? where id = ?", (pid, ev))
        results.append({"house": h["name"], "proposal": p, "status": status, "reason": reason, "rule": rule, "event": ev})
    return results


def feeling(con, house_from, house_to) -> float:
    f = one(con, "select sum(b.stance * b.confidence) / sum(b.confidence) f from beliefs b join house_members m on m.person_id = b.holder_id "
                 "where m.house_id = ? and b.about_house = ? and b.stance is not null", house_from, house_to)
    return f["f"] or 0.0


# --- 8. update: beliefs, house feelings (through beliefs), clients ------------------------------------------
STANCE_TEXT = {
    "demand": ("House {a} made demands of us.", "House {t} owes us."),
    "accuse": ("House {a} accused us before the whole city.", "House {t} is guilty, and we said so."),
    "insult": ("House {a} slighted us in public.", "House {t} deserved the slight."),
    "gift": ("House {a} honoured us with a gift.", "We showed House {t} our goodwill."),
    "alliance": ("House {a} offered us their hand.", "We offered House {t} our hand."),
    "marriage_offer": ("House {a} offered a marriage between our houses.", "We offered House {t} a marriage."),
    "judge": ("The judges of {a} sat over our affairs.", "We judged a matter of House {t}."),
    "question": ("House {a} questioned one of ours as if we were guilty.", "We pressed House {t} for the truth."),
}


def effects(con, R, kind, outcome, h, thouse, actor, tperson, ev, year, season):
    B, Cl = R["beliefs"], R["clients"]
    weight = {"success": 1.0, "partial": 0.6, "failure": 0.3}[outcome]
    target_house = thouse
    if kind == "question" and tperson:
        target_house = one(con, "select h.* from houses h join house_members m on m.house_id = h.id where m.person_id = ?", tperson["id"])
    if kind in R["beliefs"]["stance"] and target_house and target_house["id"] != h["id"]:
        s = R["beliefs"]["stance"][kind]
        t_text, a_text = STANCE_TEXT[kind]
        for m in rows(con, "select p.id, p.born_year from people p join house_members m on m.person_id = p.id where m.house_id = ? and p.alive = 1 and p.absent = 0", target_house["id"]):
            if year - m["born_year"] < 10:
                continue
            conf = B["witness_confidence"] if tperson and m["id"] == tperson["id"] else B["hearsay_confidence"]
            insert(con, "beliefs", year=year, season=season, holder_id=m["id"], subject_type="event", subject_id=str(ev),
                   interpretation=t_text.format(a=h["name"]), confidence=round(conf * weight + 0.1, 2), source_type="told_by",
                   about_house=h["id"], stance=s["target_to_actor"])
        if s["actor_to_target"]:
            insert(con, "beliefs", year=year, season=season, holder_id=actor["id"], subject_type="event", subject_id=str(ev),
                   interpretation=a_text.format(t=target_house["name"]), confidence=B["witness_confidence"], source_type="witnessed",
                   about_house=target_house["id"], stance=s["actor_to_target"])
        # old wounds reopen: earlier beliefs between these two houses come back to mind
        for a_id, b_id in ((h["id"], target_house["id"]), (target_house["id"], h["id"])):
            con.execute("update beliefs set confidence = min(1.0, confidence + ?) where about_house = ? and holder_id in "
                        "(select person_id from house_members where house_id = ?) and stance < 0",
                        (B["reopen_boost"] * weight, b_id, a_id))
        if kind in ("accuse", "insult") and outcome != "failure":
            add_loyalty(con, target_house["id"], Cl["scandal_loyalty"] * weight)
    if kind == "feast" and outcome != "failure":
        add_loyalty(con, h["id"], Cl["feast_loyalty"] * weight)
        draw_unattached(con, h["id"], Cl["join_from_unattached"] * weight)
    if kind == "rite" and outcome != "failure":
        add_loyalty(con, h["id"], Cl["rite_loyalty"] * weight)
        draw_unattached(con, h["id"], Cl["join_from_unattached"] * weight * 0.5)
    if kind == "work_land" and outcome != "failure":
        con.execute("update houses set food = food + ? where id = ?", (3 * weight, h["id"]))
    if kind == "trade" and outcome != "failure":
        con.execute("update houses set goods = goods + ? where id = ?", (3 * weight, h["id"]))
    if kind == "build" and outcome != "failure":
        add_loyalty(con, h["id"], 0.02 * weight)
    if kind == "gift" and thouse and outcome != "failure":
        con.execute("update houses set goods = goods + 2 where id = ?", (thouse["id"],))


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
        "rejection_reasons": dict(Counter(x["rule"] for x in results if x["rule"])),
        "clients": clients,
        "coldest_feelings": sorted(({"from": f["a"], "to": f["b"], "feeling": round(f["f"], 2)} for f in feelings), key=lambda x: x["feeling"])[:6],
        "warmest_feelings": sorted(({"from": f["a"], "to": f["b"], "feeling": round(f["f"], 2)} for f in feelings), key=lambda x: -x["feeling"])[:4],
        "runtime": {name: round(s, 1) for name, s, _ in clock.log}, "model_calls": clock.calls,
    }
    insert(con, "vital_signs", year=year, season=season, stats=stats)
    return stats
