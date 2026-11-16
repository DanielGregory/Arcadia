"""Download Project Gutenberg books as plain text and strip the Gutenberg boilerplate.

Usage:
    python -m engine.data_prep.fetch_gutenberg 1727 8395 11 --out data/gutenberg
    python -m engine.data_prep.fetch_gutenberg --ids-file ids.txt
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import requests
from tqdm import tqdm

# Gutenberg mirrors a book's plain text at several URLs; try them in order.
URL_PATTERNS = [
    "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://www.gutenberg.org/files/{id}/{id}-0.txt",
    "https://www.gutenberg.org/files/{id}/{id}.txt",
]

START_RE = re.compile(
    r"^\*{3}\s*START OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK.*?\*{3}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
END_RE = re.compile(
    r"^\*{3}\s*END OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK.*?\*{3}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# Older files use different markers.
LEGACY_START_RE = re.compile(r"^\*END\*THE SMALL PRINT!.*$", re.MULTILINE)
LEGACY_END_RE = re.compile(r"^End of (?:the )?Project Gutenberg.*$", re.IGNORECASE | re.MULTILINE)

HEADERS = {"User-Agent": "arcadia-data-prep/0.1"}


def fetch_raw(book_id: int, session: requests.Session, timeout: float = 30.0) -> str:
    """Return the raw text of a book, trying each known URL pattern."""
    last_err: Exception | None = None
    for pattern in URL_PATTERNS:
        url = pattern.format(id=book_id)
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200 and resp.content:
                return resp.content.decode("utf-8-sig", errors="replace")
        except requests.RequestException as err:
            last_err = err
    raise RuntimeError(f"could not download book {book_id}") from last_err


def strip_gutenberg(text: str) -> str:
    """Remove the Project Gutenberg header and license footer."""
    text = text.replace("\r\n", "\n")

    start = START_RE.search(text) or LEGACY_START_RE.search(text)
    if start:
        text = text[start.end():]

    end = END_RE.search(text) or LEGACY_END_RE.search(text)
    if end:
        text = text[: end.start()]

    return text.strip() + "\n"


def read_ids(ids: list[int], ids_file: Path | None) -> list[int]:
    out = list(ids)
    if ids_file:
        for line in ids_file.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(int(line))
    # Keep order, drop duplicates.
    return list(dict.fromkeys(out))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*", type=int, help="Gutenberg book IDs")
    parser.add_argument("--ids-file", type=Path, help="file with one book ID per line (# comments allowed)")
    parser.add_argument("--out", type=Path, default=Path("data/gutenberg"), help="output directory")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds to wait between downloads")
    parser.add_argument("--overwrite", action="store_true", help="re-download books that already exist")
    args = parser.parse_args()

    book_ids = read_ids(args.ids, args.ids_file)
    if not book_ids:
        parser.error("give at least one book ID or --ids-file")

    args.out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    failed: list[int] = []
    for book_id in tqdm(book_ids, desc="gutenberg"):
        dest = args.out / f"{book_id}.txt"
        if dest.exists() and not args.overwrite:
            continue
        try:
            text = strip_gutenberg(fetch_raw(book_id, session))
        except RuntimeError as err:
            tqdm.write(str(err))
            failed.append(book_id)
            continue
        dest.write_text(text, encoding="utf-8")
        time.sleep(args.delay)

    done = len(book_ids) - len(failed)
    print(f"{done}/{len(book_ids)} books in {args.out}")
    if failed:
        print("failed:", " ".join(map(str, failed)))


if __name__ == "__main__":
    main()
