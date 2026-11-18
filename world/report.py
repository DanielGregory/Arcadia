"""The season's reports: an in-world chronicle from several viewpoints, and the engine's log.

docs/chronicle_season<N>.md  in-world. The record of what happened (event text, from templates), then
                             accounts written in the first person by people of different houses,
                             each from only what that person saw or heard and their own beliefs, and
                             the dreams that were told and what their dreamers made of them.
docs/season<N>_log.md        the engine's side: every storyteller proposal (accepted, partial, failed,
                             rejected, with the reason or the rule broken), runtime per step, vital signs.

Never printed: private memories (the private truths), the sealed location, and any event the rules
sealed (a search that found a trace). Accounts are written from public beliefs and events only.
"""

from __future__ import annotations

import json

from world.db import ROOT, one, rows

VOICE_SYSTEM = (
    "You write one page of a private account kept by a person of Corva, an old island city of ten noble houses, at the end "
    "of a season. Write in the first person, in their voice, 120 to 170 words, plain and concrete, like a letter or a "
    "journal from an older age (no modern words). Use ONLY the events and beliefs you are given: do not invent new events, "
    "names or places. Their opinions are theirs and may be wrong. Do not reveal anything they could not know.")
TOWN_SYSTEM = (
    "You write what the townsfolk of Corva, an old island city, were saying at the end of a season: market talk, harbour "
    "talk, 100 to 140 words, in the voice of an unnamed townsperson. Use ONLY the events and rumours given; do not invent "
    "new events, names or places. Rumours may be wrong.")


def season_events(con, year, season):
    return rows(con, "select * from events where year = ? and season = ? order by id", year, season)


def event_line(e) -> str:
    return "[sealed: what this search turned up is known only to the world engine]" if e["sealed"] else e["text"]


def pick_viewpoints(con, year, season, n=4):
    """People of different houses, those touched by this season's events first; present, adult, alive."""
    touched = []
    for e in season_events(con, year, season):
        for a in json.loads(e["actors"]):
            touched.append(a)
    cands = rows(con, "select p.*, h.name house from people p join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                      "where p.alive = 1 and p.absent = 0 and p.tier = 'principal' and (? - p.born_year) >= 16", year)
    cands.sort(key=lambda p: (-touched.count(p["id"]), p["id"]))
    out, houses = [], set()
    for p in cands:
        if p["house"] in houses:
            continue
        out.append(p)
        houses.add(p["house"])
        if len(out) == n:
            break
    return out


def account(con, llm, p, year, season, clock):
    evs = season_events(con, year, season)
    seen = [event_line(e) for e in evs if not e["sealed"] and (p["id"] in json.loads(e["actors"]) or
            one(con, "select house_id from house_members where person_id = ?", p["id"])["house_id"] in json.loads(e["houses"]))]
    heard = [event_line(e) for e in evs if not e["sealed"] and event_line(e) not in seen][:5]
    beliefs = rows(con, "select interpretation from beliefs where holder_id = ? order by year desc, confidence desc limit 4", p["id"])
    dream = one(con, "select d.text, b.interpretation from dreams d left join beliefs b on b.subject_id = d.id and b.holder_id = d.dreamer_id "
                     "where d.dreamer_id = ? and d.year = ? and d.season = ? and d.recalled = 1", p["id"], year, season)
    user = (f"The writer: {p['name']} of House {p['house']}, {year - p['born_year']} years old ({p['note'] or 'of the house'}).\n"
            f"The season: {season} of year {year}, the first season after Livia Corvane and Soren of the Harbor vanished at the autumn festival.\n"
            f"What their house did or had done to it this season: " + (" ".join(seen) or "nothing of note.") + "\n"
            f"What they heard of elsewhere in the city: " + (" ".join(heard) or "little.") + "\n"
            f"What they believe: " + " / ".join(b["interpretation"] for b in beliefs) + "\n" +
            (f"A dream they remember from this season: \"{dream['text'][:300]}\"" + (f" (what they made of it: {dream['interpretation']})" if dream["interpretation"] else "") if dream else ""))
    clock.calls += 1
    return llm.chat(VOICE_SYSTEM, user, max_new_tokens=300)


def town_talk(con, llm, year, season, clock):
    evs = [event_line(e) for e in season_events(con, year, season) if not e["sealed"]]
    rumors = rows(con, "select text from dreams where kind = 'rumor' and year = ? and season = ?", year, season)
    clients = rows(con, "select h.name, c.count, c.loyalty, c.gained, c.lost from house_clients c join houses h on h.id = c.house_id "
                        "where c.year = ? and c.season = ?", year, season)
    user = ("What happened this season: " + " ".join(evs[:10]) + "\n"
            "Dreams going round the town, nobody knows whose: " + " / ".join(f"\"{r['text'][:200]}\"" for r in rumors) + "\n"
            "Which houses gained or lost townsfolk: " + ", ".join(f"{c['name']} {c['gained'] - c['lost']:+d}" for c in clients if c["gained"] or c["lost"]))
    clock.calls += 1
    return llm.chat(TOWN_SYSTEM, user, max_new_tokens=240)


def write_chronicle(con, llm, year, season, tick, clock) -> str:
    evs = season_events(con, year, season)
    lines = [f"# The Chronicle of Corva: {season.title()}, Year {year}", "",
             "*Season " + str(tick) + " of the world engine's sandbox (offline). Written in-world. The record below is the "
             "engine's own account (facts, from templates). The accounts after it are what particular people of Corva "
             "made of the season: their words, their beliefs, possibly wrong.*", "",
             "## The record", ""]
    lines += [f"- {event_line(e)}" for e in evs] or ["- Nothing was recorded."]
    lines += ["", "## Accounts", ""]
    for p in pick_viewpoints(con, year, season):
        text = account(con, llm, p, year, season, clock)
        lines += [f"### {p['name']}, of House {p['house']}", "", text.strip(), ""]
    lines += ["### What the town was saying", "", town_talk(con, llm, year, season, clock).strip(), ""]
    told = rows(con, "select d.id, d.text, d.tag, p.name dreamer, h.name house, b.interpretation, b.confidence, d.shared_with "
                     "from dreams d join people p on p.id = d.dreamer_id join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                     "left join beliefs b on b.subject_id = d.id and b.holder_id = d.dreamer_id and b.source_type = 'own_dream' "
                     "where d.year = ? and d.season = ? and d.shared_with != '[]' and p.absent = 0 order by b.confidence is null, b.confidence desc", year, season)
    lines += ["## Dreams that were told", "",
              "*Everyone dreamed. Most dreams were forgotten by morning; these were remembered and told to someone. Only "
              "told dreams are interpreted, and the reading is the dreamer's own.*", ""]
    for d in told:
        listener = one(con, "select name from people where id = ?", json.loads(d["shared_with"])[0])["name"]
        lines += [f"**{d['dreamer']}** (House {d['house']}, in the voice of *{d['tag']}*) told {listener}:", "",
                  f"> {d['text'][:600]}", ""]
        if d["interpretation"]:
            lines += [f"What {d['dreamer'].split()[0]} made of it ({d['confidence']:.0%} sure): *{d['interpretation']}*", ""]
        else:
            lines += ["*(Not among the dreams interpreted this season.)*", ""]
    rumors = rows(con, "select text from dreams where kind = 'rumor' and year = ? and season = ?", year, season)
    if rumors:
        lines += ["## Rumour dreams", "", "*Dreams going round the town that nobody owns.*", ""]
        lines += [f"> {r['text'][:400]}\n" for r in rumors]
    path = ROOT / f"docs/chronicle_season{tick}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.relative_to(ROOT))


def write_log(con, year, season, tick, stats, interp, raw_failures) -> str:
    props = rows(con, "select s.*, h.name house from storyteller_proposals s join houses h on h.id = s.house_id where s.tick = ? order by s.id", tick)
    lines = [f"# Season {tick} log: {season}, year {year} (world engine v0, offline sandbox)", "",
             "The engine's side of the season: what the storyteller proposed and what the world made of it, how long each "
             "step took, and the vital signs. (Never shown here: private truths, the sealed location, sealed events.)", "",
             "## Storyteller proposals", "",
             f"{len(props)} proposals from 10 houses (one call per house). Acceptance (success or partial): "
             f"{stats['acceptance_rate']:.0%}. Outcomes: " + ", ".join(f"{k} {v}" for k, v in stats["proposals"].items()) + ".", "",
             "| House | Kind | Actor | Target | Status | Why (the house's reason) | The engine's reason |", "|---|---|---|---|---|---|---|"]
    for s in props:
        p = json.loads(s["payload"])
        if "unparsed" in p:
            lines.append(f"| {s['house']} | ? | | | **{s['status']}** | | {s['reason']} (`{s['rule_broken']}`) |")
            continue
        target = p.get("target_house") or p.get("target_person") or p.get("place") or ""
        why = str(p.get("why") or "").replace("|", "/")[:140]
        eng = (s["reason"] or "") + (f" (`{s['rule_broken']}`)" if s["rule_broken"] else "")
        lines.append(f"| {s['house']} | {p.get('kind', '')} | {p.get('actor', '')} | {target} | **{s['status']}** | {why} | {eng} |")
    if raw_failures:
        lines += ["", "Replies that could not be read as JSON (first 200 characters):", ""]
        lines += [f"- {h}: `{t[:200]}`" for h, t in raw_failures]
    lines += ["", "## Dream interpretations", "",
              "| Dreamer | Told to | Reading (the dreamer's) | Sure | Toward | Intention |", "|---|---|---|---|---|---|"]
    for i in interp:
        if not i["ok"]:
            lines.append(f"| {i['dream']['person']['name']} | | *(reply unreadable)* | | | |")
            continue
        if i["dream"]["person"]["absent"]:
            continue
        toward = f"{i['about']} {i['stance']:+.1f}" if i["stance"] is not None else ""
        lines.append(f"| {i['dream']['person']['name']} | {i['listener']} | {i['interpretation'].replace('|', '/')} | "
                     f"{i['confidence']:.0%} | {toward} | {(i['intention'] or '').replace('|', '/')} |")
    rt = rows(con, "select step, seconds, calls from runtimes where year = ? and season = ?", year, season)
    lines += ["", "## Runtime per step", "", "| Step | Seconds | Model calls |", "|---|---:|---:|"]
    lines += [f"| {r['step']} | {r['seconds']:.0f} | {r['calls']} |" for r in rt]
    lines.append(f"| **total** | **{sum(r['seconds'] for r in rt):.0f}** | **{sum(r['calls'] for r in rt)}** |")
    lines += ["", "## Vital signs", "", "```json", json.dumps({k: v for k, v in stats.items() if k != "runtime"}, indent=1), "```", ""]
    path = ROOT / f"docs/season{tick}_log.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.relative_to(ROOT))
