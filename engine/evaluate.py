"""Score a checkpoint on a validation file, in bits per character, overall and per source tag.

    python -m engine.evaluate --ckpt run5/best.pt --val data/val.txt              # run 4's fixed benchmark
    python -m engine.evaluate --ckpt run5/best.pt --val data/run5/val.txt --keep_tags   # run 5's own val set

Why bits per CHARACTER: run 4 and run 5 use different tokenizers, so a loss per
token isn't comparable (a model with longer tokens has fewer, harder
predictions). Converting the total loss to bits and dividing by the number of
characters gives a number that compares across any tokenizer.

Fairness on run 4's benchmark (the default): every source tag is removed, so
both models read exactly the same plain text and neither is helped or hurt by
tags it has or hasn't seen. Results are still grouped by the tag each passage
had, so you can see which kinds of text each model learned best.

Method: the text of each group is tokenised and cut into windows of the
model's block size; each window is scored once (no overlap), and the summed
negative log-likelihood is converted to bits per character.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import torch
from torch.nn import functional as F

from engine.sample import load

TAG = re.compile(r"<(dream|myth|tale|saga|poem|wisdom|chronicle)>\n?(.*?)\n?</\1>", re.S)


def passages(text: str) -> dict[str, list[str]]:
    """{tag: [passage text without its tags]}; text outside any tag goes under "untagged"."""
    groups: dict[str, list[str]] = defaultdict(list)
    for m in TAG.finditer(text):
        groups[m.group(1)].append(m.group(2))
    rest = TAG.sub("", text).strip()
    if rest:
        groups["untagged"].append(rest)
    return groups


@torch.no_grad()
def nll_bits(model, tok, text: str, device: str, batch: int = 32) -> tuple[float, int]:
    """(total bits, characters) for text, scored in non-overlapping windows."""
    ids = torch.tensor(tok.encode(text), dtype=torch.long)
    T = model.config.block_size
    n = (len(ids) - 1) // T
    if n == 0:
        return 0.0, 0
    x = ids[: n * T].view(n, T)
    y = ids[1: n * T + 1].view(n, T)
    total = 0.0
    for i in range(0, n, batch):
        xb, yb = x[i:i + batch].to(device), y[i:i + batch].to(device)
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=device == "cuda"):
            logits, _ = model(xb, yb)
        total += F.cross_entropy(logits.float().reshape(-1, logits.size(-1)), yb.reshape(-1), reduction="sum").item()
    chars = len(tok.decode(ids[1: n * T + 1].tolist()))  # the characters actually predicted
    return total / math.log(2), chars


def evaluate(ckpt: str, val: Path, keep_tags: bool, device: str) -> dict:
    model, tok, info = load(ckpt, device)
    text = val.read_text(encoding="utf-8")
    groups = passages(text)
    out, bits_all, chars_all = {}, 0.0, 0
    for tag, ps in sorted(groups.items()):
        body = "\n\n".join(f"<{tag}>\n{p}\n</{tag}>" if keep_tags and tag != "untagged" else p for p in ps)
        bits, chars = nll_bits(model, tok, body, device)
        if chars:
            out[tag] = round(bits / chars, 4)
            bits_all += bits
            chars_all += chars
    out["overall"] = round(bits_all / chars_all, 4)
    out["chars"] = chars_all
    out["params_m"] = round(sum(p.numel() for p in model.parameters()) / 1e6, 1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ckpt", required=True, nargs="+", help="one or more checkpoints to compare")
    parser.add_argument("--val", type=Path, required=True)
    parser.add_argument("--keep_tags", action="store_true", help="score the text with its tags (a model's own val set)")
    parser.add_argument("--out", type=Path, help="write the results as JSON")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    results = {}
    for ckpt in args.ckpt:
        results[ckpt] = evaluate(ckpt, args.val, args.keep_tags, args.device)
        print(ckpt, json.dumps(results[ckpt]), flush=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
