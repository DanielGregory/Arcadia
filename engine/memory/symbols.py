"""First-pass symbol extraction: the recurring concrete images in dreams.

A "symbol" here is only an IMAGE that recurs (sea, stairway, temple, ship,
cloud...), normalised and counted. It carries no meaning: what an image means
is for the inhabitants' beliefs to decide later (docs/world_engine.md: no
table stores meaning). This module just notices that the sea keeps coming back.

How it works, deliberately simple and readable:
  1. LEXICON maps each canonical symbol to the words that name it
     ("stairway": stair, stairs, staircase, steps, ...).
  2. Every word of a dream is lower-cased and reduced to a rough singular
     ("waves" -> "wave", "cities" -> "city"), then looked up.
  3. The result is {symbol: times mentioned} for that dream.

    from engine.memory.symbols import extract
    extract("I climbed the stairs to the temple by the sea")  # {'stairway': 1, 'temple': 1, 'sea': 1}
"""

from __future__ import annotations

import re
from collections import Counter

# canonical symbol -> words that name it (singular forms; plurals are handled by singular()).
LEXICON: dict[str, tuple[str, ...]] = {
    # water and shore
    "sea": ("sea", "ocean", "wave", "tide", "surf", "brine"),
    "river": ("river", "stream", "brook", "creek"),
    "water": ("water",),
    "lake": ("lake", "pond", "pool"),
    "shore": ("shore", "beach", "coast", "strand", "sand"),
    "harbour": ("harbour", "harbor", "port", "quay", "dock", "pier", "wharf"),
    "ship": ("ship", "boat", "galley", "vessel", "raft", "canoe", "barge", "sail", "oar"),
    "island": ("island", "isle"),
    "fish": ("fish",),
    # high places and buildings
    "mountain": ("mountain", "hill", "peak", "cliff", "crag", "summit"),
    "stairway": ("stair", "staircase", "stairway", "step", "ladder"),
    "temple": ("temple", "shrine", "sanctuary"),
    "altar": ("altar",),
    "tower": ("tower", "turret"),
    "palace": ("palace", "castle", "hall"),
    "city": ("city", "town", "village"),
    "house": ("house", "home", "cottage", "hut", "dwelling"),
    "room": ("room", "chamber"),
    "door": ("door", "doorway"),
    "gate": ("gate",),
    "window": ("window",),
    "wall": ("wall",),
    "bridge": ("bridge",),
    "road": ("road", "path", "street", "lane", "track"),
    "market": ("market", "marketplace", "bazaar", "store", "shop"),
    "tomb": ("tomb", "grave", "sepulchre", "cemetery"),
    "cave": ("cave", "cavern", "grotto"),
    "column": ("column", "pillar"),
    # land and growing things
    "forest": ("forest", "wood", "woods", "grove", "jungle"),
    "tree": ("tree",),
    "olive": ("olive",),
    "garden": ("garden", "orchard", "vineyard"),
    "field": ("field", "meadow", "pasture"),
    "desert": ("desert",),
    "flower": ("flower", "rose", "lily", "blossom"),
    "stone": ("stone", "rock", "marble"),
    # sky and weather
    "sky": ("sky", "heaven", "heavens"),
    "cloud": ("cloud", "mist", "fog"),
    "sun": ("sun", "sunlight", "sunrise", "sunset", "dawn"),
    "moon": ("moon", "moonlight"),
    "star": ("star",),
    "night": ("night", "darkness"),
    "rain": ("rain",),
    "storm": ("storm", "thunder", "lightning", "tempest"),
    "wind": ("wind", "breeze", "gale"),
    "snow": ("snow", "ice"),
    "fire": ("fire", "flame", "blaze"),
    "smoke": ("smoke",),
    "light": ("light", "lamp", "lantern", "candle", "torch"),
    # creatures
    "bird": ("bird", "eagle", "dove", "raven", "owl", "crow", "hawk", "swan", "gull"),
    "horse": ("horse", "steed", "mare", "pony"),
    "dog": ("dog", "hound", "puppy"),
    "cat": ("cat", "kitten"),
    "serpent": ("snake", "serpent", "dragon", "viper"),
    "flock": ("sheep", "goat", "lamb", "flock", "herd", "ram"),
    "cattle": ("cow", "bull", "calf", "cattle", "ox", "oxen"),
    "wolf": ("wolf", "wolves"),
    "lion": ("lion",),
    # people and beings
    "god": ("god", "goddess", "deity"),
    "king": ("king", "emperor", "prince", "lord"),
    "queen": ("queen", "princess"),
    "priest": ("priest", "priestess", "prophet", "oracle"),
    "child": ("child", "children", "baby", "boy", "girl"),
    "mother": ("mother", "mom", "grandmother"),
    "father": ("father", "dad", "grandfather"),
    "stranger": ("stranger", "traveller", "traveler", "wanderer"),
    "giant": ("giant",),
    "ghost": ("ghost", "spirit", "phantom", "shade"),
    "crowd": ("crowd", "people", "multitude", "throng"),
    "shepherd": ("shepherd", "herdsman", "fisherman", "farmer"),
    "warrior": ("warrior", "soldier", "army", "hero"),
    # body
    "skeleton": ("skeleton", "bone", "skull"),
    "blood": ("blood",),
    "eye": ("eye",),
    "hand": ("hand",),
    "wing": ("wing",),
    "hair": ("hair",),
    "teeth": ("tooth", "teeth"),
    # things
    "sword": ("sword", "spear", "javelin", "knife", "dagger", "blade", "axe"),
    "crown": ("crown",),
    "gold": ("gold", "golden", "silver", "treasure", "coin"),
    "ring": ("ring",),
    "key": ("key",),
    "mirror": ("mirror",),
    "book": ("book", "scroll", "letter"),
    "bed": ("bed",),
    "cup": ("cup", "bowl", "goblet", "chalice"),
    "bread": ("bread", "feast", "food"),
    "wine": ("wine",),
    "car": ("car", "truck", "bus"),
    "school": ("school", "class", "classroom"),
    "church": ("church", "chapel", "cathedral"),
    "dress": ("dress", "robe", "cloak", "gown"),
    "music": ("song", "music", "harp", "lyre", "flute", "pipe"),
    # actions that are images
    "flying": ("fly", "flying", "flew", "flight", "soar", "soaring"),
    "falling": ("fall", "falling", "fell"),
    "swimming": ("swim", "swimming", "swam"),
}

# word -> symbol
_INDEX = {w: sym for sym, words in LEXICON.items() for w in words}
_WORD = re.compile(r"[a-z]+")


def singular(word: str) -> str:
    """A rough singular, good enough for a lexicon lookup ("cities" -> "city", "waves" -> "wave")."""
    if word in _INDEX:
        return word
    for suffix, repl in (("ies", "y"), ("ves", "f"), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            cand = word[: -len(suffix)] + repl
            if cand in _INDEX:
                return cand
            if suffix == "es" and word[:-1] in _INDEX:  # "waves" -> "wave", "stones" -> "stone"
                return word[:-1]
    return word


def extract(text: str) -> dict[str, int]:
    """{symbol: mentions} for one dream."""
    counts: Counter[str] = Counter()
    for word in _WORD.findall(text.lower().replace("’", "'")):
        sym = _INDEX.get(singular(word))
        if sym:
            counts[sym] += 1
    return dict(counts)
