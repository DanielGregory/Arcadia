"""The reports: an in-world chronicle of each YEAR from several viewpoints, and the engine's log of each season.

docs/chronicle_year<Y>.md    in-world, one per year (since season 3; seasons 1 and 2 had one each). For every
                             season of the year: the record of what happened (event text, from templates)
                             and the dreams that were told, with what their dreamers made of them. Then,
                             once a year, accounts written in the first person by people of different
                             houses, each from only what that person saw or heard and their own beliefs,
                             and what the town was saying. (The model calls are once a year: runtime.)
docs/season<N>_log.md        the engine's side: every storyteller proposal (accepted, partial, failed,
                             rejected, with the reason or the rule broken), interpretations with their
                             checks and which way each house's readings leaned, runtime, vital signs.

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
    "and never invent a wife, husband, son or brother. The family ties you are given are REFERENCE ONLY, so that you do "
    "not get anyone wrong: never repeat them, list them or explain who is whose child. Never write your own name and "
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


TIE_SENTENCE = re.compile(
    r"\b(is|are|was|were)\s+(the\s+|my\s+|his\s+|her\s+|their\s+|our\s+)?(fostered\s+|eldest\s+|youngest\s+)?(child|children|son|daughter|married|wife|husband|head|heir|servant|retainer|"
    r"fosterling|betrothed|rivals?)\b|\b(teaches|'s child|'s children)\b", re.I)


def drop_ties(text: str) -> tuple[str, int]:
    """Background facts are reference only: cut any sentence that just restates who is whose (child of, married to,
    head of...). Returns the text and how many sentences were cut."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [x for x in parts if not TIE_SENTENCE.search(x)]
    return " ".join(kept).strip(), len(parts) - len(kept)


def year_events(con, year, upto_season=None):
    order = ["spring", "summer", "autumn", "winter"]
    evs = rows(con, "select * from events where year = ? order by id", year)
    if upto_season:
        evs = [e for e in evs if order.index(e["season"]) <= order.index(upto_season)] if upto_season in order else evs
    return evs


def account(con, llm, p, year, season, clock, evs=None, span=None):
    """One person's first-person account. evs: the events it covers (default: this season's); span: how to name the time."""
    evs = evs if evs is not None else season_events(con, year, season)
    span = span or f"this {season}"
    seen = [event_line(e) for e in evs if not e["sealed"] and (p["id"] in json.loads(e["actors"]) or
            one(con, "select house_id from house_members where person_id = ?", p["id"])["house_id"] in json.loads(e["houses"]))]
    heard = [event_line(e) for e in evs if not e["sealed"] and event_line(e) not in seen][:5]
    beliefs = rows(con, "select interpretation from beliefs where holder_id = ? order by year desc, confidence desc limit 4", p["id"])
    dream = one(con, "select m.text, b.interpretation from memories m left join beliefs b on b.subject_id = m.source_id and b.holder_id = m.person_id "
                     "where m.person_id = ? and m.year = ? and m.text like '(as told)%' order by m.id desc limit 1", p["id"], year)
    from world.tick import true_ties
    mentioned = [p["id"]] + [a for e in evs for a in json.loads(e["actors"])]
    ties = true_ties(con, mentioned)
    user = (f"You are {p['name']} of House {p['house']}, {year - p['born_year']} years old: {p['note'] or 'a member of the house'}.\n"
            f"It is the end of {span}, year {year} since the autumn Livia Corvane and Soren of the Harbor vanished at the festival of the sea.\n"
            f"What you and your house did, or had done to you, {span}: " + (" ".join(seen) or "nothing of note.") + "\n"
            f"What you heard of elsewhere in the city: " + (" ".join(heard) or "little.") + "\n"
            f"What you believe: " + " / ".join(b["interpretation"] for b in beliefs) + "\n" +
            (f"A dream you remember from {span}, as you tell it: \"{dream['text'][len('(as told) '):][:300]}\"" +
             (f" (what you made of it: {dream['interpretation']})" if dream["interpretation"] else "") + "\n" if dream else "") +
            "Reference only (never repeat these): family ties of the people above: " + "; ".join(ties[:20]) + ".")
    first = p["name"].split()[0]
    text = ""
    cut = 0
    for attempt in range(2):
        clock.calls += 1
        text = finish(llm.chat(VOICE_SYSTEM, user, max_new_tokens=360))
        text, cut = drop_ties(text)
        third = re.search(rf"\b{re.escape(first)}\b", text) or re.search(r"^(He|She) ", text, re.M)
        if not third and cut <= 1:
            break
        user += (f"\n(Rewrite entirely in the first person: you are {first}, so say \"I\", never \"{first}\" or \"he\" / \"she\"."
                 if third else "\n(Rewrite without listing who is whose child, wife or heir: those ties are only for reference.)")
    # stored as this author's own account: their claims, never facts about the world
    from world.db import insert
    insert(con, "chronicles", year=year, season=season, author_id=p["id"], events=[e["id"] for e in evs if not e["sealed"]],
           text=text, kind="account")
    ACCOUNT_CUTS.append((p["name"], cut))
    return text


ACCOUNT_CUTS = []   # (author, tie sentences cut from their final account), for the log


def town_talk(con, llm, year, season, clock, evs=None):
    evs = [event_line(e) for e in (evs if evs is not None else season_events(con, year, season)) if not e["sealed"]]
    rumors = rows(con, "select text from dreams where kind = 'rumor' and year = ? order by id desc limit 2", year)
    told = rows(con, "select text from memories where year = ? and text like '(as told)%' and told_by is not null order by id desc limit 3", year)
    user = ("What happened lately: " + " ".join(evs[-12:]) + "\n"
            "Old talk still going round: Soren carried her off; no, she went willingly; the Therens arranged it; a sailor saw a "
            "boat sailing east; a merchant says the northern road; old Philo saw two figures at the western gate.\n"
            "Dreams going round the town, nobody knows whose: " + " / ".join(f"\"{r['text'][:160]}\"" for r in rumors) + "\n" +
            ("Dreams people told each other: " + " / ".join(t["text"][len("(as told) "):] for t in told) if told else ""))
    clock.calls += 1
    text = finish(llm.chat(TOWN_SYSTEM, user, max_new_tokens=260))
    from world.db import insert
    insert(con, "chronicles", year=year, season=season, author_id=None, text=text, kind="talk")
    return text


def season_section(con, year, season) -> list[str]:
    """The templated part of a season (no model calls): the record of events and the dreams that were told."""
    evs = season_events(con, year, season)
    lines = [f"## {season.title()}", "", "### The record", ""]
    lines += [f"- {event_line(e)}" for e in evs] or ["- Nothing was recorded."]
    told = rows(con, "select d.id, d.tag, p.name dreamer, h.name house, b.interpretation, b.confidence, d.shared_with, m2.text retold "
                     "from dreams d join people p on p.id = d.dreamer_id join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                     "join beliefs b on b.subject_id = d.id and b.holder_id = d.dreamer_id and b.source_type = 'own_dream' "
                     "left join memories m2 on m2.source_id = d.id and m2.person_id = d.dreamer_id and m2.text like '(as told)%' "
                     "where d.year = ? and d.season = ? and p.absent = 0 order by b.confidence desc", year, season)
    n_told = one(con, "select count(*) n from dreams where year = ? and season = ? and shared_with != '[]'", year, season)["n"]
    lines += ["", "### Dreams that were told", "",
              f"*Everyone dreamed. Most dreams were forgotten by morning; {n_told} were remembered and told to someone, and the "
              "most talked-about were taken to heart. Each is given as the dreamer told it, with what they made of it.*", ""]
    for d in told:
        heard = json.loads(d["shared_with"])
        names = [one(con, "select name from people where id = ?", i)["name"] for i in heard]
        whom = names[0] + (f", and from them it went round to {', '.join(names[1:])}" if len(names) > 1 else "")
        lines += [f"**{d['dreamer']}** (House {d['house']}) told {whom}:", "",
                  f"> {(d['retold'] or '')[len('(as told) '):] or '(no retelling)'}", "",
                  f"What {d['dreamer'].split()[0]} made of it ({d['confidence']:.0%} sure): *{d['interpretation']}*", ""]
    return lines


CHRONICLER_SYSTEM = (
    "You are {name}, {title}, of House {house}, in Corva, an old island city ruled by ten noble houses, in an age of oars "
    "and sails. You keep a chronicle, and you are writing the history of {span}. Your manner: {voice}. Write {lo} to {hi} "
    "words of plain, grave prose, like an old chronicle; say \"I\" for yourself and \"we\" or \"my house\" for House "
    "{house}. Do not list every event: choose the four to six that matter most to your house and tell them as one story, "
    "with your judgement of each, taken ONLY from the record you are given (never invent an event, a person or a title). "
    "Tell it the way your house sees it: praise its friends, suspect its rivals, explain events in its favour, and hold to "
    "its beliefs about the Flight. Never mention numbers of believers, scores or this briefing. You may be wrong, and you "
    "never know where Livia Corvane and Soren of "
    "the Harbor are. Corva is its own world: no modern things, and no Athens, Rome, Egypt or other real places, peoples or "
    "gods. The family ties you are given are for reference only: never list them. Do not begin with the date.")


def house_view(con, house_id):
    """What a house believes and feels, for its chronicler: its members' readings of the Flight (most held first),
    its feelings toward the other houses, and its own legend."""
    flight = one(con, "select id from events where kind = 'departure'")
    views = rows(con, "select b.interpretation, count(*) n, avg(b.confidence) c from beliefs b join house_members m on m.person_id = b.holder_id "
                      "where m.house_id = ? and b.subject_type = 'event' and b.subject_id = ? group by b.interpretation "
                      "order by n desc, c desc limit 4", house_id, str(flight["id"])) if flight else []
    feel = rows(con, "select hh.name, sum(b.stance * b.confidence) / sum(b.confidence) f from beliefs b join house_members m "
                     "on m.person_id = b.holder_id join houses hh on hh.id = b.about_house where m.house_id = ? and b.stance is not null "
                     "and b.about_house != ? group by hh.name order by f", house_id, house_id)
    legend = one(con, "select title, text from legends where house_id = ?", house_id)
    return views, feel, legend


def chronicler_history(con, llm, c, year, evs, span, R, clock) -> dict | None:
    """One chronicler's history of the year: their house's claims, stored as theirs (chronicles, kind 'chronicle')."""
    from world import anachronism
    from world.tick import true_ties
    p = one(con, "select p.*, h.name house, h.id house_id from people p join house_members m on m.person_id = p.id "
                 "join houses h on h.id = m.house_id where p.name = ? and p.alive = 1 and p.absent = 0", c["name"])
    if not p:
        return None
    views, feel, legend = house_view(con, p["house_id"])
    order = ["spring", "summer", "autumn", "winter"]
    record = []
    for se in order:
        lines = [event_line(e) for e in evs if e["season"] == se and not e["sealed"]]
        if lines:
            record.append(f"{se.title()}: " + " ".join(lines))
    told = rows(con, "select m.text, q.name from memories m join people q on q.id = m.person_id where m.year = ? and "
                     "m.text like '(as told)%' and m.told_by is null order by m.vividness desc limit 3", year)
    ties = true_ties(con, [p["id"]] + [a for e in evs for a in json.loads(e["actors"])])
    lo, hi = R.get("chronicle_words", [220, 300])
    system = CHRONICLER_SYSTEM.format(name=p["name"], title=c["title"], house=p["house"], span=span, voice=c["voice"], lo=lo, hi=hi)
    def word(f):
        return ("hates" if f < -0.6 else "distrusts" if f < -0.25 else "is wary of" if f < -0.05 else
                "is fond of" if f > 0.4 else "leans toward" if f > 0.1 else "is indifferent to")
    held = ["Most of us believe", "Some of us say", "A few say", "One or two say"]
    user = ("The record of the year (what happened; the engine's own account):\n" + "\n".join(record or ["Little of note."]) + "\n\n"
            f"What House {p['house']} believes about the Flight: "
            + (" ".join(f"{held[min(i, 3)]}: {v['interpretation']}" for i, v in enumerate(views)) or "nothing settled.") + "\n"
            + f"House {p['house']} " + ("; ".join(f"{word(f['f'])} House {f['name']}" for f in feel if abs(f["f"]) > 0.05) or "has no strong feelings")
            + ".\n"
            + (f"The legend our house tells: {legend['title']}: {legend['text']}\n" if legend else "")
            + ("Dreams people told this year: " + " / ".join(f"{t['name']}: {t['text'][len('(as told) '):][:160]}" for t in told) + "\n" if told else "")
            + "Reference only (never repeat): family ties: " + "; ".join(ties[:20]) + ".")
    text, cut = "", 0
    for attempt in range(2):
        clock.calls += 1
        text = finish(llm.chat(system, user, max_new_tokens=int(hi * 1.6), repetition_penalty=1.12))
        text, cut = drop_ties(text)
        bad = anachronism.find(text)
        if not bad and cut <= 1:
            break
        user += ("\n(Write it again without " + (", ".join(bad) + " (Corva has no such things or places)" if bad else "")
                 + (" and " if bad and cut > 1 else "") + ("listing family ties" if cut > 1 else "") + ".)")
    text = anachronism.strip(text) if anachronism.find(text) else text
    from world.db import insert
    title = f"{p['name']}, {c['title']}, of House {p['house']}"
    insert(con, "chronicles", year=year, season=evs[-1]["season"] if evs else "winter", author_id=p["id"],
           events=[e["id"] for e in evs if not e["sealed"]], text=text, kind="chronicle", title=title)
    ACCOUNT_CUTS.append((p["name"], cut))
    return {"title": title, "text": text, "house": p["house"]}


def write_year_chronicle(con, llm, year, upto_season, clock, complete: bool, R=None) -> str:
    """docs/chronicle_year<Y>.md: the year as each of the chroniclers wrote it (rules.yaml chroniclers). Their histories
    are their houses' claims, side by side; the engine's own record of events is in the season logs."""
    from world.tick import load_rules
    R = R or load_rules()
    order = ["spring", "summer", "autumn", "winter"]
    evs = year_events(con, year, upto_season)
    seasons = [x for x in order if any(e["season"] == x for e in evs)] or [upto_season]
    span = "the year" if complete else f"the year so far ({' and '.join(seasons)})"
    lines = [f"# The Chronicles of Corva: Year {year}" + ("" if complete else f" (so far: {', '.join(x.title() for x in seasons)})"), "",
             "*The world engine's sandbox (offline). Each year is written by the city's chroniclers, each from their own house: "
             "its loyalties, its grudges, its beliefs about the Flight. These are their claims, not facts, and they disagree. "
             "What actually happened is the engine's record, in the season logs.*", ""]
    ACCOUNT_CUTS.clear()
    for c in R.get("chroniclers", []):
        h = chronicler_history(con, llm, c, year, evs, span, R, clock)
        if h:
            lines += [f"## As {h['title']} wrote it", "", h["text"].strip(), ""]
    path = ROOT / f"docs/chronicle_year{year}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.relative_to(ROOT))


def pick_viewpoints_year(con, year, evs, n=4):
    touched = [a for e in evs for a in json.loads(e["actors"])]
    cands = rows(con, "select p.*, h.name house from people p join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                      "where p.alive = 1 and p.absent = 0 and p.tier = 'principal' and (? - p.born_year) >= 16", year)
    cands.sort(key=lambda p: (-touched.count(p["id"]), p["id"]))
    out, houses = [], set()
    for p in cands:
        if p["house"] not in houses:
            out.append(p)
            houses.add(p["house"])
        if len(out) == n:
            break
    return out


YEAR_CHRONICLE_ESTIMATE = 300   # seconds: 4 accounts + town talk, once a year (season 2's chronicle step took 260 s)


def write_log(con, year, season, tick, stats, interp, raw_failures, budget_seconds=7200) -> str:
    props = rows(con, "select s.*, h.name house from storyteller_proposals s join houses h on h.id = s.house_id where s.tick = ? order by s.id", tick)
    lines = [f"# Season {tick} log: {season}, year {year} (world engine v0, offline sandbox)", "",
             "The engine's side of the season: what drove people, what each house set out to do, what the storyteller "
             "proposed and what the world made of it, how long each step took, and the vital signs. (Never shown here: "
             "private truths, the sealed location, sealed events.)", ""]
    # the record: what happened (the neutral account lives here now; the chronicles are the chroniclers')
    lines += ["## The record (the engine's own account of the season)", ""]
    lines += [f"- {event_line(e)}" for e in season_events(con, year, season)] or ["- Nothing was recorded."]
    lines += [""]
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
            return f"House {r['name']} (as a family)" if r else ref
        if ref.startswith("c") and ref[1:].isdigit():
            r = one(con, "select name from houses where id = ?", int(ref[1:]))
            return f"House {r['name']}'s clients" if r else ref
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
              "Only the most-shared dreams are interpreted (told to the most people). Raw dream (the run 5 model's words) beside "
              "the dreamer's own retelling in Corva's terms, their reading, and the checks it went through (each failed check "
              "was asked again: out-of-world words, a near-copy of another reading).", "",
              "| Dreamer (house) | Told to (people) | Raw dream (start) | Retold | Reading | Sure | Toward | Checks |", "|---|---|---|---|---|---|---|---|"]
    for i in interp:
        raw = " ".join(i["dream"]["text"].split()[:22]).replace("|", "/")
        checks = "; ".join(i.get("checks") or []) or "passed first time"
        if not i["ok"]:
            lines.append(f"| {i['dream']['person']['name']} | | {raw}… | *(reply unusable)* | | | | {checks} |")
            continue
        if i["dream"]["person"]["absent"]:
            continue
        toward = f"{i['about']} {i['stance']:+.1f}" if i["stance"] is not None else "no house"
        lines.append(f"| {i['dream']['person']['name']} ({i['house']}) | {i['listener']} ({i['told']}) | {raw}… | {i['retelling'].replace('|', '/')} | "
                     f"{i['interpretation'].replace('|', '/')} | {i['confidence']:.0%} | {toward} | {checks} |")
    if interp and not interp[0].get("dedupe", True):
        lines += ["", "(The near-copy check was skipped: sentence-transformers is not installed.)"]
    lines += ["", "### Interpretation lean by house", "",
              "Which way each house's readings of dreams leaned this season (the dreamer's own reading; listeners take it up at "
              "70% of the stance).", "", "| Interpreter's house | Readings | About no house | Toward (n, mean stance) |", "|---|---:|---:|---|"]
    for h, L in sorted(stats.get("interpretation_lean", {}).items()):
        toward = ", ".join(f"{t} ({v['n']}, {v['mean_stance']:+.2f})" for t, v in L["toward"].items()) or "-"
        lines.append(f"| {h} | {L['readings']} | {L['about no house']} | {toward} |")
    # runtime against the budget
    rt = rows(con, "select step, seconds, calls from runtimes where year = ? and season = ?", year, season)
    total = sum(r["seconds"] for r in rt)
    per_day = lambda r: r["seconds"] * (1 if r["step"].startswith("chronicle") else 4)   # the chronicle is once a year
    day_total = sum(per_day(r) for r in rt) + (0 if any(r["step"].startswith("chronicle") for r in rt) else YEAR_CHRONICLE_ESTIMATE)
    lines += ["", f"## Runtime per step, against the {budget_seconds // 3600}-hour daily ceiling", "",
              "One day = one year = 4 seasons. Each season step x4; the chronicle once a year"
              + ("" if any(r["step"].startswith("chronicle") for r in rt) else f" (not written this season: estimated at {YEAR_CHRONICLE_ESTIMATE // 60} min)") + ".", "",
              f"| Step | Seconds this season | Model calls | Per day | Share of the {budget_seconds // 3600}-hour ceiling |", "|---|---:|---:|---:|---:|"]
    for r in rt:
        lines.append(f"| {r['step']} | {r['seconds']:.0f} | {r['calls']} | {per_day(r) / 60:.1f} min | {per_day(r) / budget_seconds:.0%} |")
    lines.append(f"| **total** | **{total:.0f}** | **{sum(r['calls'] for r in rt)}** | **{day_total / 60:.0f} min** | **{day_total / budget_seconds:.0%}** |")
    if ACCOUNT_CUTS:
        lines += ["", "Background ties cut from the chronicles (sentences): " + ", ".join(f"{a} {n}" for a, n in ACCOUNT_CUTS) + "."]
    lines += ["", "## Vital signs", "", "```json", json.dumps({k: v for k, v in stats.items() if k != "runtime"}, indent=1), "```", ""]
    path = ROOT / f"docs/season{tick}_log.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.relative_to(ROOT))
