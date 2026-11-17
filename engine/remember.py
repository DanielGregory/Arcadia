"""Stage 2, "as remembered": tidy a raw dream without changing what happened in it.

The dream model writes "as dreamed": vivid, but full of broken grammar and
misspellings. Here a small instruction-following model (Qwen2.5-1.5B-Instruct,
runs on CPU) acts as a strict copy editor: it fixes spelling and grammar only,
and must keep every image, name and event, in order, and add nothing.

Because a language model can't be trusted to obey, every edit is measured:

    content-word retention = share of the raw dream's content words (nouns,
    verbs, names... everything except common function words) that still
    appear in the remembered version, counting every occurrence. A corrected
    spelling counts as kept (close matches are accepted). Under 80% is
    flagged: the editor dropped or replaced too much.

    added words = share of the remembered version's content words that were
    not in the raw dream: a sign the editor invented something.

Usage:
    python -m engine.remember --in out/read_test/run2.json --out out/read_test/run2_remembered
    python -m engine.remember --text "I was walking by the wine-dark sea and the ship ..."

The first run downloads the model (~3 GB) into the Hugging Face cache.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import time
from pathlib import Path

MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
FLAG_BELOW = 0.80         # content-word retention
LENGTH_FLAG_BELOW = 0.90  # remembered length / dreamed length, in words: catches dropped sentences
                          # made only of function words ("I will go," I answered.)
ADDED_FLAG_ABOVE = 0.10   # share of new content words: catches rewording ("cool and death" -> "cool and mysterious")

SYSTEM_PROMPT = """You are a careful copy editor for dream journals.
You will be given a dream exactly as it was written down. Rewrite it with correct spelling, grammar and punctuation, and nothing else.

Rules:
- Keep every image, object, person, name, place and event, in the same order.
- Do not add anything: no new details, explanations, interpretations, titles or summaries.
- Do not remove anything, even if it is strange, contradictory or makes no sense. Dreams are like that.
- Keep the dreamer's voice, wording, person (I/we/he) and tense where possible. Change a word only to fix a clear mistake.
- Keep invented or unusual names exactly as written. If a word is misspelled and the intended word is obvious, fix it; if not, leave it unchanged.
- Old-fashioned language (thou, hath, spake) is correct: leave it.
Reply with the corrected dream only."""

# Common function words, ignored when measuring retention.
STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers herself him
himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only or other
our ours ourselves out over own same she should so some such than that the their theirs them themselves then there
these they this those through to too under until up upon very was we were what when where which while who whom why
will with would you your yours yourself yourselves thee thou thy thine ye hath doth shall unto o oh also very still
one ones like went go going get got come came said says say saw see thing things
""".split())

_WORD = re.compile(r"[A-Za-zÀ-ÿ]+(?:['’][A-Za-z]+)?")


def content_words(text: str) -> list[str]:
    return [w for w in (m.group().lower() for m in _WORD.finditer(text))
            if len(w) > 2 and w not in STOPWORDS]


def _matched(words: list[str], pool: list[str]) -> int:
    """How many items of `words` can be paired off with distinct items of `pool`.

    Exact matches are paired first, then close spellings (similarity >= 0.8), so a
    corrected misspelling ("dancin" -> "dancing") still counts as the same word.
    Every occurrence counts: a dropped sentence whose words also appear elsewhere
    in the dream still lowers the score.
    """
    from collections import Counter

    left = Counter(pool)
    unmatched = []
    for w in words:
        if left[w] > 0:
            left[w] -= 1
        else:
            unmatched.append(w)
    n = len(words) - len(unmatched)
    for w in unmatched:
        close = difflib.get_close_matches(w, [x for x, c in left.items() if c > 0], n=1, cutoff=0.8)
        if close:
            left[close[0]] -= 1
            n += 1
    return n


def length_ratio(raw: str, remembered: str) -> float:
    return len(remembered.split()) / max(1, len(raw.split()))


def is_flagged(raw: str, remembered: str) -> bool:
    kept, added = retention(raw, remembered)
    return kept < FLAG_BELOW or added > ADDED_FLAG_ABOVE or length_ratio(raw, remembered) < LENGTH_FLAG_BELOW


def retention(raw: str, remembered: str) -> tuple[float, float]:
    """(share of the raw dream's content words kept, share of the remembered version's content words that are new).

    Counted over every occurrence, not distinct words.
    """
    raw_w, rem_w = content_words(raw), content_words(remembered)
    if not raw_w:
        return 1.0, 0.0
    kept = _matched(raw_w, rem_w) / len(raw_w)
    added = (1 - _matched(rem_w, raw_w) / len(rem_w)) if rem_w else 0.0
    return kept, added


class Rememberer:
    """Loads the editor model once; .remember(text) returns the tidied dream."""

    def __init__(self, model_id: str = MODEL_ID, threads: int | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if threads:
            torch.set_num_threads(threads)
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.float32)
        self.model.eval()

    def remember(self, dream: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": dream}]
        prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tok(prompt, return_tensors="pt")
        n_in = len(self.tok(dream)["input_ids"])
        with self.torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=int(n_in * 1.3) + 40,  # room for fixes, not for new material
                do_sample=False,                       # greedy: the most faithful, and repeatable
                repetition_penalty=1.0,
            )
        return self.tok.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="inp", type=Path, help="JSON list of dreams with a 'text' field (e.g. out/read_test/run2.json)")
    parser.add_argument("--out", type=Path, help="output path without extension: writes .json and .md")
    parser.add_argument("--text", help="remember a single dream given on the command line")
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--rescore", action="store_true",
                        help="recompute retention for an existing --out .json without running the editor again")
    args = parser.parse_args()

    if args.rescore:
        rescore(args.out)
        return
    editor = Rememberer(threads=args.threads)
    if args.text:
        remembered = editor.remember(args.text)
        kept, added = retention(args.text, remembered)
        print(remembered)
        ratio = length_ratio(args.text, remembered)
        print(f"\nretention {kept:.0%} | added {added:.0%} | length {ratio:.0%}"
              f"{'  FLAG' if is_flagged(args.text, remembered) else ''}")
        return

    dreams = json.loads(args.inp.read_text(encoding="utf-8"))
    write_results(args.out, _run(editor, dreams))


def _run(editor: "Rememberer", dreams: list[dict]) -> list[dict]:
    results = []
    t0 = time.time()
    for d in dreams:
        t = time.time()
        remembered = editor.remember(d["text"])
        kept, added = retention(d["text"], remembered)
        ratio = length_ratio(d["text"], remembered)
        flagged = is_flagged(d["text"], remembered)
        results.append({**d, "as_remembered": remembered, "retention": round(kept, 3), "added": round(added, 3),
                        "length": round(ratio, 3), "flagged": flagged})
        print(f"{d['n']:2d} retention {kept:4.0%} added {added:4.0%} length {ratio:4.0%} {'FLAG' if flagged else '    '}"
              f" ({time.time() - t:.0f}s)", flush=True)
    print(f"edited {len(results)} dreams in {time.time() - t0:.0f}s")
    return results


def rescore(out: Path) -> None:
    results = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    for r in results:
        kept, added = retention(r["text"], r["as_remembered"])
        ratio = length_ratio(r["text"], r["as_remembered"])
        r.update(retention=round(kept, 3), added=round(added, 3), length=round(ratio, 3),
                 flagged=is_flagged(r["text"], r["as_remembered"]))
        print(f"{r['n']:2d} retention {kept:4.0%} added {added:4.0%} length {ratio:4.0%} {'FLAG' if r['flagged'] else ''}")
    write_results(out, results)


def write_results(out: Path, results: list[dict]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    flagged = [r["n"] for r in results if r["flagged"]]
    lines = [
        "# As dreamed / as remembered", "",
        f"Editor: `{MODEL_ID}` (greedy, strict prompt: spelling and grammar only, keep every image, name and event, add nothing).",
        f"Retention = share of the raw dream's content words kept, every occurrence counted (close spellings count). "
        f"Length = remembered words / dreamed words. Flagged if retention < {FLAG_BELOW:.0%}, added > {ADDED_FLAG_ABOVE:.0%} "
        f"or length < {LENGTH_FLAG_BELOW:.0%}. The flags catch large changes only: read before keeping.", "",
        f"Mean retention {sum(r['retention'] for r in results) / len(results):.0%}; "
        f"flagged: {', '.join(map(str, flagged)) if flagged else 'none'}.", "",
    ]
    for r in results:
        flag = " · **FLAG**" if r["flagged"] else ""
        lines += [f"## {r['n']}. retention {r['retention']:.0%} · added {r['added']:.0%} · length {r.get('length', 1):.0%}{flag}", "",
                  "**As dreamed**", "", r["text"], "", "**As remembered**", "", r["as_remembered"], ""]
    out.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out.with_suffix('.md')} and .json")


if __name__ == "__main__":
    main()
