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
    # Where people are: at the start of every season everyone who is here goes home to their house's
    # seat; acting in an event this season takes them to its place (move_actors, below). The absent
    # keep place_id NULL: where they are is sealed.
    con.execute("update people set place_id = (select h.seat_place_id from house_members m join houses h on h.id = m.house_id "
                "where m.person_id = people.id and m.left_year is null limit 1) where alive = 1 and absent = 0")
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


def move_actors(con, person_ids, place):
    """People who act somewhere are there now (until the season ends). The absent stay unplaced."""
    if not place:
        return
    for pid in person_ids:
        con.execute("update people set place_id = ? where id = ? and absent = 0 and alive = 1", (place["id"], pid))


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
        # principals dream at full length; side characters and the town's rumor dreams more briefly (runtime)
        cap = D["max_tokens"] if p and p["tier"] == "principal" else D["side_max_tokens"]
        text, closed = generate_dream(model, tok, opening, cap, "cpu", tag=tag, **D["settings"])
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
                told = [listener]
                # gossip: a striking dream is passed on, each hearer telling one more person with some chance
                # (more if the dream is vivid). A dream told round the town is "most shared".
                for _ in range(D["pass_on_max"]):
                    if r.random() >= D["pass_on"] * (0.5 + d["vividness"]):
                        break
                    nxt = rows(con, "select case when person_a = ? then person_b else person_a end other from relationships "
                                    "where (person_a = ? or person_b = ?) and strength > 0", told[-1], told[-1], told[-1])
                    nxt = [n["other"] for n in nxt if n["other"] not in told and n["other"] != p["id"]
                           and one(con, "select alive, absent from people where id = ?", n["other"]) == {"alive": 1, "absent": 0}]
                    if not nxt:
                        break
                    told.append(r.choice(nxt))
                con.execute("update dreams set shared_with = ? where id = ?", (json.dumps(told), d["id"]))
                d["listener"] = listener
                d["told"] = told
                shared.append(d)
    return remembered, shared


# --- 4. interpret ---------------------------------------------------------------------------------------------
HOUSE_NAMES = ["Corvane", "Valerius", "Theren", "Aurelian", "Marcellan", "Cassian", "Severin", "Damaris", "Veyra", "Solenne"]
INTERPRET_SYSTEM = (
    "You speak for one person in Corva, an old island city of ten noble houses, in an age of oars and sails, oil lamps, "
    "bronze and stone. Corva is its own world: there is no Athens, Rome, Egypt or Persia in it, no Zeus or Mars, and nothing "
    "modern (no cars, machines that run by themselves, offices, schools, dollars, telephones, neighborhoods or front yards). "
    "Corva remembers one thing above all: at the autumn festival of the sea, Livia Corvane and Soren of the Harbor (raised by "
    "House Theren) vanished together; nobody knows where. You are given the person and a dream they told. First retell the "
    "dream as THIS PERSON would tell it, in Corva's own terms: anything modern or foreign becomes what they would see in it "
    "(a car might be 'a beast of iron that ran without horses'; Athenians 'strangers from over the sea'). Then say what the "
    "dream means to them, in the first person. The reading must come from who they are: their house's interests, its "
    "loyalties and grudges, their own beliefs about the Flight, their temperament. A Valerius and a Theren read the same "
    "dream differently. It is their opinion, not a fact. about_house: the one house the dream speaks to them about, or "
    "\"none\" (most dreams). stance: how the dream turns them toward that house, from -1 (against it) to +1 (for it); 0 if "
    "none.")

INTERPRET_SCHEMA = {
    "type": "object",
    "properties": {
        "retelling": {"type": "string", "maxLength": 240},
        "interpretation": {"type": "string", "maxLength": 240},
        "confidence": {"type": "number"},
        "about_house": {"type": "string", "enum": ["none"] + HOUSE_NAMES},
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


def person_sketch(con, p, year=None, season=None) -> str:
    """Who is reading the dream: their house and its right, how their house feels about the others, their
    own beliefs (the Flight first), their drives this season, temperament and traits."""
    house = one(con, "select h.id, h.name, h.claim from houses h join house_members m on m.house_id = h.id where m.person_id = ?", p["id"])
    role = one(con, "select role from house_members where person_id = ?", p["id"])["role"]
    traits = ", ".join(f"{k} {p[k]:.1f}" for k in ("openness", "caution", "warmth", "pride", "piety"))
    flight = one(con, "select id from events where kind = 'departure'")
    fb = rows(con, "select interpretation, confidence from beliefs where holder_id = ? and subject_type = 'event' and subject_id = ? "
                   "order by confidence desc limit 2", p["id"], str(flight["id"])) if flight else []
    other = rows(con, "select interpretation from beliefs where holder_id = ? and not (subject_type = 'event' and subject_id = ?) "
                      "order by confidence desc limit 3", p["id"], str(flight["id"]) if flight else "")
    feel = rows(con, "select hh.name, sum(b.stance * b.confidence) / sum(b.confidence) f from beliefs b join house_members m "
                     "on m.person_id = b.holder_id join houses hh on hh.id = b.about_house where m.house_id = ? and b.stance is not null "
                     "and b.about_house != ? group by hh.name order by f", house["id"], house["id"])
    drives = rows(con, "select text from drives where person_id = ? and year = ? and season = ?", p["id"], year, season) if year is not None else []
    lines = [f"{p['name']}, {role} of House {house['name']} (its right: {house['claim']})"
             f"{'; ' + p['note'] if p.get('note') else ''}. Temperament: {p['dream_temperament']}. Traits: {traits}."]
    if feel:
        cold = [f"{f['name']} ({f['f']:+.1f})" for f in feel if f["f"] < -0.2][:3]
        warm = [f"{f['name']} ({f['f']:+.1f})" for f in feel[::-1] if f["f"] > 0.2][:2]
        if cold:
            lines.append("House " + house["name"] + " is cold toward: " + ", ".join(cold) + ".")
        if warm:
            lines.append("It is warm toward: " + ", ".join(warm) + ".")
    if fb:
        lines.append("About the Flight they believe: " + " / ".join(f"{b['interpretation']} ({b['confidence']:.0%} sure)" for b in fb))
    if other:
        lines.append("They also believe: " + " / ".join(b["interpretation"] for b in other))
    if drives:
        lines.append("This season they want to: " + "; ".join(d["text"] for d in drives))
    return "\n".join(lines)


def interpret(con, R, shared, llm, clock, year, season):
    """The most-shared dreams of the season, each read by its dreamer (and taken up by the first listener).

    Checks on every reading, each with a retry that says what was wrong:
      * out of this world: modern words, real-world peoples, places and gods (world/anachronism.py) in the
        retelling, reading or intention. If they survive the retries, the sentences holding them are cut;
      * the same reading as someone else's: readings this season are compared by meaning (embeddings,
        cosine similarity); a near-copy is asked again, as this particular person's temperament would read it.
    """
    from world import anachronism
    I = R["interpretation"]
    houses = {h["name"]: h["id"] for h in rows(con, "select id, name from houses")}

    def salience(d):
        t = d["text"].lower()
        return d["vividness"] + 0.15 * sum(k in t for k in FLIGHT_IMAGES) + (0.3 if d["person"]["tier"] == "principal" else 0) \
            + (0.2 if d["temper"] == "mystic" else 0)

    # only the most-shared dreams (told to the most people), the most salient first among equals
    chosen = sorted(shared, key=lambda d: (len(d.get("told", [d.get("listener")])), salience(d)), reverse=True)[: I["max_per_season"]]
    embed_fn = None
    try:
        from engine.memory.embed import embed as embed_fn
    except Exception:  # noqa: BLE001  (no sentence-transformers: the duplicate check is skipped, and said so in the log)
        pass
    seen_vecs = []
    if embed_fn:   # readings of the last seasons count too: the same reading twice in a row is just as dull
        prev = [b["interpretation"] for b in rows(con, "select distinct interpretation from beliefs where subject_type = 'dream' "
                                                       "and source_type = 'own_dream' order by id desc limit 16")]
        if prev:
            seen_vecs = list(embed_fn(prev))
    out = []
    for d in chosen:
        p = one(con, "select * from people where id = ?", d["person"]["id"])
        listener = one(con, "select * from people where id = ?", d["listener"])
        house = one(con, "select h.name from houses h join house_members m on m.house_id = h.id where m.person_id = ?", p["id"])["name"]
        base = (f"The person:\n{person_sketch(con, p, year, season)}\n\nThe dream they had this {season} and told to "
                f"{listener['name']}:\n\"{d['text'][:700]}\"")
        note, j, checks = "", {}, []
        for attempt in range(1 + I["retries"]):
            clock.calls += 1
            j = llm.json(INTERPRET_SYSTEM, base + note, INTERPRET_SCHEMA, max_new_tokens=I["max_new_tokens"]) or {}
            text = str(j.get("interpretation") or "").strip()
            if not text:
                checks.append("unreadable")
                note = "\n(Your last reply could not be used. Answer in the JSON asked for.)"
                continue
            said = " ".join(str(j.get(k) or "") for k in ("retelling", "interpretation", "intention"))
            bad = anachronism.find(said)
            if bad:
                checks.append("out of this world: " + ", ".join(bad))
                note = (f"\n(Your last reply used words that do not exist in Corva: {', '.join(bad)}. Corva has no such things, "
                        "peoples or places. Say what this person would see instead, in Corva's own terms, or leave it out.)")
                continue
            if embed_fn and seen_vecs:
                v = embed_fn([text])[0]
                sim = max(float(v @ w) for w in seen_vecs)
                if sim > I["duplicate_similarity"]:
                    checks.append(f"near-copy of another reading ({sim:.2f})")
                    note = (f"\n(Your last reading was almost the same as someone else's this season. Read the dream as THIS person "
                            f"would: a {p['dream_temperament']} of House {house}, from their own house's interests, grudges and "
                            f"fears, and their own belief about the Flight. Say something only they would say.)")
                    continue
            break
        text = str(j.get("interpretation") or "").strip()
        retelling = str(j.get("retelling") or "").strip()
        intention = str(j.get("intention") or "").strip()
        if anachronism.find(" ".join((text, retelling, intention))):   # still there after the retries: cut those sentences
            checks.append("cut sentences that were out of this world")
            text, retelling, intention = anachronism.strip(text), anachronism.strip(retelling), anachronism.strip(intention)
        if not text:
            out.append({"dream": d, "raw": getattr(llm, "last_raw", ""), "ok": False, "checks": checks, "house": house})
            continue
        if embed_fn:
            seen_vecs.append(embed_fn([text])[0])
        try:
            conf = max(0.05, min(1.0, float(j.get("confidence") or 0.5)))
        except (TypeError, ValueError):
            conf = 0.5
        about = houses.get(str(j.get("about_house") or ""))
        try:
            stance = max(-1.0, min(1.0, float(j.get("stance")))) if about else None
        except (TypeError, ValueError):
            stance = None
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
        if intention and intention.lower() not in ("null", "none", ""):
            insert(con, "memories", year=year, season=season, person_id=p["id"], source_type="dream", source_id=d["id"],
                   text=f"I mean to: {intention}", vividness=0.8)
        out.append({"dream": d, "retelling": retelling, "interpretation": text, "confidence": conf,
                    "about": j.get("about_house") if about else None, "stance": stance, "intention": intention or None,
                    "listener": listener["name"], "house": house, "told": len(d.get("told", [1])), "checks": checks,
                    "dedupe": bool(embed_fn), "ok": True})
    return out


def record_calls(con, year, season, step, calls):
    """Each model call's size and time (the season log's profile: is the storyteller staying under ~50 s?)."""
    for c in calls:
        insert(con, "model_calls", year=year, season=season, step=step, **c)
    calls.clear()


def lean_by_house(interp) -> dict:
    """Which way each interpreting house's readings leaned: toward which houses, how warmly, how often 'none'."""
    out = defaultdict(lambda: {"readings": 0, "none": 0, "toward": defaultdict(list)})
    for it in interp:
        if not it.get("ok"):
            continue
        L = out[it["house"]]
        L["readings"] += 1
        if it.get("about") and it.get("stance") is not None:
            L["toward"][it["about"]].append(it["stance"])
        else:
            L["none"] += 1
    return {h: {"readings": L["readings"], "about no house": L["none"],
                "toward": {t: {"n": len(v), "mean_stance": round(sum(v) / len(v), 2)} for t, v in L["toward"].items()}}
            for h, L in out.items()}


# --- 5. propose ---------------------------------------------------------------------------------------------
EXAMPLE_ACTIONS = ["search", "accuse", "bribe", "spread a rumour", "feast", "propose a marriage", "threaten",
                   "form an alliance", "pray", "flee", "investigate", "confess"]
STORY_SYSTEM = (
    "You are the storyteller of Corva, an old island city of ten noble houses, in an age of oars and sails. You do not "
    "decide what happens: you propose what ONE house's people might do this season, and the world's rules decide whether "
    "it works. First answer the strategy question about the Flight (Livia Corvane and Soren of the Harbor vanished at the "
    "autumn festival). Then propose up to {n} actions, driven by the members' drives. EACH PERSON ACTS AT MOST ONCE A SEASON: "
    "if the house does two things, two different people carry them out (the head, the heir, a cousin, a retainer, by their "
    "id, e.g. \"p12\"), or the house acts as a group (its id, e.g. \"h3\": the family together) or through its clients "
    "(e.g. \"c3\": the townsfolk who owe it loyalty). Nobody acts against themselves or their own house. "
    "Any action a person of that age could take is allowed; some "
    "ideas: {examples}. Prefer actions not already taken this season by other houses. Say only what people DO, never what "
    "anything means (no omens, signs, fate or the will of the gods). Use the true family ties given; do not invent others.")


def proposal_schema(actor_ids, target_ids, place_names, n):
    return {
        "type": "object",
        "properties": {
            "strategy": {"type": "string", "maxLength": 150},
            "proposals": {"type": "array", "minItems": 1, "maxItems": n, "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "maxLength": 40},
                    "actor": {"type": "string", "enum": actor_ids},
                    "target": {"type": "string", "enum": target_ids + ["none"]},
                    "place": {"type": "string", "enum": place_names + ["none"]},
                    "why": {"type": "string", "maxLength": 110},
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
    lines.append(f"Groups that can act: h{h['id']} (House {h['name']} as a family), c{h['id']} (its {clients['count']} clients).")
    lines.append("Other houses: " + ", ".join(f"h{o['id']} {o['name']}" for o in others) + ".")
    lines.append("Notable people of other houses: " + ", ".join(f"p{p['id']} {p['name']} ({p['house']})" for p in principals_elsewhere) + ".")
    if legends:   # the house's own legend first, each cut to a sentence or two (context budget)
        lines.append("Legends the house tells: " + " | ".join(f"{l['title']}: {l['text'][:R['storyteller']['legend_chars']]}" for l in legends))
    if feel:
        lines.append("How the house feels toward others (-1 to 1): " + ", ".join(f"{f['name']} {f['f']:+.2f}" for f in feel))
    # family ties: only this house's own people (the storyteller needs its own family right; other houses' ties
    # were 400+ tokens a call and rarely used)
    ties = [t for t in true_ties(con, [m["id"] for m in adults]) if any(m["name"] in t for m in adults)]
    lines.append("True family ties: " + "; ".join(ties[:R['storyteller']['max_ties']]) + ".")
    lines.append("Recent events in Corva: " + " ".join(last_events))
    if used_kinds:
        lines.append("Already done this season by other houses: " + ", ".join(f"{k} x{n}" for k, n in used_kinds.most_common()) + ".")
    lines.append(f"Strategy question: what is House {h['name']} trying to achieve about the Flight this season, and why?")
    lines = trim_context(lines, R["storyteller"]["max_context_tokens"])
    actor_ids = [f"p{m['id']}" for m in adults] + [f"h{h['id']}", f"c{h['id']}"]
    target_ids = [f"h{o['id']}" for o in others] + [f"p{p['id']}" for p in principals_elsewhere] + \
                 [f"p{m['id']}" for m in members if m["id"] not in {a["id"] for a in adults}] + [f"p{m['id']}" for m in adults]
    places = [p["name"] for p in rows(con, "select name from places where kind != 'house'")]
    return "\n".join(lines), actor_ids, sorted(set(target_ids)), places


_TOK = None


def ntokens(text: str) -> int:
    """Tokens in the storyteller's own tokenizer (loaded once; the tokenizer alone is small and quick)."""
    global _TOK
    if _TOK is None:
        from transformers import AutoTokenizer
        _TOK = AutoTokenizer.from_pretrained(load_rules()["storyteller"]["model"])
    return len(_TOK(text)["input_ids"])


TRIM_ORDER = ("Legends the house tells", "True family ties", "Recent events in Corva", "Notable people of other houses",
              "How the house feels")


def trim_context(lines: list[str], budget: int) -> list[str]:
    """Keep a house's context under the token budget as history grows: shorten its least needed parts first
    (legends, then family ties, then recent events, then the list of other houses' notable people), each by
    half, until it fits. The members, their drives, the house's state and the strategy question are never cut."""
    for _ in range(12):
        if ntokens("\n".join(lines)) <= budget:
            return lines
        for key in TRIM_ORDER:
            i = next((j for j, l in enumerate(lines) if l.startswith(key)), None)
            if i is not None and len(lines[i]) > 120:
                head, _, body = lines[i].partition(": ")
                cut = body[: len(body) // 2]
                lines[i] = f"{head}: {cut.rsplit(';', 1)[0].rsplit('.', 1)[0].rsplit(',', 1)[0]}…"
                break
        else:
            return lines
    return lines


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
HOSTILE = {"accuse", "threaten", "demand", "rumor", "insult"}    # never turned on one's own house
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
    if ref.startswith("c") and ref[1:].isdigit():
        r = one(con, "select * from houses where id = ?", int(ref[1:]))
        return ("clients", r) if r else (None, None)
    return None, None


def group_actor(con, R, h, kind: str, year: int) -> dict:
    """A house acting as a group (the family together, or its clients): a stand-in 'person' whose traits are
    the average of the house's adults (clients: middling), with no id, so it uses up no one's one action."""
    adults = [m for m in people(con, "h.id = ? and p.absent = 0 and p.alive = 1", h["id"]) if age(m, year) >= R["population"]["adult_age"]]
    traits = {k: (sum(m[k] for m in adults) / len(adults) if adults and kind == "house" else 0.5)
              for k in ("openness", "caution", "warmth", "pride", "piety")}
    name = f"House {h['name']}" if kind == "house" else f"the clients of House {h['name']}"
    return {"id": None, "name": name, "house_id": h["id"], "alive": 1, "absent": 0, "born_year": -100, "group": kind, **traits}


def stand_in(con, R, h, busy: set, avoid: set, year: int):
    """Someone else of the house to carry out an action whose named actor already acts this season: the heir first,
    then other adults (side characters before principals). None if everyone able has acted."""
    order = {"heir": 0, "member": 1, "cousin": 1, "retainer": 2, "servant": 3, "head": 4}
    cands = [m for m in people(con, "h.id = ? and p.absent = 0 and p.alive = 1", h["id"])
             if age(m, year) >= R["population"]["adult_age"] and m["id"] not in busy and m["id"] not in avoid]
    if not cands:
        return None
    cands.sort(key=lambda m: (order.get(m["role"], 1), m["tier"] == "principal", m["id"]))
    c = cands[0]
    return one(con, "select p.*, m.house_id from people p join house_members m on m.person_id = p.id where p.id = ?", c["id"])


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
            group_key = None
            if akind in ("house", "clients"):  # the house as a family, or its clients: a group action, no one's turn
                if actor and actor["id"] != h["id"]:
                    actor = None                 # another house's group: not this house's to command
                else:
                    group_key = f"{akind}:{h['id']}"
                    actor = group_actor(con, R, h, akind, year) if actor else None
            # nobody acts against themselves, or (in a hostile act) against their own house's people
            own_target = (target is not None and tkind == "person" and actor is not None and
                          (target["id"] == actor.get("id") or (family in HOSTILE and target["house_id"] == h["id"])))
            stood_in = None
            if actor and not own_target and group_key and group_key in acted:
                # the house (or its clients) already acted together this season: a free member carries this one out
                sub = stand_in(con, R, h, acted, {target["id"]} if tkind == "person" and target else set(), year)
                if sub:
                    stood_in, actor, group_key = actor["name"] + " (as a group)", sub, None
            elif actor and not own_target and not group_key and V["one_action_per_actor"] and actor["id"] in acted and actor["house_id"] == h["id"]:
                # one action per person per season: someone else of the house carries it out, or the house as a group
                sub = stand_in(con, R, h, acted, {target["id"]} if tkind == "person" and target else set(), year)
                if sub:
                    stood_in, actor = actor["name"], sub
                elif f"house:{h['id']}" not in acted:
                    stood_in, group_key, actor = actor["name"], f"house:{h['id']}", group_actor(con, R, h, "house", year)
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
            elif own_target:
                status, reason, rule = ("rejected", f"{actor['name']} cannot aim this at themselves", "aimed at self") \
                    if target["id"] == actor.get("id") else \
                    ("rejected", f"{actor['name']} cannot turn this against {target['name']}, of their own house", "aimed at own house")
            elif target and tkind == "house" and target["id"] == h["id"] and family in NEEDS_TARGET:
                status, reason, rule = "rejected", "a house cannot aim this at itself", "aimed at itself"
            elif V["one_action_per_actor"] and (group_key in acted if group_key else actor["id"] in acted):
                status, reason, rule = "rejected", f"{actor['name']} already acts this season, and nobody else of the house is free", "already acting"
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
                    acted.add(group_key or actor["id"])
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
                                                    pronoun="their own" if group_key else "their")
                    text = text[0].upper() + text[1:]
                    if family == "search":
                        text += " and found a trace of them." if sealed_hit else " and found no trace of them."
                    else:
                        text += OUTCOME_TAIL[outcome]
                    involved = [h["id"]] + ([thouse["id"]] if thouse and thouse["id"] != h["id"] else [])
                    ev = insert(con, "events", year=year, season=season, kind=family, place_id=place["id"] if place else None,
                                actors=([actor["id"]] if actor["id"] else []) + ([target["id"]] if tkind == "person" else []), houses=involved,
                                outcome=outcome, facts=facts, text=text, sealed=1 if sealed_hit else 0)
                    status = {"success": "accepted", "partial": "partial", "failure": "failed"}[outcome]
                    reason = f"rolled {roll:.2f} against {chance:.2f}"
                    if stood_in:
                        reason += f"; carried out by {actor['name']}, as {stood_in} already acts this season"
                        payload["stood_in_for"] = stood_in
                    effects(con, R, family, outcome, h, thouse, actor, target if tkind == "person" else None, ev, year, season, r)
                    move_actors(con, ([actor["id"]] if actor["id"] else []) + ([target["id"]] if tkind == "person" else []), place)
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
    # a group action (the house as a family, or its clients) has no single actor: its head remembers it
    holder = actor["id"] or h["head_id"]
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
            insert(con, "beliefs", year=year, season=season, holder_id=holder, subject_type="event", subject_id=str(ev),
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
    if not actor["id"]:
        return                           # what follows only a person can do (leave, confess, learn a secret)
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
        "carried_out_by_another_member": sum(1 for x in results if "carried out by" in (x["reason"] or "")),
        "group_actions": sum(1 for x in results if str((x["proposal"] or {}).get("actor", "")).startswith(("h", "c"))),
        "interpretation_lean": lean_by_house(interp),
        "interpretation_checks": dict(Counter(c.split(":")[0].split(" (")[0] for i in interp for c in (i.get("checks") or []))),
        "clients": clients,
        "coldest_feelings": sorted(({"from": f["a"], "to": f["b"], "feeling": round(f["f"], 2)} for f in feelings), key=lambda x: x["feeling"])[:6],
        "warmest_feelings": sorted(({"from": f["a"], "to": f["b"], "feeling": round(f["f"], 2)} for f in feelings), key=lambda x: -x["feeling"])[:4],
        "runtime": {name: round(s, 1) for name, s, _ in clock.log}, "model_calls": clock.calls,
    }
    insert(con, "vital_signs", year=year, season=season, stats=stats)
    return stats
