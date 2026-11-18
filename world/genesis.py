"""Genesis: Corva on the first day, from the seed story (docs/seed_history.md).

Corva is already an old city. The world begins in the autumn of year 0, just after the Flight: the
ten houses, ~25 principals, ~75 side characters and ~200 townsfolk (as clients and the unattached),
the places of the island, the events of the seed story as facts, everyone's first beliefs about
them, the private truths as character-only memories, and each house's legends.

Everything not in Danny's seed story is marked PROPOSED (in the `proposed` columns, and in NOTES
below): the heads and families of the houses he hasn't detailed, Lucan's father, the old
priestess's name, the old temple servant, the sailor and the merchant, the houses' claims as
worded here, the older grievances between houses, and the legends.

The lovers' true location is chosen here, at random from the island's places and the lands beyond,
with an unseeded random choice, and written only to sealed_facts. Nothing prints it.
"""

from __future__ import annotations

import json
import random
import secrets
from pathlib import Path

from world.db import ROOT, create, insert, rows, one

Y0, AUTUMN = 0, "autumn"

# --- the houses -----------------------------------------------------------------------------------
# name: (claim, land, land kind, seat, starting stores [food, goods, materials], clients, detailed by Danny)
HOUSES = {
    "Corvane":  ("the council seat: the presiding voice in Corva's council", "the old estates of the upper city and the citadel hill", "city", "the Corvane house on the summit", [30, 30, 10], 26, True),
    "Valerius": ("command of Corva's ships of war and the harbour guard", "shipyards and estates along the north shore", "ships", "the Valerius house above the shipyards", [26, 34, 8], 24, True),
    "Theren":   ("the oldest grove rights in the hills: the first pressing of olive and vine", "olive and vineyard land in the hills", "groves", "the Theren farmhouse in the hills", [40, 18, 4], 16, True),
    "Aurelian": ("the high priesthood of the sea temple", "the temple lands below the summit", "temple", "the sea temple", [20, 24, 4], 18, False),
    "Marcellan": ("the harbour dues and the trading charters", "warehouses and wharves on the harbour", "trade", "the Marcellan counting house on the quay", [24, 40, 4], 22, False),
    "Cassian":  ("the right to cut stone from the city's quarries and to build its terraces", "the quarries on the north ridge", "quarries", "the Cassian yard by the quarries", [16, 18, 30], 18, False),
    "Severin":  ("the judges' bench: their elders settle disputes between houses", "a hall and gardens by the market", "law", "the hall of judgment", [18, 20, 4], 12, False),
    "Damaris":  ("the right to attend every birth and every death in Corva", "a house and herb gardens by the western gate", "healing", "the Damaris house by the western gate", [14, 12, 2], 10, True),
    "Veyra":    ("the grazing and the hunting of the mountain", "pastures and hunting grounds on Mount Aetos", "herds", "the Veyra steadings on the mountain", [30, 10, 6], 10, False),
    "Solenne":  ("a seat of honour at the festival of the sea (all that remains of greater rights)", "one old house in the upper city", "faded", "the Solenne house in the upper city", [8, 10, 2], 8, False),
}

# --- people -----------------------------------------------------------------------------------------
# (name, house, role, age, dream temperament, traits [openness, caution, warmth, pride, piety], proposed, absent, note)
PRINCIPALS = [
    ("Marius Corvane", "Corvane", "head", 61, "traditionalist", [0.3, 0.6, 0.5, 0.85, 0.6], False, False, "aging lord of House Corvane"),
    ("Livia Corvane", "Corvane", "child", 20, "romantic", [0.85, 0.3, 0.7, 0.6, 0.4], False, True, "his only daughter; fled in the autumn of year 0"),
    ("Lucan Valerius", "Valerius", "heir", 26, "pragmatist", [0.35, 0.7, 0.45, 0.85, 0.5], False, False, "heir of Valerius; proud, disciplined, believes in duty"),
    ("Galen Theren", "Theren", "head", 58, "sage", [0.55, 0.7, 0.8, 0.45, 0.55], False, False, "head of House Theren; took Soren in"),
    ("Tiberon Theren", "Theren", "heir", 29, "skeptic", [0.3, 0.55, 0.35, 0.8, 0.4], False, False, "Galen's eldest son"),
    ("Soren of the Harbor", "Theren", "fosterling", 22, "romantic", [0.7, 0.35, 0.75, 0.55, 0.35], False, True, "harbour pilot, raised by the Therens; fled in the autumn of year 0"),
    ("Neria", "Damaris", "servant", 34, "romantic", [0.6, 0.75, 0.8, 0.3, 0.5], False, False, "a servant of House Damaris"),
    # PROPOSED from here: named roles from the story, and the heads and heirs Danny hasn't detailed
    ("Gaius Valerius", "Valerius", "head", 55, "pragmatist", [0.3, 0.6, 0.35, 0.9, 0.45], True, False, "Lucan's father, head of Valerius"),
    ("Ismene", "Aurelian", "kin", 74, "mystic", [0.75, 0.4, 0.6, 0.3, 0.95], True, False, "the old priestess who dreamed of the ring and the two stars"),
    ("Theodric Aurelian", "Aurelian", "head", 59, "mystic", [0.4, 0.75, 0.4, 0.7, 0.9], True, False, "high priest of the sea temple"),
    ("Octavia Marcellan", "Marcellan", "head", 48, "pragmatist", [0.65, 0.6, 0.5, 0.6, 0.3], True, False, "head of the merchant house"),
    ("Rufus Cassian", "Cassian", "head", 51, "skeptic", [0.35, 0.3, 0.45, 0.85, 0.35], True, False, "master of the quarries"),
    ("Aldric Severin", "Severin", "head", 67, "traditionalist", [0.2, 0.8, 0.3, 0.75, 0.7], True, False, "eldest of the judges"),
    ("Hesione Damaris", "Damaris", "head", 56, "sage", [0.6, 0.65, 0.85, 0.35, 0.6], True, False, "chief of the healers and midwives"),
    ("Kael Veyra", "Veyra", "head", 45, "traditionalist", [0.25, 0.75, 0.4, 0.7, 0.65], True, False, "chief of the mountain herders"),
    ("Seraphine Solenne", "Solenne", "head", 71, "romantic", [0.4, 0.5, 0.3, 0.9, 0.5], True, False, "last matriarch of Solenne"),
    ("Decimus Corvane", "Corvane", "kin", 33, "pragmatist", [0.45, 0.55, 0.4, 0.75, 0.4], True, False, "Marius's nephew"),
    ("Corin Theren", "Theren", "child", 24, "sage", [0.6, 0.5, 0.7, 0.4, 0.5], True, False, "Galen's second son"),
    ("Drusilla Valerius", "Valerius", "child", 22, "skeptic", [0.6, 0.45, 0.5, 0.7, 0.3], True, False, "Lucan's sister"),
    ("Iola Aurelian", "Aurelian", "kin", 19, "mystic", [0.7, 0.4, 0.65, 0.4, 0.85], True, False, "a young priestess, Ismene's attendant"),
    ("Nikias Marcellan", "Marcellan", "heir", 28, "pragmatist", [0.6, 0.4, 0.55, 0.6, 0.3], True, False, "ship's captain, Octavia's son"),
    ("Brenna Cassian", "Cassian", "heir", 26, "pragmatist", [0.5, 0.35, 0.5, 0.8, 0.4], True, False, "master builder, Rufus's daughter"),
    ("Quintus Severin", "Severin", "heir", 41, "skeptic", [0.3, 0.75, 0.35, 0.7, 0.55], True, False, "a judge, Aldric's son"),
    ("Ysolde Veyra", "Veyra", "heir", 23, "mystic", [0.55, 0.45, 0.5, 0.6, 0.7], True, False, "huntress, Kael's daughter"),
    ("Silvan Solenne", "Solenne", "heir", 19, "romantic", [0.75, 0.3, 0.6, 0.65, 0.4], True, False, "Seraphine's grandson, the last heir"),
]
# PROPOSED side characters from the story's unnamed figures
STORY_SIDE = [
    ("Philo", "Aurelian", "servant", 68, "traditionalist", "the old temple servant who said he saw two figures at the western gate"),
    ("Dion", "Marcellan", "retainer", 37, "skeptic", "the sailor who swore he saw their vessel sailing east"),
    ("Hesper", "Marcellan", "retainer", 44, "pragmatist", "the merchant who said they took the northern road"),
]
MALE = ["Aulus", "Bion", "Cato", "Doros", "Evander", "Felix", "Junius", "Kleon", "Milo", "Nerva", "Otho", "Petros",
        "Silas", "Theon", "Titus", "Varro", "Xanthos", "Laurent", "Damon", "Isidor", "Corvin", "Basil", "Lysias", "Orin"]
FEMALE = ["Aelia", "Calla", "Cyra", "Delia", "Elara", "Fausta", "Helia", "Irene", "Julia", "Lavinia", "Maia", "Nyssa",
          "Phaedra", "Rhea", "Sabina", "Thalia", "Xenia", "Zoe", "Lysandra", "Ione", "Daphne", "Clio", "Selene", "Tamsin"]
TEMPERAMENTS = ["mystic", "romantic", "traditionalist", "sage", "pragmatist", "skeptic"]
# a house's leaning in temperament (PROPOSED)
HOUSE_TEMPER = {"Aurelian": "mystic", "Severin": "traditionalist", "Marcellan": "pragmatist", "Cassian": "pragmatist",
                "Veyra": "traditionalist", "Damaris": "sage", "Solenne": "romantic", "Valerius": "pragmatist",
                "Corvane": "traditionalist", "Theren": "sage"}

# --- places -----------------------------------------------------------------------------------------
PLACES = [  # (name, kind, on island)
    ("the harbour", "harbour", 1), ("the sea temple", "temple", 1), ("the western gate", "gate", 1),
    ("the summit", "hill", 1), ("the market", "market", 1), ("the terraces", "quarter", 1),
    ("the council hall", "hall", 1), ("the north shore shipyards", "shipyard", 1), ("the quarries", "quarry", 1),
    ("the Theren hills", "groves", 1), ("Mount Aetos", "mountain", 1), ("the northern road", "road", 1),
    ("Elaia", "village", 1), ("Ampelos", "village", 1), ("Kryoneri", "village", 1), ("Platanos", "village", 1),
    ("Melissa", "village", 1), ("the north coast coves", "coast", 1), ("the mountain sheepfolds", "pasture", 1),
    ("the eastern islands", "islands", 0), ("the mainland", "mainland", 0), ("the open sea", "sea", 0),
]
# where the lovers might be: anywhere they could have reached and still be alive (the engine draws one)
SEALED_CANDIDATES = ["Elaia", "Ampelos", "Kryoneri", "Platanos", "Melissa", "the north coast coves",
                     "the mountain sheepfolds", "Mount Aetos", "the eastern islands", "the mainland"]

# --- the founding legend, as each house tells it (all PROPOSED) --------------------------------------
LEGENDS = {
    None: ("The Founding", "Long ago, ships came to the island out of a storm and the people climbed the cliffs to build Corva; the city tells it with ten houses at the oars, though no two houses agree on who steered."),
    "Corvane": ("The First Lord", "As House Corvane tells it, Corvan the first lord read the stars that brought the ships ashore, chose the summit, and set the council around his own hearth: the city was founded by Corvanes and the rest came after."),
    "Valerius": ("The Shield of the Harbour", "As Valerius tells it, the city would have burned in its first summer if their ancestor had not held the harbour against raiders; the founders gave Valerius the ships in gratitude."),
    "Theren": ("The First Olive", "As the Therens tell it, their ancestor carried a single olive cutting across the sea in her cloak, planted it in the hills, and from it every grove on the island grew."),
    "Aurelian": ("The Sea's Bargain", "As Aurelian tells it, the founders were spared the storm only because their first priest promised the sea a temple; the temple was built before any house."),
    "Marcellan": ("The Second Ship", "As Marcellan tells it, the founders came on two ships, and theirs carried the grain, the tools and the coin: the city lived on what Marcellan brought."),
    "Cassian": ("The Terraces", "As Cassian tells it, the cliff was bare rock until their stonecutters cut the first terraces; the other houses lived in tents while Cassians built."),
    "Severin": ("The First Judgment", "As Severin tells it, the founders quarrelled over the land on the first night, and their ancestor's judgment kept the peace; since then no dispute has been settled without them."),
    "Damaris": ("The Birth on the Shore", "As Damaris tells it, the first child of Corva was born on the shore the night the ships landed, and a Damaris midwife brought it into the world."),
    "Veyra": ("Before the Ships", "As Veyra tells it, their people were already on the mountain when the ships came, and Corva has been a guest on the island ever since."),
    "Solenne": ("The Seat That Was", "As Solenne tells it, theirs was the first council seat, held for a hundred years before Corvane took it by a marriage and a lie."),
}

# --- older grievances between houses (PROPOSED), permanent facts --------------------------------------
HISTORY = [  # (year, kind, houses [actor, target], text, stances: [(holder house, about house, stance, interpretation)])
    (-62, "seat_transfer", ["Corvane", "Solenne"], "The council seat passed from House Solenne to House Corvane.",
     [("Solenne", "Corvane", -0.7, "Corvane took our seat by a marriage and a lie."), ("Corvane", "Solenne", -0.1, "Solenne lost the seat through its own failings.")]),
    (-30, "grant", ["Corvane", "Valerius"], "The council granted House Valerius command of the war fleet after the raiders were driven off.",
     [("Valerius", "Corvane", 0.3, "Corvane honoured what we did."), ("Solenne", "Valerius", -0.2, "The upstarts were rewarded too well.")]),
    (-11, "judgment", ["Severin", "Cassian"], "The judges of Severin ruled for House Marcellan against House Cassian in the dispute over the harbour quarry.",
     [("Cassian", "Severin", -0.5, "The judges were bought."), ("Cassian", "Marcellan", -0.4, "Marcellan won with coin, not right."), ("Marcellan", "Severin", 0.3, "The judges were fair.")]),
    (-5, "fine", ["Corvane", "Veyra"], "The council fined a Veyra herder for grazing his flock in the Theren groves.",
     [("Veyra", "Corvane", -0.5, "The city's council punishes the mountain for the city's benefit."), ("Veyra", "Theren", -0.3, "The Therens ran to the council instead of talking to us.")]),
]

# --- first beliefs about the Flight (PROPOSED distributions per house) ---------------------------------
FLIGHT_VIEWS = {
    "force":  ("Soren of the Harbor carried Livia off against her will.", "Theren", -0.6),
    "willing": ("Livia left of her own will; she chose him.", "Corvane", -0.15),
    "plot":   ("House Theren arranged the escape to humiliate Valerius.", "Theren", -0.8),
}
FLIGHT_MIX = {
    "Corvane": {"force": 0.6, "willing": 0.2, "plot": 0.2}, "Valerius": {"plot": 0.5, "force": 0.4, "willing": 0.1},
    "Theren": {"willing": 0.65, "force": 0.25, "plot": 0.1}, "Damaris": {"willing": 0.6, "force": 0.3, "plot": 0.1},
    "Aurelian": {"willing": 0.4, "force": 0.3, "plot": 0.3}, "default": {"force": 0.35, "willing": 0.35, "plot": 0.3},
}
DESTINATIONS = [("They sailed east.", "the eastern islands"), ("They took the northern road.", "the northern road")]


def place_id(con, name: str) -> int:
    return one(con, "select id from places where name = ?", name)["id"]


def genesis(seed: int = 1717) -> None:
    con = create()
    r = random.Random(seed)
    for name, kind, on in PLACES:
        insert(con, "places", year=Y0, season=AUTUMN, name=name, kind=kind, on_island=on, condition="standing")

    # houses
    house_id = {}
    for name, (claim, land, kind, seat, stores, _, detailed) in HOUSES.items():
        pid = insert(con, "places", year=Y0, season=AUTUMN, name=seat, kind="house", on_island=1, condition="standing")
        house_id[name] = insert(con, "houses", year=Y0, season=AUTUMN, name=name, claim=claim, land=land, land_kind=kind,
                                seat_place_id=pid, food=stores[0], goods=stores[1], materials=stores[2],
                                proposed=0 if detailed and name in ("Corvane", "Valerius", "Theren") else 1)

    used = {p[0].split()[0] for p in PRINCIPALS}

    def add_person(name, house, role, age, temper, traits, tier, proposed, absent=False, note=None, alive=True, died=None):
        o, c, w, p, pi = traits
        seat = one(con, "select seat_place_id from houses where name = ?", house)["seat_place_id"]
        pid = insert(con, "people", year=Y0, season=AUTUMN, name=name, born_year=Y0 - age, died_year=died,
                     origin="Corva", household=house, openness=o, caution=c, warmth=w, pride=p, piety=pi,
                     need_hunger=0.8, need_warmth=0.7, need_safety=0.7, need_belonging=0.7, need_standing=0.7,
                     health=0.9 if age < 60 else 0.7, place_id=None if absent else seat, alive=1 if alive else 0,
                     tier=tier, dream_temperament=temper, absent=1 if absent else 0, proposed=1 if proposed else 0, note=note)
        insert(con, "house_members", house_id=house_id[house], person_id=pid, role=role, joined_year=Y0 - age, joined_season=AUTUMN)
        return pid

    pid = {}
    for name, house, role, age, temper, traits, proposed, absent, note in PRINCIPALS:
        pid[name] = add_person(name, house, role, age, temper, traits, "principal", proposed, absent, note)
        if role == "head":
            con.execute("update houses set head_id = ? where name = ?", (pid[name], house))
    for name, house, role, age, temper, note in STORY_SIDE:
        pid[name] = add_person(name, house, role, age, temper, [r.random() for _ in range(5)], "side", True, note=note)

    # Livia's mother (PROPOSED: dead some years; the ring was hers)
    aelia = add_person("Aelia Corvane", "Corvane", "spouse", 52, "romantic", [0.6, 0.4, 0.7, 0.5, 0.6], "side", True,
                       note="Livia's mother, dead eight years (PROPOSED)", alive=False, died=Y0 - 8)
    used.add("Aelia")

    def fresh(pool):
        choices = [n for n in pool if n not in used] or pool
        n = r.choice(choices)
        used.add(n)
        return n

    def rel(a, b, kind, strength):
        insert(con, "relationships", year=Y0, season=AUTUMN, person_a=a, person_b=b, kind=kind, strength=strength)

    def child_of(parent, child, kind="blood"):
        insert(con, "lineage", parent_id=parent, child_id=child, kind=kind)
        rel(parent, child, "kin", 0.6 + r.random() * 0.3)

    # the families from the seed story
    child_of(pid["Marius Corvane"], pid["Livia Corvane"]); child_of(aelia, pid["Livia Corvane"])
    child_of(pid["Gaius Valerius"], pid["Lucan Valerius"]); child_of(pid["Gaius Valerius"], pid["Drusilla Valerius"])
    child_of(pid["Galen Theren"], pid["Tiberon Theren"]); child_of(pid["Galen Theren"], pid["Corin Theren"])
    child_of(pid["Galen Theren"], pid["Soren of the Harbor"], "fostered")   # his father: no row, unknown
    for parent, child in [("Octavia Marcellan", "Nikias Marcellan"), ("Rufus Cassian", "Brenna Cassian"),
                          ("Aldric Severin", "Quintus Severin"), ("Kael Veyra", "Ysolde Veyra")]:
        child_of(pid[parent], pid[child])
    rel(pid["Livia Corvane"], pid["Soren of the Harbor"], "lover", 0.95)
    rel(pid["Livia Corvane"], pid["Lucan Valerius"], "betrothed", 0.1)
    rel(pid["Tiberon Theren"], pid["Soren of the Harbor"], "rival", -0.5)
    rel(pid["Neria"], pid["Livia Corvane"], "friend", 0.7)
    rel(pid["Ismene"], pid["Iola Aurelian"], "teacher", 0.7)
    rel(pid["Tiberon Theren"], pid["Corin Theren"], "kin", 0.7)
    rel(pid["Corin Theren"], pid["Soren of the Harbor"], "kin", 0.7)

    # side characters (PROPOSED): spouses of living heads, children, kin and servants, up to ~75
    side_target = 75
    houses_cycle = list(HOUSES)
    n_side = len(STORY_SIDE) + 1
    for h in houses_cycle:   # a spouse for each living head (not Marius: widowed)
        head = one(con, "select head_id from houses where name = ?", h)["head_id"]
        if h == "Corvane":
            continue
        hp = one(con, "select born_year from people where id = ?", head)
        female_head = h in ("Marcellan", "Damaris", "Solenne")
        nm = fresh(MALE if female_head else FEMALE) + " " + h
        sp = add_person(nm, h, "spouse", -hp["born_year"] - r.randint(0, 6), HOUSE_TEMPER[h] if r.random() < 0.5 else r.choice(TEMPERAMENTS),
                        [r.random() for _ in range(5)], "side", True, note="spouse of the head")
        rel(head, sp, "spouse", 0.4 + r.random() * 0.5)
        n_side += 1
    # how many family and household each house has: great houses more, faded Solenne few (PROPOSED)
    weight = {"Corvane": 1.0, "Valerius": 1.1, "Theren": 1.0, "Aurelian": 1.0, "Marcellan": 1.0, "Cassian": 1.0,
              "Severin": 0.8, "Damaris": 0.7, "Veyra": 0.9, "Solenne": 0.2}
    while n_side < side_target:
        h = r.choices(houses_cycle, weights=[weight[x] for x in houses_cycle])[0]
        roll = r.random()
        if roll < 0.45:      # a child of the head (some still young)
            head = one(con, "select head_id from houses where name = ?", h)["head_id"]
            hp = one(con, "select born_year from people where id = ?", head)
            age = max(2, min(-hp["born_year"] - 18, r.randint(3, 30)))
            nm = fresh(r.choice([MALE, FEMALE])) + " " + h
            p = add_person(nm, h, "child", age, r.choice(TEMPERAMENTS), [r.random() for _ in range(5)], "side", True)
            child_of(head, p)
        elif roll < 0.75:    # kin: cousins, aunts, uncles
            nm = fresh(r.choice([MALE, FEMALE])) + " " + h
            add_person(nm, h, "kin", r.randint(18, 70), HOUSE_TEMPER[h] if r.random() < 0.4 else r.choice(TEMPERAMENTS),
                       [r.random() for _ in range(5)], "side", True)
        else:                # servants and retainers: a single name
            nm = fresh(r.choice([MALE, FEMALE]))
            add_person(nm, h, r.choice(["servant", "retainer"]), r.randint(16, 65), r.choice(TEMPERAMENTS),
                       [r.random() for _ in range(5)], "side", True)
        n_side += 1

    # objects: the ring
    ring = insert(con, "objects", year=Y0, season=AUTUMN, kind="ring", description="a gold ring, an heirloom of House Corvane",
                  owner_person=pid["Livia Corvane"], owner_house=house_id["Corvane"], location_person=pid["Livia Corvane"], condition="whole")

    # events: older history (PROPOSED), then the seed story
    def event(year, season, kind, text, actors=(), houses=(), place=None, facts=None, objects=()):
        return insert(con, "events", year=year, season=season, kind=kind, text=text, actors=list(actors), objects=list(objects),
                      houses=[house_id[h] for h in houses], place_id=place_id(con, place) if place else None,
                      outcome="success", facts=facts or {})

    def belief(holder, subject_type, subject_id, text, conf, about=None, stance=None, source="witnessed", year=Y0, season=AUTUMN):
        insert(con, "beliefs", year=year, season=season, holder_id=holder, subject_type=subject_type, subject_id=str(subject_id),
               interpretation=text, confidence=round(conf, 2), source_type=source, about_house=house_id.get(about) if about else None,
               stance=stance)

    members = {h: rows(con, "select p.id, p.born_year, p.caution, p.alive from people p join house_members m on m.person_id = p.id "
                           "join houses hh on hh.id = m.house_id where hh.name = ?", h) for h in HOUSES}
    adults = lambda h: [m for m in members[h] if m["alive"] and -m["born_year"] >= 16]

    for year, kind, houses, text, stances in HISTORY:
        ev = event(year, "summer", kind, text, houses=houses, facts={"proposed": True})
        for holder_house, about, stance, interp in stances:
            for m in adults(holder_house):
                if -m["born_year"] - 16 < Y0 - year and r.random() < 0.5:
                    # too young to have seen it: they hold it as inherited (fainter)
                    belief(m["id"], "event", ev, interp, 0.35, about, stance * 0.6, "told_by")
                else:
                    belief(m["id"], "event", ev, interp, 0.5 + r.random() * 0.3, about, stance, "told_by")

    betrothal = event(Y0 - 1, "spring", "betrothal", "House Corvane and House Valerius agreed the marriage of Livia Corvane and Lucan Valerius.",
                      actors=[pid["Marius Corvane"], pid["Gaius Valerius"]], houses=["Corvane", "Valerius"])
    event(Y0 - 4, "summer", "gathering", "Livia Corvane and Soren of the Harbor were both at the summer gathering at the harbour.",
          actors=[pid["Livia Corvane"], pid["Soren of the Harbor"]], place="the harbour")
    # the old priestess's dream, three nights before the festival, and her telling of it
    insert(con, "dreams", id="y0-autumn-ismene", year=Y0, season=AUTUMN, dreamer_id=pid["Ismene"], run="seed", kind="world",
           tag="dream", text="A golden ring sank beneath dark water while two stars disappeared from the heavens.",
           recalled=1, shared_with=[pid["Iola Aurelian"]], vividness=0.95)
    told = event(Y0, AUTUMN, "told_dream", "Ismene told the temple attendants of a dream she had had.", actors=[pid["Ismene"]],
                 houses=["Aurelian"], place="the sea temple", facts={"dream": "y0-autumn-ismene"})
    event(Y0, AUTUMN, "festival", "The festival of the sea was held along the harbour.", place="the harbour")
    flight = event(Y0, AUTUMN, "departure", "Livia Corvane and Soren of the Harbor left Corva during the festival of the sea.",
                   actors=[pid["Livia Corvane"], pid["Soren of the Harbor"]], houses=["Corvane", "Theren"], objects=[ring],
                   facts={"taken": ["a small travelling cloak", "a purse of coins", "a gold ring"], "destination": "unknown"})
    gate = event(Y0, AUTUMN, "testimony", "Philo, an old temple servant, said he saw two figures leave through the western gate.",
                 actors=[pid["Philo"]], place="the western gate")
    east = event(Y0, AUTUMN, "testimony", "Dion, a sailor, swore he saw their vessel sailing east.", actors=[pid["Dion"]], place="the harbour")
    north = event(Y0, AUTUMN, "testimony", "Hesper, a merchant, said they had taken the northern road.", actors=[pid["Hesper"]], place="the market")
    dem1 = event(Y0, AUTUMN, "demand", "Marius Corvane demanded that his daughter be returned.", actors=[pid["Marius Corvane"]],
                 houses=["Corvane"], place="the council hall")
    dem2 = event(Y0, AUTUMN, "demand", "House Valerius demanded satisfaction for the insult to its heir and the breaking of the betrothal.",
                 actors=[pid["Gaius Valerius"], pid["Lucan Valerius"]], houses=["Valerius", "Corvane", "Theren"], place="the council hall")

    # everyone in Corva heard: first beliefs about the Flight, by house
    present = rows(con, "select p.id, p.name, p.born_year, p.caution, h.name house from people p join house_members m on m.person_id = p.id "
                        "join houses h on h.id = m.house_id where p.alive = 1 and p.absent = 0")
    for p in present:
        if -p["born_year"] < 10:
            continue
        mix = FLIGHT_MIX.get(p["house"], FLIGHT_MIX["default"])
        if p["name"] == "Tiberon Theren":
            mix = {"force": 0.6, "willing": 0.3, "plot": 0.1}
        view = r.choices(list(mix), weights=list(mix.values()))[0]
        text, about, stance = FLIGHT_VIEWS[view]
        belief(p["id"], "event", flight, text, 0.35 + (1 - p["caution"]) * 0.4, about, stance, "told_by")
        if r.random() < 0.35:
            t, _ = r.choice(DESTINATIONS)
            belief(p["id"], "event", flight, t, 0.25 + r.random() * 0.3, None, None, "told_by")
        # Valerius's demand: how each house's people stand toward Valerius now (PROPOSED)
        if p["house"] == "Theren":
            belief(p["id"], "event", dem2, "Valerius wants Theren blood for a wrong Theren did not do.", 0.5, "Valerius", -0.4, "told_by")
        if p["house"] == "Valerius":
            belief(p["id"], "event", dem2, "Corvane failed to keep its word, and Theren sheltered the thief.", 0.6, "Corvane", -0.4, "witnessed")
    # Ismene's own reading of her dream, and the attendants' dismissal
    belief(pid["Ismene"], "dream", "y0-autumn-ismene", "The sea took the Corvane ring and two lives left the sky of Corva; I saw it before it happened.", 0.8, source="own_dream")
    for m in members["Aurelian"]:
        if m["id"] not in (pid["Ismene"],) and -m["born_year"] >= 16 and r.random() < 0.5:
            belief(m["id"], "event", told, "An old woman's ramblings.", 0.4, source="told_by")

    # private truths: character-only memories (never in reports)
    def private(person, text):
        insert(con, "memories", year=Y0, season=AUTUMN, person_id=person, source_type="event", source_id=str(flight),
               text=text, vividness=0.95, private=1)
    private(pid["Livia Corvane"], "I love Soren, truly; and leaving was also my escape from the life that had been decided for me.")
    private(pid["Neria"], "I knew of them for years. I helped arrange their going, and I was the only one who knew it would be that night.")
    private(pid["Tiberon Theren"], "I never accepted him as a brother. I have never acted on it.")
    # (Galen: whether he knows Soren's father is undecided, even to the creator: nothing is stored.)

    # public memories of the festival night for everyone present
    for p in present:
        insert(con, "memories", year=Y0, season=AUTUMN, person_id=p["id"], source_type="event", source_id=str(flight),
               text="The festival night, when Livia Corvane and Soren of the Harbor were gone by sunrise.", vividness=0.7 + r.random() * 0.2)
    for p in present:
        if r.random() < 0.3:
            insert(con, "memories", year=Y0, season=AUTUMN, person_id=p["id"], source_type="event", source_id=str(told),
                   text="The old priestess's dream of a golden ring sinking and two stars going out.", vividness=0.5 + r.random() * 0.3)

    # legends
    for h, (title, text) in LEGENDS.items():
        insert(con, "legends", year=None, season=None, house_id=house_id[h] if h else None, title=title, text=text, proposed=1)

    # clients
    total = 0
    for h, spec in HOUSES.items():
        n = spec[5]
        loyalty = 0.68 + r.random() * 0.1 - (0.08 if h in ("Corvane", "Theren") else 0)   # the scandal touches both
        insert(con, "house_clients", year=Y0, season=AUTUMN, house_id=house_id[h], count=n, loyalty=round(loyalty, 2))
        total += n
    insert(con, "house_clients", year=Y0, season=AUTUMN, house_id=None, count=200 - total, loyalty=None)
    insert(con, "townsfolk", year=Y0, season=AUTUMN, count=200, mood=-0.1, food_share=1.0)

    # sealed: where the lovers truly are (unseeded: not even the seed above can reproduce it)
    where = SEALED_CANDIDATES[secrets.randbelow(len(SEALED_CANDIDATES))]
    insert(con, "sealed_facts", key="lovers_location", value=json.dumps({"place_id": place_id(con, where), "chosen": "genesis, year 0 autumn"}))
    con.commit()
    n_people = one(con, "select count(*) n from people")["n"]
    n_beliefs = one(con, "select count(*) n from beliefs")["n"]
    print(f"genesis: {len(HOUSES)} houses, {n_people} people "
          f"({one(con, 'select count(*) n from people where tier = ?', 'principal')['n']} principals), "
          f"{one(con, 'select count(*) n from events')['n']} events, {n_beliefs} beliefs, 200 townsfolk; "
          f"the lovers' location is sealed")


if __name__ == "__main__":
    genesis()
