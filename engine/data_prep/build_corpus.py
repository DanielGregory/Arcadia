"""Build the Arcadia training corpus from the reading list in `books.py` plus DreamBank.

Steps:
  1. Download each Gutenberg text (cached in data/raw/gutenberg/) and the
     DreamBank reports (cached in data/raw/dreambank/, see fetch_dreambank.py).
  2. Strip Gutenberg headers/footers, translator prefaces, introductions,
     notes, indexes and footnotes, using the per-book rules in books.py.
  3. Cap each SEASONING book at 4% of the final corpus by randomly sampling
     whole paragraphs to keep.
  4. Randomly sample whole DreamBank reports, each wrapped in <dream>...</dream>,
     until the "dreambank" tier is 25% of the final corpus.
  5. Write data/arcadia.txt, then a 90/10 train/val split (data/train.txt,
     data/val.txt): ~10% of each book's sections, and ~10% of the sampled
     dream reports, go to val.
  6. Print a per-source table, the tier split, and total and unique character counts.

Usage:
    python -m engine.data_prep.build_corpus
    python -m engine.data_prep.build_corpus --refresh --seed 7
"""

from __future__ import annotations

import argparse
import random
import re
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from tqdm import tqdm

from engine.data_prep.books import BOOKS, SEASONING, Book
from engine.data_prep.fetch_dreambank import load_reports
from engine.data_prep.fetch_gutenberg import HEADERS, fetch_raw, strip_gutenberg

SEASONING_CAP = 0.04
DREAMBANK = "dreambank"
DREAMBANK_SHARE = 0.25  # default; run 3 uses --dreambank_share 0.12

# Source tags (--tags, run 3 on): every passage of a book is wrapped in its
# tier's tag, the way each DreamBank report is wrapped in <dream>...</dream>.
# The tag tells the model which voice it is reading, and at sampling time
# lets us ask for a voice. Passages are runs of whole paragraphs of about
# PASSAGE_CHARS characters (~one 256-token training window), so almost every
# training window contains a tag.
TIER_TAGS = {"core": "myth", "dream": "tale", "seasoning": "saga"}
PASSAGE_CHARS = 1000
VAL_FRACTION = 0.10
# Sections longer than this share of their book are cut into paragraph-aligned
# chunks, so books with few long sections can still be split ~90/10.
MAX_SECTION_SHARE = 0.05

PARA_SEP = "\n\n"
BOOK_SEP = "\n\n\n"

# Paragraphs that are apparatus in any edition.
GENERIC_DROP = (
    r"\[(?:Illustration|Footnote|Redactor|Transcriber|Editor|Note)",
    r"\[\d+[a-z]?\]",      # footnote body: "[12] ..."
    r"\(\d+\)\s",          # footnote body: "(1)  ..."
    r"[+|][-=+| ]*$",      # ASCII boxes
    r"[*•\s]+$",           # "* * * * *" and "• • • • •" scene breaks
)
GENERIC_INLINE = (
    r"\[Illustration[^\]]*\]",
    r"\[\d+[a-z]?\]",      # footnote markers: "mass,[4]"
    r"\[\*\]",             # footnote markers: "Dummling,[*]"
    r"\{[\d\[\]\-]+\}",     # page/footnote numbers in braces: "{11}", "{[0-9]}"
    r"\[Note of[^\]]*\]",  # Coleridge's dated notes
    r"(?:\s*\*){2,}\s*$",  # trailing "* *" after a line
)
# Long verse paragraphs are cut at sentence-ending lines into pieces of about this size.
VERSE_CHUNK = 1500


@dataclass
class Para:
    text: str
    heading: bool = False


Section = list[Para]


# --------------------------------------------------------------------- fetch
def load_raw(book: Book, cache: Path, session: requests.Session, refresh: bool) -> str:
    path = cache / f"{book.gutenberg_id}.txt"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    text = fetch_raw(book.gutenberg_id, session)
    path.write_text(text, encoding="utf-8")
    time.sleep(1.0)  # be polite to gutenberg.org
    return text


# --------------------------------------------------------------------- clean
def _find(lines: list[str], pattern: str, start: int, nth: int = 1) -> int | None:
    rx = re.compile(pattern)
    seen = 0
    for i in range(start, len(lines)):
        if rx.fullmatch(lines[i].strip()):
            seen += 1
            if seen == nth:
                return i
    return None


def select_ranges(lines: list[str], book: Book) -> list[str]:
    kept: list[str] = []
    cursor = 0
    for r in book.ranges:
        i = _find(lines, r.start, cursor, r.nth)
        if i is None:
            raise ValueError(f"{book.gutenberg_id} {book.title}: start {r.start!r} (#{r.nth}) not found")
        j = len(lines)
        if r.end:
            found = _find(lines, r.end, i + 1)
            if found is None:
                raise ValueError(f"{book.gutenberg_id} {book.title}: end {r.end!r} not found")
            j = found
        kept += lines[i:j] + [""]
        cursor = j
    return kept


def drop_after_heading(lines: list[str], book: Book) -> list[str]:
    if not book.drop_after_heading:
        return lines
    head, sep, max_lines = book.drop_after_heading
    rh, rs = re.compile(head), re.compile(sep)
    out, i = [], 0
    while i < len(lines):
        out.append(lines[i])
        if rh.fullmatch(lines[i].strip()):
            for j in range(i + 1, min(i + 1 + max_lines, len(lines))):
                if rs.fullmatch(lines[j].strip()):
                    i = j
                    break
        i += 1
    return out


def drop_blocks(lines: list[str], book: Book) -> list[str]:
    for start, end in book.drop_blocks:
        rs, re_ = re.compile(start), re.compile(end)
        out, skipping = [], False
        for line in lines:
            s = line.strip()
            if skipping and re_.fullmatch(s):
                skipping = False
            elif not skipping and rs.fullmatch(s):
                skipping = True
            if not skipping:
                out.append(line)
        lines = out
    return lines


def split_paragraphs(lines: list[str]) -> list[str]:
    paras, cur = [], []
    for line in lines:
        if line.strip():
            cur.append(line.rstrip())
        elif cur:
            paras.append("\n".join(cur))
            cur = []
    if cur:
        paras.append("\n".join(cur))
    return paras


def generic_heading(text: str) -> bool:
    if "\n" in text or len(text) > 70:
        return False
    letters = [c for c in text if c.isalpha()]
    return len(letters) > 2 and sum(c.isupper() for c in letters) >= 0.8 * len(letters)


def clean_paragraph(raw: str, book: Book) -> str | None:
    if book.drop_indented and all(l[:1].isspace() for l in raw.split("\n")):
        return None
    para = textwrap.dedent(raw)
    for pat in GENERIC_DROP + book.drop_paragraphs:
        if re.match(pat, para):
            return None
    lines = para.split("\n")
    if book.verse or any(l[:1].isspace() for l in lines[1:]):
        para = "\n".join(re.sub(r"[ \t]+", " ", l).strip() for l in lines)  # keep verse lines
    else:
        para = re.sub(r"\s+", " ", " ".join(lines))                         # unwrap prose

    # Markers are removed after unwrapping, since they often sit at a line break.
    for pat in GENERIC_INLINE + book.inline_refs:
        para = re.sub(pat, "", para, flags=re.MULTILINE)
    para = re.sub(r"\{([^{}]*)\}", r"\1", para)  # Riley's {supplied words}
    para = para.replace("_", "")                  # _italics_
    para = para.replace("`", "‘")                 # old-style `opening quotes'
    para = re.sub(r"[ \t]{2,}", " ", para)
    para = re.sub(r"[ \t]+([,;:.!?])", r"\1", para)
    para = "\n".join(l.strip() for l in para.split("\n")).strip()
    return para or None


def split_verse(text: str) -> list[str]:
    """Cut a long verse paragraph (e.g. a whole Georgic) at sentence ends so it can be sampled and split."""
    pieces, cur, size = [], [], 0
    for line in text.split("\n"):
        cur.append(line)
        size += len(line) + 1
        if size >= VERSE_CHUNK and re.search(r"[.!?][’”\"')]*$", line):
            pieces.append("\n".join(cur))
            cur, size = [], 0
    if cur:
        pieces.append("\n".join(cur))
    return pieces


def clean_book(raw: str, book: Book) -> list[Section]:
    text = strip_gutenberg(raw)
    for old, new in book.replace:
        text = text.replace(old, new)
    lines = text.split("\n")
    lines = drop_blocks(drop_after_heading(select_ranges(lines, book), book), book)
    section_rx = re.compile(book.section) if book.section else None

    sections: list[Section] = [[]]
    for raw_para in split_paragraphs(lines):
        text = clean_paragraph(raw_para, book)
        if text is None:
            continue
        if "\n" in text and len(text) > 2 * VERSE_CHUNK:
            *pieces, text = split_verse(text)
            sections[-1] += [Para(p) for p in pieces]
        is_head = bool(section_rx.fullmatch(text)) if section_rx else generic_heading(text)
        if is_head and any(not p.heading for p in sections[-1]):
            sections.append([])
        sections[-1].append(Para(text, is_head))
    sections = [s for s in sections if any(not p.heading for p in s)]
    return subdivide(sections)


def section_len(sec: Section) -> int:
    return sum(len(p.text) for p in sec) + len(PARA_SEP) * max(len(sec) - 1, 0)


def book_len(sections: list[Section]) -> int:
    return sum(section_len(s) for s in sections) + len(PARA_SEP) * max(len(sections) - 1, 0)


def subdivide(sections: list[Section]) -> list[Section]:
    limit = max(int(book_len(sections) * MAX_SECTION_SHARE), 2000)
    out: list[Section] = []
    for sec in sections:
        if section_len(sec) <= limit:
            out.append(sec)
            continue
        chunk: Section = []
        size = 0
        for p in sec:
            if chunk and size + len(p.text) > limit and any(not q.heading for q in chunk):
                out.append(chunk)
                chunk, size = [], 0
            chunk.append(p)
            size += len(p.text) + len(PARA_SEP)
        if chunk:
            out.append(chunk)
    return out


# ----------------------------------------------------------------- seasoning
def final_total(sizes: dict[int, int], seasoning_ids: set[int], dreambank_share: float = DREAMBANK_SHARE,
                dreambank_chars: int = 0) -> int:
    """Solve for the final corpus size T, where each seasoning book is capped at
    4% of T and DreamBank adds 25% of T:  T = fixed + sum(min(s_i, 0.04 T)) + 0.25 T."""
    fixed = sum(n for i, n in sizes.items() if i not in seasoning_ids)
    # dreambank_chars: a fixed amount of DreamBank (--dreambank_reports) instead of a share.
    total = (sum(sizes.values()) + dreambank_chars) / (1 - dreambank_share)
    for _ in range(200):
        cap = SEASONING_CAP * total
        new_total = (fixed + sum(min(sizes[i], cap) for i in seasoning_ids) + dreambank_chars) / (1 - dreambank_share)
        if abs(new_total - total) < 1:
            break
        total = new_total
    return int(total)


def wrap_dream(text: str) -> str:
    return f"<dream>\n{text}\n</dream>"


def sample_dreams(reports: list[dict], budget: int, rng: random.Random) -> list[str]:
    """Randomly pick whole reports (wrapped) until adding another would exceed `budget` chars."""
    order = list(range(len(reports)))
    rng.shuffle(order)
    picked, used = [], 0
    for i in order:
        w = wrap_dream(reports[i]["text"])
        n = len(w) + len(PARA_SEP)
        if used + n > budget:
            if used >= budget - 2000:  # close enough: stop
                break
            continue                   # a shorter report may still fit
        picked.append(w)
        used += n
    if used + 2000 < budget:
        raise ValueError(f"DreamBank has only {used:,} chars of reports; {budget:,} needed")
    return picked


def trim(sections: list[Section], budget: int, rng: random.Random) -> list[Section]:
    """Keep a random subset of whole body paragraphs (headings always kept) within `budget` chars."""
    flat = [(si, pi) for si, s in enumerate(sections) for pi, p in enumerate(s)]
    keep = {(si, pi) for si, pi in flat if sections[si][pi].heading}
    used = sum(len(sections[si][pi].text) + len(PARA_SEP) for si, pi in keep)
    body = [k for k in flat if k not in keep]
    rng.shuffle(body)
    for si, pi in body:
        n = len(sections[si][pi].text) + len(PARA_SEP)
        if used + n <= budget:
            keep.add((si, pi))
            used += n
    out = [[p for pi, p in enumerate(s) if (si, pi) in keep] for si, s in enumerate(sections)]
    return [s for s in out if any(not p.heading for p in s)]


# --------------------------------------------------------------------- split
def split_sections(sections: list[Section], rng: random.Random) -> set[int]:
    """Pick whole sections for val until this book's val share is as close to 10% as possible."""
    target = VAL_FRACTION * book_len(sections)
    order = list(range(len(sections)))
    rng.shuffle(order)
    val: set[int] = set()
    size = 0
    for i in order:
        n = section_len(sections[i])
        if abs(size + n - target) < abs(size - target) or not val:
            val.add(i)
            size += n
    return val


def join_tagged(sections: list[Section], tag: str | None) -> str:
    """Like join(), but with every ~PASSAGE_CHARS run of paragraphs wrapped in <tag>...</tag>.

    Passages never cross a section boundary, and a heading always stays with
    the paragraph after it.
    """
    if tag is None:
        return join(sections)
    passages: list[str] = []
    for sec in sections:
        cur: list[Para] = []
        size = 0
        for p in sec:
            # Close the passage once it is full, unless it holds only headings so far.
            if size + len(p.text) > PASSAGE_CHARS and any(not q.heading for q in cur):
                passages.append(f"<{tag}>\n" + PARA_SEP.join(q.text for q in cur) + f"\n</{tag}>")
                cur, size = [], 0
            cur.append(p)
            size += len(p.text) + len(PARA_SEP)
        if cur:
            passages.append(f"<{tag}>\n" + PARA_SEP.join(q.text for q in cur) + f"\n</{tag}>")
    return PARA_SEP.join(passages)


def join(sections: list[Section]) -> str:
    return PARA_SEP.join(PARA_SEP.join(p.text for p in s) for s in sections)


# ---------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--refresh", action="store_true", help="re-download cached texts")
    parser.add_argument("--dreambank_share", type=float, default=DREAMBANK_SHARE,
                        help="DreamBank's share of the final corpus (run 2: 0.25, run 3: 0.12)")
    parser.add_argument("--dreambank_reports", type=int, default=0,
                        help="use exactly this many DreamBank reports instead of a share (run 3: 2529, the run 2 count)")
    parser.add_argument("--tags", action="store_true",
                        help="wrap book passages in <myth>/<tale>/<saga> source tags (run 3)")
    args = parser.parse_args()

    cache = args.data_dir / "raw" / "gutenberg"
    cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    books: dict[int, list[Section]] = {}
    for book in tqdm(BOOKS, desc="clean"):
        books[book.gutenberg_id] = clean_book(load_raw(book, cache, session, args.refresh), book)

    reports = load_reports(args.data_dir, args.refresh)

    rng = random.Random(args.seed)
    raw_sizes = {i: book_len(s) for i, s in books.items()}
    seasoning_ids = {b.gutenberg_id for b in BOOKS if b.tier == SEASONING}
    # DreamBank either fills a share of the corpus, or (--dreambank_reports N) is a
    # fixed number of whole reports and its share falls out of the book total.
    dream_rng = random.Random(f"{args.seed}-{DREAMBANK}")
    if args.dreambank_reports:
        order = list(range(len(reports)))
        dream_rng.shuffle(order)
        dreams = [wrap_dream(reports[i]["text"]) for i in order[: args.dreambank_reports]]
        dream_chars = sum(len(d) + len(PARA_SEP) for d in dreams)
        target_total = final_total(raw_sizes, seasoning_ids, 0.0, dream_chars)
    else:
        target_total = final_total(raw_sizes, seasoning_ids, args.dreambank_share)
    cap = int(SEASONING_CAP * target_total)
    for i in sorted(seasoning_ids):
        if raw_sizes[i] > cap:
            books[i] = trim(books[i], cap, rng)

    # DreamBank gets its own RNG so its sample doesn't shift when the book list changes.
    if not args.dreambank_reports:
        dreams = sample_dreams(reports, int(args.dreambank_share * target_total), dream_rng)
    dream_val = set(dream_rng.sample(range(len(dreams)), round(VAL_FRACTION * len(dreams))))

    full, train, val = [], [], []
    val_by_tier: dict[str, list[str]] = {}  # the same val text, grouped by tier
    rows = []
    for book in BOOKS:
        sections = books[book.gutenberg_id]
        val_idx = split_sections(sections, rng)
        tag = TIER_TAGS[book.tier] if args.tags else None
        full.append(join_tagged(sections, tag))
        train.append(join_tagged([s for k, s in enumerate(sections) if k not in val_idx], tag))
        val.append(join_tagged([s for k, s in enumerate(sections) if k in val_idx], tag))
        val_by_tier.setdefault(book.tier, []).append(val[-1])
        rows.append((book.gutenberg_id, book.tier, f"{book.title} ({book.author})", len(full[-1]),
                     raw_sizes[book.gutenberg_id], len(val_idx), len(sections)))

    full.append(PARA_SEP.join(dreams))
    train.append(PARA_SEP.join(d for k, d in enumerate(dreams) if k not in dream_val))
    val.append(PARA_SEP.join(d for k, d in enumerate(dreams) if k in dream_val))
    val_by_tier[DREAMBANK] = [val[-1]]
    dream_pool = sum(len(wrap_dream(r["text"])) + len(PARA_SEP) for r in reports)
    rows.append(("HF", DREAMBANK, f"DreamBank ({len(dreams):,} of {len(reports):,} reports)",
                 len(full[-1]), dream_pool, len(dream_val), len(dreams)))

    corpus = BOOK_SEP.join(full)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    (args.data_dir / "arcadia.txt").write_text(corpus, encoding="utf-8")
    (args.data_dir / "train.txt").write_text(BOOK_SEP.join(t for t in train if t), encoding="utf-8")
    (args.data_dir / "val.txt").write_text(BOOK_SEP.join(v for v in val if v), encoding="utf-8")
    # Per-tier copies of val.txt (val_core.txt, val_dream.txt, ...) so training
    # can report how well each kind of text is learned.
    for tier, parts in val_by_tier.items():
        (args.data_dir / f"val_{tier}.txt").write_text(BOOK_SEP.join(v for v in parts if v), encoding="utf-8")

    total = len(corpus)
    print()
    print(f"{'id':>6}  {'tier':<9} {'source':<50} {'chars':>10} {'%':>6}  {'val/units':>11}")
    print("-" * 100)
    tiers: dict[str, int] = {}
    for sid, tier, title, n, raw_n, n_val, n_units in rows:
        tiers[tier] = tiers.get(tier, 0) + n
        trimmed = f"  (sampled from {raw_n:,})" if n < raw_n else ""
        print(f"{sid:>6}  {tier:<9} {title[:50]:<50} {n:>10,} {100 * n / total:>5.2f}%"
              f"  {n_val:>5}/{n_units:<5}{trimmed}")
    print("-" * 100)
    for tier, n in tiers.items():
        print(f"{'':>6}  {tier:<9} {'(tier total)':<50} {n:>10,} {100 * n / total:>5.2f}%")
    print()
    train_n = sum(map(len, train))
    val_n = sum(map(len, val))
    chars = sorted(set(corpus))
    print(f"total characters:  {total:,}")
    print(f"train / val:       {train_n:,} / {val_n:,}  ({100 * val_n / (train_n + val_n):.1f}% val)")
    print(f"unique characters: {len(chars)}")
    print("                   " + "".join(c if c.isprintable() and c != " " else repr(c)[1:-1] for c in chars))
    print(f"wrote {args.data_dir / 'arcadia.txt'}, train.txt, val.txt, val_<tier>.txt")


if __name__ == "__main__":
    main()
