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

import re

from world.db import ROOT, one, rows

VOICE_SYSTEM = (
    "You are a person of Corva, an old island city ruled by ten noble houses, writing in your private journal at the end "
    "of a season. Write ONLY in the first person (\"I\", \"my house\"), 110 to 150 words, plain and concrete, in the "
    "manner of an older age (no modern words). Say what you did or saw, what you heard, and what you think it means for "
    "you and your house. Use ONLY the facts you are given: do not invent people, houses, titles, family ties or events, "
    "and use the true family ties given (never invent a wife, husband, son or brother). Never write your own name and "
    "never call yourself \"he\" or \"she\": you are always \"I\". Corva knows nothing modern; if a dream held strange "
    "things, describe them as you would. Your opinions are your own and may be wrong. Do not begin with the date.")
TOWN_SYSTEM = (
    "You are an unnamed townsperson of Corva, an old island city ruled by ten noble houses, gossiping at the market at "
    "the end of a season. 90 to 130 words, in the first person, plain and lively, in the manner of an older age (no modern "
    "words). Talk about the vanished lovers Livia Corvane and Soren of the Harbor, about what the great houses did this "
    "season, and about the strange dreams going round. Use ONLY the facts and rumours given; do not invent names or events. "
    "Corva knows nothing modern: describe any strange dream-images in Corva's own terms (a car is 'a beast of iron that "
    "ran without horses'). Rumours may be wrong.")


def finish(text: str) -> str:
    """Cut a reply back to its last full sentence (the model sometimes runs out of room mid-sentence)."""
    text = text.strip()
    m = re.search(r"^(.*[.!?][\"')\]]?)", text, re.S)
    return m.group(1).strip() if m else text


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
    dream = one(con, "select m.text, b.interpretation from memories m left join beliefs b on b.subject_id = m.source_id and b.holder_id = m.person_id "
                     "where m.person_id = ? and m.year = ? and m.season = ? and m.text like '(as told)%' order by m.id limit 1", p["id"], year, season)
    from world.tick import true_ties
    mentioned = [p["id"]] + [a for e in evs for a in json.loads(e["actors"])]
    ties = true_ties(con, mentioned)
    user = (f"You are {p['name']} of House {p['house']}, {year - p['born_year']} years old: {p['note'] or 'a member of the house'}.\n"
            f"It is the end of the first {season} since Livia Corvane and Soren of the Harbor vanished at the autumn festival of the sea.\n"
            f"What you and your house did, or had done to you, this {season}: " + (" ".join(seen) or "nothing of note.") + "\n"
            f"What you heard of elsewhere in the city: " + (" ".join(heard) or "little.") + "\n"
            f"What you believe: " + " / ".join(b["interpretation"] for b in beliefs) + "\n" +
            (f"A dream you remember from this {season}, as you tell it: \"{dream['text'][len('(as told) '):][:300]}\"" +
             (f" (what you made of it: {dream['interpretation']})" if dream["interpretation"] else "") + "\n" if dream else "") +
            "True family ties of the people above: " + "; ".join(ties[:20]) + ".")
    first = p["name"].split()[0]
    text = ""
    for attempt in range(2):
        clock.calls += 1
        text = finish(llm.chat(VOICE_SYSTEM, user, max_new_tokens=360))
        third = re.search(rf"\b{re.escape(first)}\b", text) or re.search(r"^(He|She) ", text, re.M)
        if not third:
            break
        user += f"\n(Rewrite entirely in the first person: you are {first}, so say \"I\", never \"{first}\" or \"he\" / \"she\".)"
    # stored as this author's own account: their claims, never facts about the world
    from world.db import insert
    insert(con, "chronicles", year=year, season=season, author_id=p["id"], events=[e["id"] for e in evs if not e["sealed"]],
           text=text, kind="account")
    return text


def town_talk(con, llm, year, season, clock):
    evs = [event_line(e) for e in season_events(con, year, season) if not e["sealed"]]
    rumors = rows(con, "select text from dreams where kind = 'rumor' and year = ? and season = ?", year, season)
    told = rows(con, "select text from memories where year = ? and season = ? and text like '(as told)%' and told_by is not null limit 3", year, season)
    user = ("What happened this season: " + " ".join(evs[:10]) + "\n"
            "Old talk still going round: Soren carried her off; no, she went willingly; the Therens arranged it; a sailor saw a "
            "boat sailing east; a merchant says the northern road; old Philo saw two figures at the western gate.\n"
            "Dreams going round the town, nobody knows whose: " + " / ".join(f"\"{r['text'][:160]}\"" for r in rumors) + "\n" +
            ("Dreams people told each other: " + " / ".join(t["text"][len("(as told) "):] for t in told) if told else ""))
    clock.calls += 1
    text = finish(llm.chat(TOWN_SYSTEM, user, max_new_tokens=260))
    from world.db import insert
    insert(con, "chronicles", year=year, season=season, author_id=None, text=text, kind="talk")
    return text


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
    told = rows(con, "select d.id, d.tag, p.name dreamer, h.name house, b.interpretation, b.confidence, d.shared_with, m2.text retold "
                     "from dreams d join people p on p.id = d.dreamer_id join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                     "join beliefs b on b.subject_id = d.id and b.holder_id = d.dreamer_id and b.source_type = 'own_dream' "
                     "left join memories m2 on m2.source_id = d.id and m2.person_id = d.dreamer_id and m2.text like '(as told)%' "
                     "where d.year = ? and d.season = ? and p.absent = 0 order by b.confidence desc", year, season)
    n_told = one(con, "select count(*) n from dreams where year = ? and season = ? and shared_with != '[]'", year, season)["n"]
    lines += ["## Dreams that were told", "",
              f"*Everyone dreamed. Most dreams were forgotten by morning; {n_told} were remembered and told to someone, and the "
              "most striking of those were taken to heart. Each is given as the dreamer told it, with what they made of it.*", ""]
    for d in told:
        listener = one(con, "select name from people where id = ?", json.loads(d["shared_with"])[0])["name"]
        lines += [f"**{d['dreamer']}** (House {d['house']}) told {listener}:", "",
                  f"> {(d['retold'] or '')[len('(as told) '):] or '(no retelling)'}", "",
                  f"What {d['dreamer'].split()[0]} made of it ({d['confidence']:.0%} sure): *{d['interpretation']}*", ""]
    path = ROOT / f"docs/chronicle_season{tick}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.relative_to(ROOT))


def write_log(con, year, season, tick, stats, interp, raw_failures, budget_seconds=3600) -> str:
    props = rows(con, "select s.*, h.name house from storyteller_proposals s join houses h on h.id = s.house_id where s.tick = ? order by s.id", tick)
    lines = [f"# Season {tick} log: {season}, year {year} (world engine v0, offline sandbox)", "",
             "The engine's side of the season: what drove people, what each house set out to do, what the storyteller "
             "proposed and what the world made of it, how long each step took, and the vital signs. (Never shown here: "
             "private truths, the sealed location, sealed events.)", ""]
    # drives
    lines += ["## Drives this season (principals in Corva)", "", "| Person | House | Drives |", "|---|---|---|"]
    for d in rows(con, "select p.name, h.name house, group_concat(d.text, '; ') drives from drives d join people p on p.id = d.person_id "
                       "join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                       "where d.year = ? and d.season = ? group by p.id order by h.id, p.id", year, season):
        lines.append(f"| {d['name']} | {d['house']} | {d['drives']} |")
    # strategies
    lines += ["", "## Each house's strategy about the Flight", ""]
    seen = set()
    for s_ in props:
        st = json.loads(s_["payload"]).get("strategy", "")
        if s_["house"] not in seen:
            seen.add(s_["house"])
            lines.append(f"- **{s_['house']}:** {st or '(none given)'}")
    # action types
    lines += ["", "## Action types", "",
              "The storyteller may name any action; the engine sorts each into a family to resolve it.", "",
              "| Family | Proposed | Resolved (became an event) |", "|---|---:|---:|"]
    fams = sorted(set(stats["action_types_proposed"]) | set(stats["action_types_resolved"]), key=lambda f: -stats["action_types_proposed"].get(f, 0))
    for f in fams:
        lines.append(f"| {f} | {stats['action_types_proposed'].get(f, 0)} | {stats['action_types_resolved'].get(f, 0)} |")
    lines += ["", "Actions as the storyteller named them: " + ", ".join(f"{k} ({v})" for k, v in sorted(stats["action_names_proposed"].items(), key=lambda x: -x[1])) + "."]
    # proposals
    lines += ["", "## Storyteller proposals", "",
              f"{len(props)} proposals from 10 houses (one call per house, the 3B model, schema-guided). Acceptance (success or "
              f"partial): {stats['acceptance_rate']:.0%}. Outcomes: " + ", ".join(f"{k} {v}" for k, v in stats["proposals"].items()) + ".", "",
              "| House | Action (family) | Actor | Target / place | Status | Why (the house's reason) | The engine's reason |", "|---|---|---|---|---|---|---|"]
    def name_of(ref):
        ref = str(ref or "")
        if ref.startswith("p") and ref[1:].isdigit():
            r = one(con, "select name from people where id = ?", int(ref[1:]))
            return r["name"] if r else ref
        if ref.startswith("h") and ref[1:].isdigit():
            r = one(con, "select name from houses where id = ?", int(ref[1:]))
            return f"House {r['name']}" if r else ref
        return "" if ref in ("none", "None") else ref
    for s_ in props:
        p = json.loads(s_["payload"])
        if "unparsed" in p:
            lines.append(f"| {s_['house']} | ? | | | **{s_['status']}** | | {s_['reason']} (`{s_['rule_broken']}`) |")
            continue
        tgt = " / ".join(x for x in (name_of(p.get("target")), "" if p.get("place") in (None, "none") else p.get("place")) if x)
        why = str(p.get("why") or "").replace("|", "/")[:150]
        eng = (s_["reason"] or "") + (f" (`{s_['rule_broken']}`)" if s_["rule_broken"] else "")
        lines.append(f"| {s_['house']} | {p.get('kind', '')} ({p.get('family', '?')}) | {name_of(p.get('actor'))} | {tgt} | **{s_['status']}** | {why} | {eng} |")
    if raw_failures:
        lines += ["", "Replies that could not be used (first 200 characters):", ""]
        lines += [f"- {h}: `{t[:200]}`" for h, t in raw_failures]
    # dreams
    lines += ["", "## Dream interpretations", "",
              "Raw dream (the run 5 model's words) beside the dreamer's own retelling in Corva's terms, and their reading.", "",
              "| Dreamer | Told to | Raw dream (start) | Retold | Reading | Sure | Toward | Intention |", "|---|---|---|---|---|---|---|---|"]
    for i in interp:
        raw = " ".join(i["dream"]["text"].split()[:22]).replace("|", "/")
        if not i["ok"]:
            lines.append(f"| {i['dream']['person']['name']} | | {raw}… | *(reply unusable)* | | | | |")
            continue
        if i["dream"]["person"]["absent"]:
            continue
        toward = f"{i['about']} {i['stance']:+.1f}" if i["stance"] is not None else ""
        lines.append(f"| {i['dream']['person']['name']} | {i['listener']} | {raw}… | {i['retelling'].replace('|', '/')} | "
                     f"{i['interpretation'].replace('|', '/')} | {i['confidence']:.0%} | {toward} | {(i['intention'] or '').replace('|', '/')} |")
    # runtime against the budget
    rt = rows(con, "select step, seconds, calls from runtimes where year = ? and season = ?", year, season)
    total = sum(r["seconds"] for r in rt)
    lines += ["", "## Runtime per step, against the 1-hour daily budget", "",
              "One day = one year = 4 seasons. Per season, then projected to a day (x4).", "",
              "| Step | Seconds | Model calls | Per day (x4) | Share of the 1-hour budget |", "|---|---:|---:|---:|---:|"]
    for r in rt:
        lines.append(f"| {r['step']} | {r['seconds']:.0f} | {r['calls']} | {r['seconds'] * 4 / 60:.1f} min | {r['seconds'] * 4 / budget_seconds:.0%} |")
    lines.append(f"| **total** | **{total:.0f}** | **{sum(r['calls'] for r in rt)}** | **{total * 4 / 60:.0f} min** | **{total * 4 / budget_seconds:.0%}** |")
    lines += ["", "## Vital signs", "", "```json", json.dumps({k: v for k, v in stats.items() if k != "runtime"}, indent=1), "```", ""]
    path = ROOT / f"docs/season{tick}_log.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.relative_to(ROOT))
