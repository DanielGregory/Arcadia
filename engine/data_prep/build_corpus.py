"""Build the Arcadia training corpus from the reading list in `books.py` plus DreamBank.

Steps:
  1. Download each Gutenberg text (cached in data/raw/gutenberg/) and the
     DreamBank reports (cached in data/raw/dreambank/, see fetch_dreambank.py).
  2. Strip Gutenberg headers/footers, translator prefaces, introductions,
     notes, indexes and footnotes, using the per-book rules in books.py.
  3. Cap every work at 4% of the final corpus by randomly sampling whole
     paragraphs to keep (a work can span several Gutenberg files, e.g. the
     Mahabharata's four volumes). Plays are turned into plain verse or prose:
     speaker names, stage directions and cast lists go.
  4. Randomly sample whole DreamBank reports, each wrapped in <dream>...</dream>,
     until DreamBank is --dreambank_share of the final corpus (run 5: 13.5%).
  5. Write <out_dir>/arcadia.txt, then a 90/10 train/val split (train.txt,
     val.txt, and val_<tag>.txt per source tag): ~10% of each book's sections, and ~10% of the sampled
     dream reports, go to val.
  6. Print a per-source table, the per-tag split, total and unique character
     counts, and the books from the reading list that were skipped (and why).
  7. Set the dream-interpretation books aside in data/interpretation/ (not trained on).

Usage:
    python -m engine.data_prep.build_corpus
    python -m engine.data_prep.build_corpus --refresh --seed 7
    python -m engine.data_prep.build_corpus --tags --dreambank_share 0.135 --out_dir data/run5   # run 5
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

from engine.data_prep.books import BOOKS, INTERPRETATION, SKIPPED, Book
from engine.data_prep.fetch_dreambank import load_reports
from engine.data_prep.fetch_gutenberg import HEADERS, fetch_raw, strip_gutenberg

WORK_CAP = 0.04         # no work may be more than 4% of the corpus
DREAMBANK = "dream"     # DreamBank's tag
DREAMBANK_SHARE = 0.135

# Source tags (--tags, run 3 on): every passage of a book is wrapped in its
# tag (books.py), the way each DreamBank report is wrapped in <dream>...</dream>.
# The tag tells the model which voice it is reading, and at sampling time
# lets us ask for a voice. Passages are runs of whole paragraphs of about
# PASSAGE_CHARS characters (~one 256-token training window), so almost every
# training window contains a tag.
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


# --------------------------------------------------------------------- plays
# A speaker's name on a line of its own: "KENT.", "FIRST WITCH.", "_XANTHIAS_".
SPEAKER_LINE = re.compile(r"_?[A-Z][A-Z’'\-]*(?:[ ,&][A-Z][A-Z’'\-]*)*_?\.?(?:\s*\[[^\]]*\]?)?")
# A speaker's name at the start of a line, in capitals: "VUL. Thy tongue", "DIONYSUS. Aye".
SPEAKER_PREFIX = re.compile(r"^_?[A-Z][A-Z’'\-]+(?: [A-Z][A-Z’'\-]+)*_?\.(?:\s*\([^)]*\)\.?)?\s+")
# A stage direction on its own: "Enter Kent, Gloucester and Edmund.", "Exeunt.", "[Thunder.]"
STAGE_LINE = re.compile(r"(?:\[.*|\(.*\)\.?|(?:Enter|Exit|Exeunt|Re-enter|Manet|Flourish|Alarum|Alarums|Sennet"
                        r"|Trumpets?|Thunder|Music|Storm|Noise within|Retreat|Hautboys|Dies|A tucket)\b.*)")
# Cast lists: the heading, and every short line after it up to the first blank line.
CAST_HEADING = re.compile(r"(?:DRAMATIS PERSON[AÆ]E?|Dramatis Person[aæ]e?|PERSONS (?:OF THE DRAMA|REPRESENTED)\.?"
                          r"|CHARACTERS (?:OF|IN) THE PLAY|PERSONS OF THE DIALOGUE.*)\s*")


# Cast-list lines: "THESEUS, King of Athens", or a short Title-Case name ("The Priest of Zeus.").
CAST_CAPS = re.compile(r"(?:A |THE )?[A-Z][A-Z’'\-]+(?: [A-Z][A-Z’'\-]+)*,.*")
CAST_NAME = re.compile(r"(?:The |A |An )?[A-Z][a-z’'\-]+(?: (?:of|the|and|to|in|at)? ?[A-Z][a-z’'\-]+){0,5}\.?")
# The setting, before the first line is spoken: "Scene: Thebes.", "The Scene is the Palace of Atreus".
SETTING = re.compile(r"(?:the )?scene(?::| is | represents | lies ).*", re.S | re.I)


def play_lines(para: str, book: Book) -> str:
    """A play paragraph as plain verse or prose: no speakers, stage directions or cast lists."""
    para = re.sub(r"\[[^\]]*\]", "", para, flags=re.S)        # [_Exit._], [Lies down ...]
    # These editions set stage directions (and some speaker names) in _italics_:
    # a paragraph or line that is italic from end to end is not spoken.
    if re.fullmatch(r"\s*_[^_]+_[.,:;\s]*", para, flags=re.S):
        return ""
    para = "\n".join(l for l in para.split("\n") if not re.fullmatch(r"\s*_[^_]+_[.,:;]?\s*", l))
    lines = para.split("\n")
    if CAST_HEADING.fullmatch(lines[0].strip()) or SETTING.fullmatch(para.replace("_", "").strip()):
        return ""
    stripped = [l.strip() for l in lines if l.strip()]
    names = [l.replace("_", "") for l in stripped]
    if names and ((CAST_CAPS.fullmatch(names[0]) or SPEAKER_LINE.fullmatch(names[0]))
                  and (n_cast := sum(bool(CAST_CAPS.fullmatch(l) or SPEAKER_LINE.fullmatch(l)) for l in names))
                  > len(names) / 2  # long entries wrap onto a second line
                  and (n_cast >= 2 or (len(names) == 1 and CAST_CAPS.fullmatch(names[0])))
                  or (len(stripped) >= 2 and all(CAST_NAME.fullmatch(l) for l in stripped))):
        return ""  # a cast list
    if len(stripped) == 1 and CAST_NAME.fullmatch(stripped[0]) and stripped[0][-1].isalpha():
        return ""  # a speaker's name in mixed case on its own ("A Watchman"); spoken lines end in punctuation
    speakers = re.compile(rf"^(?:{book.speakers})(?:\s*\([^)]*\))?\.\s*") if book.speakers else None
    out = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if SPEAKER_LINE.fullmatch(s) and sum(c.isalpha() for c in s) >= 2:
            continue
        if STAGE_LINE.fullmatch(s.replace("_", "").strip()):
            continue
        s = SPEAKER_PREFIX.sub("", s)
        if speakers:
            s = speakers.sub("", s)
        if s:
            out.append(s)
    return "\n".join(out)


def clean_paragraph(raw: str, book: Book) -> str | None:
    if book.drop_indented and all(l[:1].isspace() for l in raw.split("\n")):
        return None
    para = textwrap.dedent(raw)
    if book.play:
        para = play_lines(para, book)
        if not para:
            return None
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
    para = re.sub(r"([,;:])(?=[^\W\d_])", r"\1 ", para)  # a removed marker can leave "Válmíki,bird"
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
        if is_head and book.play:
            continue  # a play's ACT/SCENE heading: a section boundary, but not text to read
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
def final_total(work_sizes: dict[str, int], dreambank_share: float = DREAMBANK_SHARE,
                dreambank_chars: int = 0) -> int:
    """Solve for the final corpus size T, where every work is capped at 4% of T
    and DreamBank adds `dreambank_share` of T:  T = sum(min(s_w, 0.04 T)) + share * T.
    The cap depends on T and T on the cap, so iterate until it settles."""
    total = (sum(work_sizes.values()) + dreambank_chars) / (1 - dreambank_share)
    for _ in range(500):
        cap = WORK_CAP * total
        new_total = (sum(min(n, cap) for n in work_sizes.values()) + dreambank_chars) / (1 - dreambank_share)
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
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="where data/raw/ (the download cache) lives")
    parser.add_argument("--out_dir", type=Path, help="where to write the corpus (default: --data-dir; run 5: data/run5)")
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--refresh", action="store_true", help="re-download cached texts")
    parser.add_argument("--dreambank_share", type=float, default=DREAMBANK_SHARE,
                        help="DreamBank's share of the final corpus (run 2: 0.25, run 3: 0.12, run 5: 0.135)")
    parser.add_argument("--tags", action="store_true",
                        help="wrap every passage in its source tag: <myth>, <tale>, <poem>, <wisdom>, <chronicle>")
    args = parser.parse_args()
    out_dir = args.out_dir or args.data_dir

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
    works: dict[str, list[Book]] = {}
    for book in BOOKS:
        works.setdefault(book.work_name, []).append(book)
    work_sizes = {w: sum(raw_sizes[b.gutenberg_id] for b in bs) for w, bs in works.items()}

    # 4% cap per work. A work over the cap is sampled down; its volumes keep
    # their share of the work (a 4-volume work gives each volume ~1% if equal).
    target_total = final_total(work_sizes, args.dreambank_share)
    cap = int(WORK_CAP * target_total)
    for w, bs in works.items():
        if work_sizes[w] > cap:
            for b in bs:
                share = raw_sizes[b.gutenberg_id] / work_sizes[w]
                books[b.gutenberg_id] = trim(books[b.gutenberg_id], int(cap * share), rng)

    # DreamBank gets its own RNG so its sample doesn't shift when the book list changes.
    dream_rng = random.Random(f"{args.seed}-dreambank")
    dreams = sample_dreams(reports, int(args.dreambank_share * target_total), dream_rng)
    dream_val = set(dream_rng.sample(range(len(dreams)), round(VAL_FRACTION * len(dreams))))

    full, train, val = [], [], []
    val_by_tag: dict[str, list[str]] = {}  # the same val text, grouped by tag
    rows = []
    for book in BOOKS:
        sections = books[book.gutenberg_id]
        val_idx = split_sections(sections, rng)
        tag = book.tag if args.tags else None
        full.append(join_tagged(sections, tag))
        train.append(join_tagged([s for k, s in enumerate(sections) if k not in val_idx], tag))
        val.append(join_tagged([s for k, s in enumerate(sections) if k in val_idx], tag))
        val_by_tag.setdefault(book.tag, []).append(val[-1])
        rows.append((book.gutenberg_id, book.tag, book.work_name, f"{book.title} ({book.author})", len(full[-1]),
                     raw_sizes[book.gutenberg_id], len(val_idx), len(sections)))

    full.append(PARA_SEP.join(dreams))
    train.append(PARA_SEP.join(d for k, d in enumerate(dreams) if k not in dream_val))
    val.append(PARA_SEP.join(d for k, d in enumerate(dreams) if k in dream_val))
    val_by_tag[DREAMBANK] = [val[-1]]
    dream_pool = sum(len(wrap_dream(r["text"])) + len(PARA_SEP) for r in reports)
    rows.append(("HF", DREAMBANK, "DreamBank", f"DreamBank ({len(dreams):,} of {len(reports):,} reports)",
                 len(full[-1]), dream_pool, len(dream_val), len(dreams)))

    corpus = BOOK_SEP.join(full)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "arcadia.txt").write_text(corpus, encoding="utf-8")
    (out_dir / "train.txt").write_text(BOOK_SEP.join(t for t in train if t), encoding="utf-8")
    (out_dir / "val.txt").write_text(BOOK_SEP.join(v for v in val if v), encoding="utf-8")
    # Per-tag copies of val.txt (val_myth.txt, val_dream.txt, ...) so training
    # can report how well each kind of text is learned.
    for tag, parts in val_by_tag.items():
        (out_dir / f"val_{tag}.txt").write_text(BOOK_SEP.join(v for v in parts if v), encoding="utf-8")

    # 7. The dream-interpretation books, cleaned the same way but set aside.
    interp = args.data_dir / "interpretation"
    interp.mkdir(parents=True, exist_ok=True)
    for book in INTERPRETATION:
        text = join(clean_book(load_raw(book, cache, session, args.refresh), book))
        (interp / f"{book.gutenberg_id}.txt").write_text(text, encoding="utf-8")
        print(f"set aside (not trained on): {interp / f'{book.gutenberg_id}.txt'}  {book.title} ({len(text):,} chars)")

    total = len(corpus)
    print()
    print(f"{'id':>6}  {'tag':<9} {'source':<58} {'chars':>10} {'%':>6}  {'val/units':>11}")
    print("-" * 110)
    by_tag: dict[str, int] = {}
    by_work: dict[str, int] = {}
    for sid, tag, work, title, n, raw_n, n_val, n_units in rows:
        by_tag[tag] = by_tag.get(tag, 0) + n
        by_work[work] = by_work.get(work, 0) + n
        trimmed = f"  (sampled from {raw_n:,})" if n < raw_n * 0.98 else ""
        print(f"{sid:>6}  {tag:<9} {title[:58]:<58} {n:>10,} {100 * n / total:>5.2f}%"
              f"  {n_val:>5}/{n_units:<5}{trimmed}")
    print("-" * 110)
    multi = [w for w in works if len(works[w]) > 1]
    for w in multi:
        print(f"{'':>6}  {'work':<9} {w[:58]:<58} {by_work[w]:>10,} {100 * by_work[w] / total:>5.2f}%")
    print("-" * 110)
    for tag, n in sorted(by_tag.items(), key=lambda kv: -kv[1]):
        print(f"{'':>6}  {tag:<9} {'(tag total)':<58} {n:>10,} {100 * n / total:>5.2f}%")
    print()
    train_n = sum(map(len, train))
    val_n = sum(map(len, val))
    chars = sorted(set(corpus))
    print(f"total characters:  {total:,}")
    print(f"train / val:       {train_n:,} / {val_n:,}  ({100 * val_n / (train_n + val_n):.1f}% val)")
    print(f"largest work:      {max(by_work, key=by_work.get)} ({100 * max(by_work.values()) / total:.2f}%)")
    print(f"unique characters: {len(chars)}")
    print("                   " + "".join(c if c.isprintable() and c != " " else repr(c)[1:-1] for c in chars))
    print()
    print("Skipped from the reading list:")
    for title, reason in SKIPPED:
        print(f"  - {title}: {reason}")
    print(f"wrote {out_dir / 'arcadia.txt'}, train.txt, val.txt, val_<tag>.txt")


if __name__ == "__main__":
    main()
