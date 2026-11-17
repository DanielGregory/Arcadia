"""Copy check: does generated text repeat the training text word for word?

For every sample, finds the longest run of consecutive words that also appears
verbatim in data/train.txt (whitespace-normalised, tags removed). Short shared
runs ("I was in the living room with") are ordinary language; long ones mean
the model is reproducing its training data, which matters most for DreamBank
(real people's dreams) and before anything is published.

    python -m engine.copy_check --text "some generated passage ..."
    python -m engine.copy_check --file samples.txt            # passages separated by blank lines or tags
    python -m engine.copy_check --kaggle_log checkpoints/run3/kaggle.log

Flags any sample whose longest copied run is FLAG_WORDS words or more.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

FLAG_WORDS = 12
TAG = re.compile(r"</?(?:dream|myth|tale|saga)>|\[length limit\]")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", text)).strip()


def longest_copied_run(sample: str, train: str) -> tuple[int, str]:
    """(length in words, the run itself) of the longest word sequence of `sample` found in `train`."""
    words = normalise(sample).split()
    best, best_run = 0, ""
    i = 0
    while i < len(words):
        # grow a window starting at i for as long as it still occurs in the training text
        j = i + max(best, 1)
        if j > len(words) or " ".join(words[i:j]) not in train:
            i += 1
            continue
        while j < len(words) and " ".join(words[i:j + 1]) in train:
            j += 1
        best, best_run = j - i, " ".join(words[i:j])
        i += 1
    return best, best_run


def split_samples(text: str) -> list[str]:
    parts = re.split(r"</(?:dream|myth|tale|saga)>|={5}.*?={5}", text)
    return [normalise(p) for p in parts if len(normalise(p).split()) >= 15]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train", type=Path, default=Path("data/train.txt"))
    parser.add_argument("--text")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--kaggle_log", type=Path, help="a Kaggle run log; checks every sample printed in it")
    args = parser.parse_args()

    train = normalise(args.train.read_text(encoding="utf-8"))
    if args.text:
        samples = [normalise(args.text)]
    elif args.file:
        samples = split_samples(args.file.read_text(encoding="utf-8"))
    else:
        log = json.loads(args.kaggle_log.read_text(encoding="utf-8"))
        stdout = "".join(e["data"] for e in log if e["stream_name"] == "stdout")
        samples = split_samples(stdout[stdout.find("===== temperature"):])

    worst = 0
    for k, s in enumerate(samples, 1):
        n, run = longest_copied_run(s, train)
        worst = max(worst, n)
        flag = "  FLAG" if n >= FLAG_WORDS else ""
        print(f"{k:2d}. {len(s.split()):4d} words | longest copied run {n:2d} words{flag} | {run[:90]}")
    print(f"\n{len(samples)} samples; longest copied run overall: {worst} words "
          f"({'flagged' if worst >= FLAG_WORDS else 'nothing flagged'}, threshold {FLAG_WORDS})")


if __name__ == "__main__":
    main()
