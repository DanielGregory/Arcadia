"""Download DreamBank dream reports from the Hugging Face dataset "DReAMy-lib/DreamBank-dreams-en".

Keeps reports of 50-400 words (whitespace-split), with whitespace normalised and
no content filtering. Two format fixes are applied first: Mac Roman mojibake is
repaired, and the study questionnaire some series append after the dream
("Answers to questions 2. Frustrated... 3. actual participant4. unpleasant5. ...")
is cut off. The kept reports are cached as JSON lines in
data/raw/dreambank/reports_v2.jsonl, so later builds need neither the network
nor the `datasets` library.

Usage:
    python -m engine.data_prep.fetch_dreambank            # fetch and cache
    python -m engine.data_prep.fetch_dreambank --refresh  # re-download

If the network blocks Hugging Face's xet storage host, set HF_HUB_DISABLE_XET=1
to download through the plain CDN instead.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DATASET = "DReAMy-lib/DreamBank-dreams-en"
MIN_WORDS = 50
MAX_WORDS = 400

# A few reports are Mac Roman text mis-decoded as Latin-1 ("ÒIÕll fix thisÓ").
# Repair the punctuation and accents; this is an encoding fix, not content filtering.
MOJIBAKE = str.maketrans({"Ò": "“", "Ó": "”", "Ô": "‘", "Õ": "’", "Ð": "–", "Ñ": "—",
                          "\x8e": "é", "\xad": "-"})

# The Hall female-student series ends each report with the study's questionnaire
# answers. That is survey apparatus, not dream text, so everything from this
# phrase on is removed (the dream itself is untouched).
QUESTIONNAIRE = re.compile(r"\s*Answers to questions\b.*$", re.DOTALL)

CACHE_NAME = "reports_v2.jsonl"  # v2: questionnaire trailers removed


def download(hf_cache: Path) -> list[dict]:
    from datasets import load_dataset  # imported lazily: only needed on a cache miss

    ds = load_dataset(DATASET, split="train", cache_dir=str(hf_cache))
    kept = []
    for row in ds:
        text = QUESTIONNAIRE.sub("", (row["dreams"] or "").translate(MOJIBAKE))
        text = re.sub(r"\s+", " ", text).strip()
        if MIN_WORDS <= len(text.split()) <= MAX_WORDS:
            kept.append({"series": row["series"], "text": text})
    return kept


def load_reports(data_dir: Path = Path("data"), refresh: bool = False) -> list[dict]:
    """Return the filtered reports as dicts with "series" and "text", in dataset order."""
    cache = data_dir / "raw" / "dreambank" / CACHE_NAME
    if cache.exists() and not refresh:
        with cache.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f]
    reports = download(data_dir / "raw" / "hf")
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("w", encoding="utf-8") as f:
        for r in reports:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    reports = load_reports(args.data_dir, args.refresh)
    chars = sum(len(r["text"]) for r in reports)
    print(f"{len(reports):,} reports with {MIN_WORDS}-{MAX_WORDS} words, {chars:,} characters")


if __name__ == "__main__":
    main()
