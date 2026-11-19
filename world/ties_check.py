"""Check the family relationships a written text claims against the engine's records.

Chroniclers and account writers may slant everything (that is the point of them), but they may not get a family
wrong: "his son, Galen" about Galen Theren is factual nonsense, not a point of view. This finds the relationships
a text claims and checks each against the records (lineage for parents and children, relationships for spouses,
shared parents for brothers and sisters).

    bad = wrong_ties(con, text)   ->  [{"sentence", "claim", "truth"}, ...]

Patterns it reads (A and B are people's names, full or an unambiguous first name; "his/her" means the last person
named before it in the sentence):
    A's son, B  /  A's son B          B, A's son          B, the son of A  /  B, son of A
    B is A's son  /  B is the son of A                  his son, B  /  her daughter B
    A and B are married  /  A and B were married
Relations: son, daughter, child, children (A's child), father, mother, parent, wife, husband, spouse, brother, sister.
A claim about someone the records don't know (or a relation they don't record: cousin, nephew, heir) is left alone.
"""

from __future__ import annotations

import re
from collections import Counter

from world.db import rows

CHILD = {"son", "daughter", "child", "children", "sons", "daughters"}
PARENT = {"father", "mother", "parent"}
SPOUSE = {"wife", "husband", "spouse"}
SIBLING = {"brother", "sister", "brothers", "sisters"}
RELS = CHILD | PARENT | SPOUSE | SIBLING


class Family:
    def __init__(self, con):
        self.people = {p["id"]: p for p in rows(con, "select id, name from people")}
        self.parents = {}
        for l in rows(con, "select parent_id, child_id from lineage"):
            self.parents.setdefault(l["child_id"], set()).add(l["parent_id"])
        self.spouses = {}
        for r in rows(con, "select person_a, person_b from relationships where kind = 'spouse'"):
            self.spouses.setdefault(r["person_a"], set()).add(r["person_b"])
            self.spouses.setdefault(r["person_b"], set()).add(r["person_a"])
        firsts = Counter(p["name"].split()[0] for p in self.people.values())
        self.by_name = {}
        for pid, p in self.people.items():
            self.by_name[p["name"]] = pid
            first = p["name"].split()[0]
            if firsts[first] == 1 and len(first) > 2:
                self.by_name.setdefault(first, pid)
        names = sorted(self.by_name, key=len, reverse=True)
        self.name_re = "(" + "|".join(re.escape(n) for n in names) + r")(?![\w])"

    def children(self, a):
        return {c for c, ps in self.parents.items() if a in ps}

    def holds(self, b: int, rel: str, a: int) -> bool:
        """Is B the <rel> of A?"""
        if a == b:
            return False
        if rel in CHILD:
            return a in self.parents.get(b, set())
        if rel in PARENT:
            return b in self.parents.get(a, set())
        if rel in SPOUSE:
            return b in self.spouses.get(a, set())
        if rel in SIBLING:
            return bool(self.parents.get(a, set()) & self.parents.get(b, set()))
        return True

    def describe(self, a: int) -> str:
        """The true family of A, for the rewrite request."""
        n = lambda ids: ", ".join(sorted(self.people[i]["name"] for i in ids if i in self.people)) or "none recorded"
        sib = {s for p in self.parents.get(a, set()) for s in self.children(p)} - {a}
        return (f"{self.people[a]['name']}: parents {n(self.parents.get(a, set()))}; children {n(self.children(a))}; "
                f"spouse {n(self.spouses.get(a, set()))}; brothers and sisters {n(sib)}")


def wrong_ties(con, text: str, fam: Family | None = None) -> list[dict]:
    fam = fam or Family(con)
    N, R = fam.name_re, "(" + "|".join(sorted(RELS, key=len, reverse=True)) + ")"
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        claims = []   # (B, rel, A, span)
        for m in re.finditer(rf"{N}'s {R},? {N}", sent):                       # A's son, B
            claims.append((m.group(3), m.group(2), m.group(1), m.group(0)))
        for m in re.finditer(rf"{N}, {N}'s {R}\b", sent):                      # B, A's son
            claims.append((m.group(1), m.group(3), m.group(2), m.group(0)))
        for m in re.finditer(rf"{N},? (?:is |was )?(?:the )?{R} of {N}", sent):  # B, the son of A / B is the son of A
            claims.append((m.group(1), m.group(2), m.group(3), m.group(0)))
        for m in re.finditer(rf"{N} (?:is|was) {N}'s {R}\b", sent):           # B is A's son
            claims.append((m.group(1), m.group(3), m.group(2), m.group(0)))
        for m in re.finditer(rf"\b(?:his|her) {R},? {N}", sent):               # his son, B (his = the last person named)
            before = [x.group(1) for x in re.finditer(N, sent[: m.start()])]
            if before:
                claims.append((m.group(2), m.group(1), before[-1], m.group(0)))
        for m in re.finditer(rf"{N} and {N} (?:are|were) married", sent):
            claims.append((m.group(2), "spouse", m.group(1), m.group(0)))
        for b_name, rel, a_name, span in claims:
            a, b = fam.by_name.get(a_name), fam.by_name.get(b_name)
            if a is None or b is None or fam.holds(b, rel.lower(), a):
                continue
            out.append({"sentence": sent, "claim": span, "truth": fam.describe(a)})
    return out


def rewrite_note(bad: list[dict]) -> str:
    return ("\n(These family ties in your text are wrong: " + "; ".join(f"\"{b['claim']}\"" for b in bad)
            + ". The records: " + " | ".join(dict.fromkeys(b["truth"] for b in bad))
            + ". Write it again with the families right, or without naming the tie.)")


def drop_wrong(text: str, bad: list[dict]) -> str:
    """What survives a rewrite is cut sentence by sentence."""
    gone = {b["sentence"] for b in bad}
    return " ".join(s for s in re.split(r"(?<=[.!?])\s+", text) if s not in gone).strip()
