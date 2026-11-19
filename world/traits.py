"""Procedural personalities: what every person of Corva is like, so nobody has to write it by hand.

Each person has (people.traits, JSON; all PROPOSED unless the seed story fixes it):
  humors        the four humours, a mix that sums to 1: sanguine (cheerful, bold), choleric (proud, quick to anger),
                melancholic (brooding, dreamy, fearful), phlegmatic (calm, slow, steady)
  values        what they care about, 0..1 each: honor, faith, family, ambition, love, wealth
  dispositions  what life does to them, 0..1: fear, suspicion (they start from the humours and are pushed by events)
  quirks        one or two from QUIRKS (superstitious, a liar, generous to strangers, holds grudges, afraid of the sea...)
  seed_fixed    for the eight seed characters: which parts the seed story states (docs/seed_history.md)

The engine's older traits (openness, caution, warmth, pride, piety) and the dream voice (mystic, romantic,
traditionalist, sage, pragmatist, skeptic) are no longer chosen by hand: they are DERIVED from these (derive()),
and recomputed whenever the traits change. So everything that used temperament (dream tags and recall,
interpretation, drives, the chances of actions) now follows the humours, values and quirks.

Life shapes traits slowly (nudge()): famine makes a household more fearful, a betrayal more suspicious, a spouse's
death more melancholic... Every change is written to trait_changes with the event that caused it.
"""

from __future__ import annotations

import json
import random

from world.db import insert, one, rows

HUMORS = ["sanguine", "choleric", "melancholic", "phlegmatic"]
VALUES = ["honor", "faith", "family", "ambition", "love", "wealth"]
QUIRKS = ["superstitious", "a liar", "generous to strangers", "holds grudges", "afraid of the sea", "a gambler",
          "drinks too much", "vain", "a gossip", "keeps every promise", "fears the dark", "collects old things",
          "quick-tempered", "sharp-tongued", "dotes on children", "never forgets a face", "headstrong", "keeps secrets",
          "sings while working", "cannot keep still"]
# what each quirk does to the chance of an action family (small: a quirk colours a person, it doesn't rule them)
QUIRK_EFFECTS = {
    "superstitious": {"rite": 0.1}, "a liar": {"rumor": 0.1, "confess": -0.2}, "generous to strangers": {"gift": 0.1},
    "holds grudges": {"accuse": 0.05, "insult": 0.05}, "afraid of the sea": {"search": -0.1, "trade": -0.15, "flee": -0.2},
    "a gambler": {"bribe": 0.05}, "a gossip": {"rumor": 0.1}, "keeps every promise": {"alliance": 0.1, "marriage": 0.05},
    "quick-tempered": {"threaten": 0.05, "insult": 0.05}, "sharp-tongued": {"insult": 0.1}, "headstrong": {"flee": 0.1},
    "keeps secrets": {"confess": -0.15},
}
# each house's culture: the humours and values its children are nudged toward (PROPOSED)
HOUSE_CULTURE = {
    "Corvane": ({"choleric": 0.35, "phlegmatic": 0.3}, {"honor": 0.8, "family": 0.6, "ambition": 0.6}),
    "Valerius": ({"choleric": 0.4, "phlegmatic": 0.25}, {"honor": 0.9, "ambition": 0.7}),
    "Theren": ({"phlegmatic": 0.35, "sanguine": 0.3}, {"family": 0.85, "love": 0.6}),
    "Aurelian": ({"melancholic": 0.4, "phlegmatic": 0.3}, {"faith": 0.9, "family": 0.4}),
    "Marcellan": ({"sanguine": 0.4, "choleric": 0.25}, {"wealth": 0.9, "ambition": 0.6}),
    "Cassian": ({"choleric": 0.35, "phlegmatic": 0.3}, {"ambition": 0.7, "wealth": 0.6, "honor": 0.5}),
    "Severin": ({"phlegmatic": 0.45, "melancholic": 0.25}, {"honor": 0.8, "faith": 0.5}),
    "Damaris": ({"melancholic": 0.35, "phlegmatic": 0.3}, {"family": 0.7, "love": 0.6, "faith": 0.5}),
    "Veyra": ({"phlegmatic": 0.35, "choleric": 0.3}, {"family": 0.8, "honor": 0.6}),
    "Solenne": ({"melancholic": 0.45, "sanguine": 0.2}, {"honor": 0.7, "love": 0.6}),
}
VOICE_BIAS = {"mystic": 0.057, "romantic": -0.001, "traditionalist": -0.056, "sage": 0.048, "pragmatist": 0.009, "skeptic": -0.057}
VOICE_WORDS = {"mystic": "dreamy and devout", "romantic": "warm-hearted and wistful", "traditionalist": "dutiful and set in old ways",
               "sage": "calm and thoughtful", "pragmatist": "practical and driven", "skeptic": "doubting and wry"}


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def norm(h: dict) -> dict:
    t = sum(max(0.01, v) for v in h.values())
    return {k: round(max(0.01, h.get(k, 0)) / t, 3) for k in HUMORS}


def dominant(t: dict) -> str:
    return max(t["humors"], key=t["humors"].get)


def derive(t: dict) -> dict:
    """The engine's older numbers, from the traits: openness, caution, warmth, pride, piety (0..1) and the dream voice."""
    h, v, d, q = t["humors"], t["values"], t.get("dispositions", {}), set(t.get("quirks", []))
    fear, susp = d.get("fear", 0.3), d.get("suspicion", 0.3)
    out = {
        "openness": clamp(0.25 + 0.6 * h["sanguine"] + 0.2 * v["ambition"] + 0.15 * v["love"] - 0.25 * h["phlegmatic"] - 0.2 * fear),
        "caution": clamp(0.2 + 0.6 * h["phlegmatic"] + 0.25 * h["melancholic"] + 0.3 * fear - 0.25 * h["sanguine"]),
        "warmth": clamp(0.2 + 0.5 * h["sanguine"] + 0.25 * v["love"] + 0.2 * v["family"] - 0.3 * susp
                        + (0.1 if "generous to strangers" in q else 0)),
        "pride": clamp(0.15 + 0.7 * h["choleric"] + 0.3 * v["honor"] + 0.15 * v["ambition"] + (0.1 if "vain" in q else 0)),
        "piety": clamp(0.05 + 0.8 * v["faith"] + 0.15 * h["melancholic"] + (0.1 if "superstitious" in q else 0)),
    }
    voice = {
        "mystic": h["melancholic"] * 0.9 + v["faith"] * 0.7 + (0.4 if "superstitious" in q else 0),
        "romantic": h["sanguine"] * 1.3 + v["love"] * 0.9,
        "traditionalist": h["phlegmatic"] + v["honor"] * 0.6 + v["family"] * 0.4,
        "sage": h["phlegmatic"] * 0.7 + h["melancholic"] * 0.5 + (1 - v["ambition"]) * 0.4,
        "pragmatist": h["choleric"] * 0.6 + v["wealth"] * 0.7 + v["ambition"] * 0.5,
        "skeptic": h["choleric"] * 0.4 + (1 - v["faith"]) * 0.7 + susp * 0.5,
    }
    # small offsets, calibrated once on the year-1 population so the six voices come out about even (PROPOSED)
    for k, b in VOICE_BIAS.items():
        voice[k] += b
    out["dream_temperament"] = max(voice, key=voice.get)
    return {k: (round(x, 3) if isinstance(x, float) else x) for k, x in out.items()}


def describe(t: dict) -> str:
    """A short phrase for prompts: 'choleric and sanguine; cares most for honor and family; holds grudges'."""
    hs = sorted(t["humors"], key=t["humors"].get, reverse=True)
    vs = sorted(t["values"], key=t["values"].get, reverse=True)[:2]
    d = t.get("dispositions", {})
    extra = [w for w, k in (("fearful", "fear"), ("suspicious", "suspicion")) if d.get(k, 0) > 0.6]
    return (f"{hs[0]}" + (f" and {hs[1]}" if t["humors"][hs[1]] > 0.25 else "") + f"; cares most for {vs[0]} and {vs[1]}"
            + (f"; {', '.join(extra)}" if extra else "") + (f"; {', '.join(t.get('quirks', []))}" if t.get("quirks") else ""))


def from_legacy(p: dict, house: str, r: random.Random) -> dict:
    """Traits for someone made before traits existed, read from their old numbers so they stay the same person:
    sanguine from openness and warmth, choleric from pride, melancholic from a dreaming voice and caution,
    phlegmatic from caution; faith from piety, honor from pride; the rest from the house's culture and chance."""
    culture_h, culture_v = HOUSE_CULTURE.get(house, ({}, {}))
    voice = p.get("dream_temperament") or "sage"
    h = {"sanguine": 0.5 * p["openness"] + 0.5 * p["warmth"], "choleric": p["pride"],
         "melancholic": 0.4 * p["caution"] + (0.5 if voice in ("mystic", "romantic") else 0.1),
         "phlegmatic": 0.7 * p["caution"] + (0.3 if voice in ("traditionalist", "sage") else 0)}
    for k, w in culture_h.items():
        h[k] += w * 0.5
    v = {k: clamp(0.3 + r.gauss(0, 0.18) + 0.5 * (culture_v.get(k, 0) - 0.4)) for k in VALUES}
    v["faith"] = clamp(0.7 * p["piety"] + 0.3 * v["faith"])
    v["honor"] = clamp(0.6 * p["pride"] + 0.4 * v["honor"])
    t = {"humors": norm(h), "values": {k: round(x, 3) for k, x in v.items()},
         "quirks": r.sample(QUIRKS, 1 if r.random() < 0.6 else 2), "proposed": True}
    t["dispositions"] = {"fear": round(clamp(0.2 + 0.5 * t["humors"]["melancholic"] + r.gauss(0, 0.08)), 3),
                         "suspicion": round(clamp(0.2 + 0.4 * t["humors"]["choleric"] + r.gauss(0, 0.08)), 3)}
    return t


def blend(mother: dict | None, father: dict | None, house: str, r: random.Random) -> dict:
    """A newborn's traits: the parents' blended, with noise, nudged toward the house's culture."""
    parents = [x for x in (mother, father) if x]
    culture_h, culture_v = HOUSE_CULTURE.get(house, ({}, {}))
    if not parents:
        parents = [{"humors": {k: 0.25 for k in HUMORS}, "values": {k: 0.4 for k in VALUES}, "quirks": []}]
    h = {k: sum(p["humors"][k] for p in parents) / len(parents) + r.gauss(0, 0.08) + 0.3 * culture_h.get(k, 0)
         for k in HUMORS}
    v = {k: round(clamp(sum(p["values"][k] for p in parents) / len(parents) + r.gauss(0, 0.12)
                        + 0.25 * (culture_v.get(k, 0.4) - 0.4)), 3) for k in VALUES}
    inherited = [q for p in parents for q in p.get("quirks", []) if r.random() < 0.25]
    quirks = list(dict.fromkeys(inherited + r.sample(QUIRKS, 1)))[:2]
    t = {"humors": norm(h), "values": v, "quirks": quirks, "proposed": True}
    t["dispositions"] = {"fear": round(clamp(0.2 + 0.4 * t["humors"]["melancholic"]), 3),
                         "suspicion": round(clamp(0.2 + 0.3 * t["humors"]["choleric"]), 3)}
    return t


def save(con, pid: int, t: dict) -> None:
    """Store the traits and recompute everything derived from them."""
    d = derive(t)
    con.execute("update people set traits = ?, openness = ?, caution = ?, warmth = ?, pride = ?, piety = ?, dream_temperament = ? "
                "where id = ?", (json.dumps(t), d["openness"], d["caution"], d["warmth"], d["pride"], d["piety"],
                                 d["dream_temperament"], pid))


def load(con, pid: int) -> dict | None:
    r = one(con, "select traits from people where id = ?", pid)
    return json.loads(r["traits"]) if r and r["traits"] else None


def nudge(con, pid: int, changes: dict, year: int, season: str, event_id: int | None, reason: str) -> None:
    """Life pushes a person a little: changes like {"humors.melancholic": +0.08, "dispositions.fear": +0.05,
    "values.love": +0.03}. Humours are renormalised. Each change is logged with its cause (trait_changes)."""
    t = load(con, pid)
    if not t:
        return
    before = json.loads(json.dumps(t))
    for key, delta in changes.items():
        group, name = key.split(".")
        t.setdefault(group, {})
        t[group][name] = clamp(t[group].get(name, 0.3) + delta)
    t["humors"] = norm(t["humors"])
    t["values"] = {k: round(x, 3) for k, x in t["values"].items()}
    t["dispositions"] = {k: round(x, 3) for k, x in t.get("dispositions", {}).items()}
    save(con, pid, t)
    for key in changes:
        group, name = key.split(".")
        b, a = before.get(group, {}).get(name, 0.3), t[group][name]
        if round(a - b, 3):
            insert(con, "trait_changes", year=year, season=season, person_id=pid, trait=key, before=round(b, 3), after=round(a, 3),
                   event_id=event_id, reason=reason)


# --- what events do to people (PROPOSED sizes: slow; a life changes over years) ---------------------------------------
def on_event(con, ev: int, family: str, outcome: str, h: dict, thouse: dict | None, actor: dict, tperson: dict | None,
             year: int, season: str) -> None:
    targets = [tperson] if tperson else ([dict(m) for m in rows(con, "select p.id from people p join house_members m on "
                                                                 "m.person_id = p.id where m.house_id = ? and p.alive = 1 and p.absent = 0",
                                                                 thouse["id"])] if thouse else [])
    if family == "threaten" and outcome != "failure":
        for t in targets:
            nudge(con, t["id"], {"dispositions.fear": 0.03}, year, season, ev, f"threatened by House {h['name']}")
    if family in ("accuse", "rumor", "insult") and outcome != "failure" and thouse:
        from world.tick import feeling
        betrayed = feeling(con, thouse["id"], h["id"]) > 0.2      # accused by a house they trusted: a betrayal
        for t in targets:
            nudge(con, t["id"], {"dispositions.suspicion": 0.08 if betrayed else 0.03}, year, season, ev,
                  f"{'betrayed' if betrayed else 'slandered'} by House {h['name']}")
    if family == "marriage" and outcome == "success" and actor.get("id"):
        nudge(con, actor["id"], {"humors.sanguine": 0.03, "values.love": 0.03}, year, season, ev, "a marriage agreed")


def on_hunger(con, house: dict, year: int, season: str) -> None:
    """A house that could not feed itself: an event, and its people a little more fearful and more careful of wealth."""
    ev = insert(con, "events", year=year, season=season, kind="hunger", actors=[], houses=[house["id"]], outcome="failure",
                facts={}, text=f"House {house['name']} went hungry this {season}.")
    for m in rows(con, "select p.id from people p join house_members m on m.person_id = p.id where m.house_id = ? and "
                       "p.alive = 1 and p.absent = 0", house["id"]):
        nudge(con, m["id"], {"dispositions.fear": 0.04, "values.wealth": 0.02}, year, season, ev, "famine in the house")
    return ev


def on_death(con, dead: dict, ev: int, year: int, season: str) -> None:
    """A spouse grows more melancholic; children too, a little."""
    for s in rows(con, "select case when person_a = ? then person_b else person_a end other from relationships "
                       "where kind = 'spouse' and (person_a = ? or person_b = ?)", dead["id"], dead["id"], dead["id"]):
        nudge(con, s["other"], {"humors.melancholic": 0.1}, year, season, ev, f"the death of their spouse, {dead['name']}")
    for c in rows(con, "select child_id from lineage where parent_id = ?", dead["id"]):
        nudge(con, c["child_id"], {"humors.melancholic": 0.05}, year, season, ev, f"the death of their parent, {dead['name']}")
