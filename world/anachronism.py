"""Words that cannot belong in Corva: modern things, and real-world peoples, places and gods.

Corva is its own world (VISION): an island city of oars and sails, oil lamps, bronze and stone, with
no Athens, Rome or Egypt in it and no Zeus or Mars over it. The dream model (run 5) was trained on
real-world text, so its dreams are full of both; that is fine in a raw dream (dreams are strange), but
not in what a person of Corva SAYS about the dream: their retelling, their reading, their intention.

    find("We sailed past Athens in a car")  ->  ["athens", "car"]

The interpreter is asked to try again without the words found; what still slips through is cut out
sentence by sentence (world/tick.py). The lists are deliberately plain, to be added to freely.
"""

from __future__ import annotations

import re

MODERN = [
    # machines and devices
    "car", "cars", "truck", "bus", "buses", "railway", "airplane", "aeroplane", "airport",
    "helicopter", "rocket", "bicycle", "motorcycle", "motor", "robot", "computer", "laptop",
    "internet", "email", "phone", "telephone", "cellphone", "television", "tv", "radio", "camera", "photo", "photograph",
    "movie", "video", "electric", "electricity", "battery", "light bulb", "lightbulb", "elevator", "escalator",
    "gun", "guns", "rifle", "pistol", "bomb", "bombs", "missile", "plastic", "cigarette", "tobacco",
    # places and institutions of the modern world
    "office", "offices", "school", "schools", "college", "university", "hospital", "police", "airport", "highway",
    "freeway", "parking", "garage", "apartment", "apartments", "neighborhood", "neighbourhood", "front yard", "backyard",
    "supermarket", "mall", "hotel", "restaurant", "cafe", "café", "cinema", "factory",
    "bleachers", "subway", 
    # (left out on purpose, because they have old meanings too: engine, machine, yard, theatre, stadium,
    #  hour, foot, pound, train, plane, film, kid, second)
    # money, food, clothes and talk of today
    "dollar", "dollars", "cent", "cents", "credit card", "coffee", "chocolate", "pizza", "sandwich", "potato", "potatoes",
    "tomato", "tomatoes", "jeans", "t-shirt", "sneakers", "mom", "dad", "okay", "ok", "guy", "guys", 
    "miles", "inches", 
    
]

REAL_WORLD = [
    # peoples and places
    "athens", "athenian", "athenians", "sparta", "spartan", "spartans", "rome", "roman", "romans", "greece", "greek",
    "greeks", "hellas", "hellenes", "egypt", "egyptian", "egyptians", "persia", "persian", "persians", "scythia",
    "scythian", "scythians", "troy", "trojan", "trojans", "carthage", "babylon", "assyria", "assyrian", "macedon",
    "macedonia", "macedonian", "thebes", "theban", "corinth", "delphi", "dodona", "susa", "locrian", "ionia", "ionian",
    "sicily", "crete", "cretan", "cyprus", "lydia", "phoenicia", "phoenician", "israel", "jerusalem", "india", "china",
    "chinese", "africa", "african", "europe", "european", "america", "american", "england", "english", "britain",
    "british", "france", "french", "germany", "german", "spain", "spanish", "italy", "italian", "london", "paris",
    "new york", "mediterranean", "aegean", "olympus", "olympia",
    # gods, heroes and rulers of the real world's stories
    "zeus", "hera", "apollo", "athena", "ares", "mars", "jupiter", "juno", "venus", "mercury", "neptune", "poseidon",
    "hermes", "dionysus", "bacchus", "hades", "jesus", "christ", "christian", "allah", "buddha", "homer", "achilles",
    "odysseus", "ulysses", "hector", "agamemnon", "hercules", "heracles", "telamon", "darius", "dareios", "xerxes",
    "alexander", "caesar", "pericles", "socrates", "plato", "aristotle",
]

_PATTERNS = [(w, re.compile(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", re.I)) for w in sorted(set(MODERN + REAL_WORLD), key=len, reverse=True)]


def find(text: str) -> list[str]:
    """The out-of-world words in a text (lowercase, each once, in the order of the lists)."""
    t = text or ""
    return [w for w, pat in _PATTERNS if pat.search(t)]


def strip(text: str) -> str:
    """The text without the sentences that contain an out-of-world word ('' if nothing is left)."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return " ".join(p for p in parts if p and not find(p)).strip()
