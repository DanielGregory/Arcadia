"""Generate a read test: 20 dreams (5 unprimed, 15 primed), temperature 0.9.

    python out/read_test/make_read_test.py --run run2      (uses checkpoints/run2/best.pt)
    python out/read_test/make_read_test.py --run run4

Every run uses the same 20 openings and the same seeds, so read tests from
different runs can be compared dream by dream.
"""

import argparse

import json
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine.sample import generate_dream, load  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--run", default="run2")
args = parser.parse_args()
RUN = args.run
CKPT = f"checkpoints/{RUN}/best.pt"
OUT = Path("out/read_test")
SETTINGS = dict(temperature=0.9, top_p=0.9, repetition_penalty=1.1)
MAX_TOKENS = 250

PROMPTS = [""] * 5 + [
    # storyteller openings (third person, someone telling a tale)
    "The old shepherd told me of a tomb in the olive grove where",
    "The fisherman's wife said that long ago, before Corva had walls,",
    "They say that in the hills above Corva there was a well that",
    "An old woman by the harbour told the children how the first ship",
    "The herdsman sat by the fire and spoke of the night the river",
    "In the days before the city, the people of the shore believed that",
    "The traveller told us of a country beyond the mountains where",
    "My grandmother said that when she was a girl the stars over Corva",
    # "the gods" openings
    "In Corva, the city by the sea, I dreamed that the gods",
    "The gods of the harbour were angry, and the sea",
    "Before there were men in Corva, the gods",
    "The gods met on the mountain above the city and",
    "When the gods came down to the market at Corva,",
    "The god of the river and the god of the sea quarrelled over",
    "In the dream the gods of Corva were sleeping, and",
]

model, tok, ckpt_info = load(CKPT, "cpu")
dreams = []
t0 = time.time()
for n, prompt in enumerate(PROMPTS, 1):
    torch.manual_seed(1000 + n)  # one fixed seed per dream, so each is reproducible
    text, closed = generate_dream(model, tok, prompt, MAX_TOKENS, "cpu", **SETTINGS)
    dreams.append({"n": n, "prompt": prompt, "closed": closed, "text": text, "seed": 1000 + n})
    print(f"{n:2d} {'closed' if closed else 'cut   '} {len(text.split()):3d} words | {prompt[:50]}", flush=True)

(OUT / f"{RUN}.json").write_text(json.dumps(dreams, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
lines = [
    f"# Read test: {RUN}", "",
    f"Model `{CKPT}` (val {ckpt_info['val_bpc']:.3f} bits/char, step {ckpt_info['step']}). Temperature {SETTINGS['temperature']}, top-p {SETTINGS['top_p']}, "
    f"repetition penalty {SETTINGS['repetition_penalty']}, at most {MAX_TOKENS} tokens per dream, "
    "cut back to the last full sentence if it hit the limit. Seed 1000 + dream number.", "",
    "Mark the keepable ones by changing `[ ]` to `[x]`.", "",
    "- Dreams 1–5: no priming (just `<dream>`).",
    "- Dreams 6–13: storyteller openings.",
    "- Dreams 14–20: \"the gods\" openings.", "",
]
for d in dreams:
    kind = "unprimed" if not d["prompt"] else f"primed: *{d['prompt']}*"
    ending = "ended itself with </dream>" if d["closed"] else "cut at the length limit"
    lines += [f"## {d['n']}. [ ] keep", "", f"{kind} · {ending}", "", d["text"], ""]
(OUT / f"{RUN}.md").write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT / (RUN + '.md')} and {RUN}.json in {time.time() - t0:.0f}s")
