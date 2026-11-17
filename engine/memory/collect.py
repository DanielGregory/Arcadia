"""Gather every dream Arcadia has dreamed so far, from wherever it was saved.

Each dream becomes one dict with a stable id (re-running never duplicates):

    id        e.g. "run4-read-07", "run2-priming-3.2", "run3-sample-2", "morning-2026-11-17",
              "morning-2026-11-17-c05" (a candidate that morning that wasn't chosen)
    run       which model dreamed it: run2 / run3 / run4
    kind      read_test | priming | sample | morning | candidate | test
    tag       the voice it was dreamed in: dream / myth / tale / saga
    prompt    the opening it was started from ("" = none)
    text      the dream as dreamed
    remembered  the editor's "as remembered" version, when there is one
    day       for morning dreams, the morning (YYYY-MM-DD)

Sources:
    out/read_test/run*.json                  read tests (+ run2_remembered.json)
    out/priming/run2.md                      the run 2 priming test
    checkpoints/run*/kaggle.log, *.kaggle.log, sample.txt   samples printed during training
    daily/mornings/*.json                    every published morning, with its candidates
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAGS = ("dream", "myth", "tale", "saga", "poem", "wisdom", "chronicle")
_PASSAGE = re.compile(rf"<({'|'.join(TAGS)})>\s*(.*?)\s*</\1>", re.S)


def read_tests() -> list[dict]:
    out = []
    remembered = {}
    rp = ROOT / "out/read_test/run2_remembered.json"
    if rp.exists():
        remembered = {d["n"]: d.get("as_remembered") for d in json.loads(rp.read_text(encoding="utf-8"))}
    for path in sorted((ROOT / "out/read_test").glob("run*.json")):
        if not re.fullmatch(r"run\d+", path.stem):
            continue
        for d in json.loads(path.read_text(encoding="utf-8")):
            out.append({"id": f"{path.stem}-read-{d['n']:02d}", "run": path.stem, "kind": "read_test", "tag": "dream",
                        "prompt": d.get("prompt", ""), "text": d["text"],
                        "remembered": remembered.get(d["n"]) if path.stem == "run2" else None})
    return out


def priming() -> list[dict]:
    path = ROOT / "out/priming/run2.md"
    if not path.exists():
        return []
    md = path.read_text(encoding="utf-8")
    prompts = {n: ("" if p == "(no priming)" else p) for n, p in re.findall(r"^## Prompt (\d+): (.*)$", md, re.M)}
    out = []
    for key, body in re.findall(r"^### (\d+\.\d+) .*?\n\n(.*?)(?=\n### |\n## |\Z)", md, re.S | re.M):
        out.append({"id": f"run2-priming-{key}", "run": "run2", "kind": "priming", "tag": "dream",
                    "prompt": prompts.get(key.split(".")[0], ""), "text": body.strip()})
    return out


def training_samples() -> list[dict]:
    """Passages printed in the training logs and sample.txt files (any voice)."""
    out, seen = [], set()
    for run_dir in sorted((ROOT / "checkpoints").glob("run*")):
        run = run_dir.name
        texts = []
        for log in sorted(run_dir.glob("*.log")):
            try:
                texts.append("".join(e["data"] for e in json.loads(log.read_text(encoding="utf-8"))))
            except (ValueError, KeyError):
                continue
        sample = run_dir / "sample.txt"
        if sample.exists():
            texts.append(sample.read_text(encoding="utf-8"))
        n = 0
        for text in texts:
            for tag, body in _PASSAGE.findall(text.replace("\r\n", "\n")):
                body = body.strip()
                if len(body.split()) < 25 or body[:80] in seen:
                    continue
                seen.add(body[:80])
                n += 1
                out.append({"id": f"{run}-sample-{n}", "run": run, "kind": "sample", "tag": tag, "prompt": "",
                            "text": body})
    return out


def mornings() -> list[dict]:
    out = []
    for path in sorted((ROOT / "daily/mornings").glob("*.json")):
        out += morning_dreams(json.loads(path.read_text(encoding="utf-8")))
    return out


def morning_dreams(r: dict) -> list[dict]:
    """The chosen dream and every other candidate of one morning record."""
    day = r["day"]
    out = []
    for c in r.get("candidates", []):
        chosen = c["i"] == r.get("chosen")
        out.append({"id": f"morning-{day}" if chosen else f"morning-{day}-c{c['i']:02d}", "run": r.get("run", "run4"),
                    "kind": "morning" if chosen else "candidate", "tag": c.get("tag", "dream"),
                    "prompt": c.get("opening", ""), "text": c["text"],
                    "remembered": r.get("as_remembered") if chosen else None, "day": day})
    return out


def test_mornings() -> list[dict]:
    """Candidates from morning-job test runs kept locally (out/morning/<day>_<label>/), e.g. the first
    Morning 1 (the wheelchair dream) and the art-style test. Dreams all the same, so remembered too."""
    out = []
    for path in sorted((ROOT / "out/morning").glob("*_*/morning.json")):
        label = path.parent.name.split("_", 1)[1]
        for d in morning_dreams(json.loads(path.read_text(encoding="utf-8"))):
            d["id"] = d["id"].replace("morning-", f"test-{label}-", 1)
            d["kind"] = "test"
            out.append(d)
    return out


def all_dreams() -> list[dict]:
    dreams = read_tests() + priming() + training_samples() + mornings() + test_mornings()
    by_id = {}
    for d in dreams:
        d.setdefault("remembered", None)
        d.setdefault("day", None)
        by_id[d["id"]] = d
    return list(by_id.values())


if __name__ == "__main__":
    from collections import Counter

    ds = all_dreams()
    print(len(ds), "dreams;", dict(Counter(d["kind"] for d in ds)), dict(Counter(d["tag"] for d in ds)))
