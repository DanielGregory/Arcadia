"""Drives: what each principal is pushing for this season (1 to 3 each).

A drive is a person's own aim, like a belief: it lives with them, never as a fact about the world.
They are worked out at the start of each season from the person's situation (house, role, stores,
clients), their beliefs (the Flight, old grievances between houses), and the intentions their dreams
left them with. The storyteller sees them, so a house's proposals come from its people's wants.

Seeded drives (from Danny's review of season 1) hold for the story's principals while their
situation holds (Marius's lasts while Livia is missing...). Everything derived is PROPOSED.
"""

from __future__ import annotations

from world.db import insert, one, rows

STORY_DRIVES = {   # Danny's: they hold while the situation holds
    "Marius Corvane": ("get Livia back", lambda con: missing(con, "Livia Corvane")),
    "Lucan Valerius": ("restore his honour after the broken betrothal", lambda con: True),
    "Galen Theren": ("torn: protect Soren, or keep the peace that has protected House Theren for generations", lambda con: True),
    "Tiberon Theren": ("his resentment of Soren, whom he never accepted as a brother", lambda con: True),
    "Neria": ("fear of discovery", lambda con: True),
}
# what each house's head pushes for by default, from its role (PROPOSED)
HOUSE_AIMS = {
    "Corvane": "hold the council seat while the house is shamed", "Valerius": "turn the insult into advantage",
    "Theren": "keep the house out of the quarrel", "Aurelian": "keep the temple's standing above the quarrel",
    "Marcellan": "profit whichever way the quarrel turns", "Cassian": "win back what the judges took from Cassian",
    "Severin": "keep the peace through judgment", "Damaris": "keep the city's secrets, and its trust",
    "Veyra": "keep Corva's quarrels off the mountain", "Solenne": "find a way back into the council",
}
FLIGHT_DRIVES = {   # from a person's own reading of the Flight
    "carried Livia off": "make Soren of the Harbor and House Theren answer for taking Livia",
    "arranged the escape": "expose House Theren's part in the Flight",
    "own will": "find out where Livia and Soren went",
    "sailed east": "find out whether they sailed east",
    "northern road": "find out whether they took the northern road",
}


def missing(con, name: str) -> bool:
    p = one(con, "select absent from people where name = ?", name)
    return bool(p and p["absent"])


def compute_drives(con, year: int, season: str, max_per_person: int = 3) -> dict[int, list[str]]:
    out = {}
    principals = rows(con, "select p.*, h.name house, h.id house_id, h.food, m.role from people p join house_members m on m.person_id = p.id "
                           "join houses h on h.id = m.house_id where p.alive = 1 and p.absent = 0 and p.tier = 'principal'")
    for p in principals:
        drives: list[tuple[str, str]] = []
        story = STORY_DRIVES.get(p["name"])
        if story and story[1](con):
            drives.append((story[0], "story"))
        # the strongest reading of the Flight they hold
        flight = one(con, "select id from events where kind = 'departure'")["id"]
        for b in rows(con, "select interpretation, confidence from beliefs where holder_id = ? and subject_id = ? "
                           "order by confidence desc", p["id"], str(flight)):
            for key, drive in FLIGHT_DRIVES.items():
                if key in b["interpretation"] and b["confidence"] > 0.35:
                    drives.append((drive, "belief"))
                    break
            if len(drives) >= 2:
                break
        # an old score: their coldest belief about another house from an older quarrel between houses (not the
        # Flight itself, which the drives above already cover, and not dreams)
        cold = one(con, "select h.name, b.stance, b.confidence from beliefs b join houses h on h.id = b.about_house "
                        "join events e on e.id = b.subject_id and b.subject_type = 'event' "
                        "where b.holder_id = ? and b.stance < -0.3 and h.id != ? and e.kind != 'departure' "
                        "order by b.stance * b.confidence limit 1", p["id"], p["house_id"])
        if cold:
            drives.append((f"settle the old score with House {cold['name']}", "grievance"))
        # what last season's dream left them meaning to do
        intent = one(con, "select text from memories where person_id = ? and text like 'I mean to:%' order by id desc limit 1", p["id"])
        if intent:
            drives.append((intent["text"][len("I mean to: "):].rstrip(".")[:120], "dream"))
        if p["role"] == "head":
            clients = one(con, "select loyalty from house_clients where house_id = ? order by id desc limit 1", p["house_id"])
            if clients and clients["loyalty"] is not None and clients["loyalty"] < 0.65:
                drives.append(("keep the house's clients loyal", "situation"))
            if p["food"] < 10:
                drives.append(("feed the house through the season", "situation"))
            drives.append((HOUSE_AIMS[p["house"]], "house"))
        seen, kept = set(), []
        for text, source in drives:
            if text.lower() not in seen:
                seen.add(text.lower())
                kept.append((text, source))
        kept = kept[:max_per_person]
        for text, source in kept:
            insert(con, "drives", year=year, season=season, person_id=p["id"], text=text, source=source)
        out[p["id"]] = [t for t, _ in kept]
    return out
