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

# Where to look for a book's plain text, in order. The main site is tried
# first; if it is down (e.g. for maintenance) the official mirrors run by
# PGLAF, Project Gutenberg's host, are tried with the same book ID.
MAIN_SITE = "https://www.gutenberg.org"
MIRRORS = [
    "https://gutenberg.pglaf.org",   # PGLAF; serves the same cache/epub files as the main site
    "https://aleph.gutenberg.org",   # PGLAF's main mirror (its HTTPS certificate was broken in Nov 2026)
]


def mirror_dir(book_id: int) -> str:
    """Mirror directory for a book: every digit but the last, then the ID.

    84 -> "8/84", 1727 -> "1/7/2/1727", 21765 -> "2/1/7/6/21765", 5 -> "0/5".
    """
    digits = str(book_id)
    parents = "/".join(digits[:-1]) if len(digits) > 1 else "0"
    return f"{parents}/{digits}"


def candidate_urls(book_id: int) -> list[tuple[str, str]]:
    """(url, encoding) pairs to try for one book, main site first."""
    urls = [
        (f"{MAIN_SITE}/cache/epub/{book_id}/pg{book_id}.txt", "utf-8"),
        (f"{MAIN_SITE}/files/{book_id}/{book_id}-0.txt", "utf-8"),
        (f"{MAIN_SITE}/files/{book_id}/{book_id}.txt", "utf-8"),
    ]
    for base in MIRRORS:
        d = mirror_dir(book_id)
        urls += [
            (f"{base}/cache/epub/{book_id}/pg{book_id}.txt", "utf-8"),  # same file as the main site
            (f"{base}/{d}/{book_id}-0.txt", "utf-8"),                    # UTF-8 edition
            (f"{base}/{d}/{book_id}.txt", "utf-8"),                      # plain-ASCII edition
            (f"{base}/{d}/{book_id}-8.txt", "latin-1"),                  # 8-bit (Latin-1) edition
        ]
    return urls


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
    """Return the raw text of a book from the main site, or a mirror if it fails."""
    last_err: Exception | str | None = None
    dead_hosts: set[str] = set()  # hosts that are down: skip their other URLs
    for url, encoding in candidate_urls(book_id):
        host = url.split("/")[2]
        if host in dead_hosts:
            continue
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as err:  # connection or TLS failure
            last_err = err
            dead_hosts.add(host)
            continue
        if resp.status_code >= 500:                # e.g. 503 during maintenance
            last_err = f"HTTP {resp.status_code} from {url}"
            dead_hosts.add(host)
            continue
        if resp.status_code == 200 and resp.content:
            if not url.startswith(MAIN_SITE):
                tqdm.write(f"book {book_id}: main site unavailable, using {url}")
            return resp.content.decode("utf-8-sig" if encoding == "utf-8" else encoding, errors="replace")
        last_err = f"HTTP {resp.status_code} from {url}"
    raise RuntimeError(f"could not download book {book_id} from gutenberg.org or its mirrors ({last_err})")


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
