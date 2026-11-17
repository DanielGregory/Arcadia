"""The Arcadia reading list: which Gutenberg texts make up the corpus, and how to clean each one.

Each Gutenberg text is one `Book`. Cleaning rules are per book because every
edition hides its apparatus (prefaces, notes, indexes) in a different way.

Regex fields are matched with `re.fullmatch` against a single *stripped* line,
unless noted otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CORE = "core"
DREAM = "dream"
SEASONING = "seasoning"


@dataclass(frozen=True)
class Range:
    """Keep lines from the `nth` line matching `start` up to (not including) the next line matching `end`."""

    start: str
    end: str | None = None
    nth: int = 1


@dataclass(frozen=True)
class Book:
    gutenberg_id: int
    title: str
    author: str
    translator: str | None
    tier: str
    ranges: tuple[Range, ...]
    # Blocks to delete: from a line matching the first regex up to (not including)
    # the next line matching the second.
    drop_blocks: tuple[tuple[str, str], ...] = ()
    # (heading, separator, max_lines): after a heading line, drop everything up to and
    # including the separator line if one follows within max_lines (editorial arguments).
    drop_after_heading: tuple[str, str, int] | None = None
    # Extra inline patterns to delete (re.sub, anywhere in a paragraph), e.g. footnote markers.
    inline_refs: tuple[str, ...] = ()
    # Delete whole paragraphs that match (re.match against the dedented paragraph).
    drop_paragraphs: tuple[str, ...] = ()
    # Delete paragraphs whose every line is indented (used where notes and
    # editorial summaries are set indented and the text itself is not).
    drop_indented: bool = False
    # Literal string replacements applied to the raw text (encoding repairs).
    replace: tuple[tuple[str, str], ...] = ()
    # Keep every line break (verse translations). Otherwise prose paragraphs are unwrapped.
    verse: bool = False
    # Section heading lines (fullmatch on stripped line). If None, a generic
    # "short all-caps line on its own" rule is used.
    section: str | None = None
    notes: str = field(default="", compare=False)


ROMAN = r"[IVXLC]+"

BOOKS: tuple[Book, ...] = (
    # ---------------------------------------------------------------- CORE
    Book(
        1727, "The Odyssey", "Homer", "Samuel Butler", CORE,
        ranges=(Range(r"BOOK I", r"FOOTNOTES:"),),
        # Butler's footnote numbers are glued to the preceding word: "East.1 He had".
        # Butler's footnote numbers sit after a word, mark or space: "East.1 He", "tune.]38", "them. 44 Early".
        # Butler spells out real numbers, so any bare 1-3 digit number is a marker.
        # His [square brackets] mark supplied words; keep the words.
        inline_refs=(r"\s?(?<!\d)\d{1,3}(?!\d)", r"[\[\]]"),
        section=rf"BOOK {ROMAN}",
    ),
    Book(
        21765, "Metamorphoses, Books I–VII", "Ovid", "Henry T. Riley (prose)", CORE,
        ranges=(Range(r"BOOK THE FIRST\.", r"The Hamilton, Locke and Clark"),),
        # Riley follows every fable with an "EXPLANATION." essay; drop them.
        drop_blocks=((r"EXPLANATION\.", rf"(FABLES?\s.*|BOOK THE \w+\.)"),),
        inline_refs=(r"\s*\[[IVXLC]+\.\s*\d+[-–]\d+\]",),
        drop_indented=True,  # argument summaries and footnotes are indented
        section=r"(FABLES?\s.*|BOOK THE \w+\.)",
    ),
    Book(
        26073, "Metamorphoses, Books VIII–XV", "Ovid", "Henry T. Riley (prose)", CORE,
        ranges=(Range(r"BOOK THE EIGHTH\.", r"THE END\."),),
        drop_blocks=((r"EXPLANATION\.", rf"(FABLES?\s.*|BOOK THE \w+\.)"),),
        inline_refs=(r"\s*\[[IVXLC]+\.\s*\d+[-–]\d+\]",),
        drop_indented=True,
        section=r"(FABLES?\s.*|BOOK THE \w+\.)",
    ),
    Book(
        4775, "Theocritus, Bion and Moschus", "Theocritus, Bion, Moschus", "Andrew Lang (prose)", CORE,
        ranges=(Range(r"THEOCRITUS", r"FOOTNOTES"),),
        # Lang's short biographical notes before Bion's poems (numbered I, II, ...)
        # and before Moschus's (headed IDYL I, ...).
        drop_blocks=((r"BION", ROMAN), (r"MOSCHUS", rf"IDYL {ROMAN}")),
        # Lang's italic argument before each idyl ends in a "* * * * *" line.
        drop_after_heading=(rf"IDYL {ROMAN}", r"\*(\s*\*)+", 40),
        # Backstop for arguments without the separator: wholly italic, or a run of
        # italic phrases ("_The poet_, _with two friends_, ..."). A speaker tag
        # like "_Thyrsis_.  Sweet, ..." is kept.
        drop_paragraphs=(r"(?s)_.*_[.\s]*$", r"(?s)_[^_]+_\S*\s+_"),
        inline_refs=(r" \d{1,3}(?=\s|$)",),  # Lang's inline line numbers: "lover, 11 who"
        # "IDYL X THE REAPERS", "I For a rustic Altar." -- but not "I will cast off ..."
        section=rf"(IDYL {ROMAN}|{ROMAN})( [A-Z][^.!?]{{0,60}}\.?)?",
    ),
    Book(
        230, "Eclogues", "Virgil", "J. B. Greenough (verse; uncredited in this edition)", CORE,
        ranges=(Range(r"ECLOGUE I"),),
        verse=True,
        section=rf"ECLOGUE {ROMAN}",
        notes="No public-domain prose translation is on Gutenberg; this is the closest available.",
    ),
    Book(
        232, "Georgics", "Virgil", "James Rhoades (verse)", CORE,
        ranges=(Range(r"GEORGIC I"),),
        verse=True,
        section=rf"GEORGIC {ROMAN}",
        notes="No public-domain prose translation is on Gutenberg; this is the closest available.",
    ),
    Book(
        348, "Works and Days, Theogony, and the Homeric Hymns", "Hesiod / Homer", "Hugh G. Evelyn-White", CORE,
        # Works and Days, the Theogony and the Homeric Hymns. Fragment collections,
        # the Epic Cycle, intros and endnotes are left out. Each heading also
        # appears once in the front-matter contents, hence nth=2.
        ranges=(
            Range(r"HESIOD’S WORKS AND DAYS", r"THE DIVINATION BY BIRDS", nth=2),
            Range(r"THE THEOGONY", r"THE CATALOGUES OF WOMEN AND EOIAE.*"),
            Range(r"THE HOMERIC HYMNS", r"HOMER’S EPIGRAMS.*"),
        ),
        inline_refs=(
            r"\(ll?\.?\s*[\dab\-–, ]+\)\s*",       # line references: "(ll. 1-10)", "(ll 493-501)"
            r"\s?\b\d{4}\b",                       # endnote markers: "asphodel 1301."
        ),
        drop_paragraphs=(r"\(\(LACUNA\)\)\s*$",),
    ),
    Book(
        11339, "Aesop's Fables", "Aesop", "V. S. Vernon Jones", CORE,
        ranges=(Range(r"THE FOX AND THE GRAPES", r"ILLUSTRATIONS", nth=3),),
    ),
    # --------------------------------------------------------------- DREAM
    Book(
        8395, "The Gods of Pegana", "Lord Dunsany", None, DREAM,
        ranges=(Range(r"PREFACE"),),  # Dunsany's own preface is part of the mythos
        # cp1252 text mis-read as Mac Roman: Eimës, Zänës, Segástrion.
        replace=(("Î", "ë"), ("‰", "ä"), ("·", "á")),
    ),
    Book(
        8183, "Time and the Gods", "Lord Dunsany", None, DREAM,
        ranges=(Range(r"PREFACE", r"THE END"),),
    ),
    Book(
        325, "Phantastes", "George MacDonald", None, DREAM,
        ranges=(Range(r"CHAPTER I"),),  # skips Greville MacDonald's 1905 preface
        section=rf"CHAPTER {ROMAN}",
    ),
    Book(
        1640, "Lilith", "George MacDonald", None, DREAM,
        # Skips the Thoreau epigraph; stops before the end-notes on chapter epigraphs.
        ranges=(Range(r"CHAPTER I\. THE LIBRARY", r"\*Chapter \d+:.*"),),
        inline_refs=(r" ?\*+",),
        section=rf"(?i:CHAPTER {ROMAN}\..*)",
    ),
    Book(
        8208, "Poems of Coleridge", "Samuel Taylor Coleridge", None, DREAM,
        ranges=(Range(r"THE RIME OF THE ANCIENT MARINER", r"NOTES", nth=2),),  # skips Symons's intro
        verse=True,
    ),
    Book(
        11, "Alice's Adventures in Wonderland", "Lewis Carroll", None, DREAM,
        ranges=(Range(r"CHAPTER I\.", r"THE END"),),
        # Gutenberg's editor brackets two poem variants; keep Carroll's lines.
        inline_refs=(r"\[later editions continued as follows\s*", r"\]"),
        section=rf"CHAPTER {ROMAN}\.",
    ),
    Book(
        12, "Through the Looking-Glass", "Lewis Carroll", None, DREAM,
        ranges=(Range(r"Child of the pure unclouded brow", r"THE END"),),  # skips the chess problem
        section=rf"CHAPTER {ROMAN}\..*",
    ),
    Book(
        128, "The Arabian Nights Entertainments", "Anonymous", "Andrew Lang (selection)", DREAM,
        ranges=(Range(r"The Arabian Nights", r"End of Project Gutenberg.*", nth=2),),  # skips the contents and Lang's preface
        section=r"(The (Story|Adventures|Seven Voyages|Little Hunchback|Enchanted Horse)\b.*"
                r"|\w+ Voyage|(Seventh and Last) Voyage|Noureddin.*|Aladdin.*)",
    ),
    # ------------------------------------------------- CORE, added for run 3
    Book(
        2199, "The Iliad", "Homer", "Samuel Butler", CORE,
        ranges=(Range(r"BOOK I\.", nth=2),),  # the first is in the contents
        section=rf"BOOK {ROMAN}\.",
    ),
    Book(
        22456, "The Aeneid", "Virgil", "J. W. Mackail (prose)", CORE,
        ranges=(Range(r"BOOK FIRST", r"NOTES"),),  # skips the preface; stops before the Latin textual notes
        inline_refs=(r"\[\d+-\d+\]",),             # Mackail's line references: "[20-53]Troy"
        section=r"BOOK [A-Z]+",
    ),
    Book(
        830, "The Argonautica", "Apollonius of Rhodes", "R. C. Seaton (prose)", CORE,
        ranges=(Range(r"BOOK I", r"ENDNOTES:", nth=2),),  # skips contents, bibliography and introduction
        section=rf"BOOK {ROMAN}",
    ),
    Book(
        1666, "The Golden Ass", "Apuleius", "William Adlington (1566)", CORE,
        ranges=(Range(r"THE FIRST BOOKE", nth=2),),  # skips contents, dedication and Adlington's address
        inline_refs=(r"[\[\]]",),                    # editor's supplied words "[in]": keep the word
        section=r"THE [A-Z-]+ (BOOKE|CHAPTER)",
    ),
    Book(
        6585, "A True Story (True History)", "Lucian", "H. W. and F. G. Fowler", CORE,
        ranges=(Range(r"BOOK I", r"THE TYRANNICIDE"),),  # only the True History from this volume
        section=r"BOOK II?",
        notes="Starts at Book I, after Lucian's own short preface.",
    ),
    Book(
        1572, "Timaeus (the Atlantis story)", "Plato", "Benjamin Jowett", CORE,
        # The dialogue only (Jowett's ~3,900-line introduction is skipped), and only
        # up to where Timaeus begins his cosmology: the Atlantis story is Critias's.
        ranges=(Range(r"TIMAEUS\.", r"TIMAEUS: All men, Socrates, who have any degree of right feeling,"),),
    ),
    Book(
        1571, "Critias", "Plato", "Benjamin Jowett", CORE,
        ranges=(Range(r"CRITIAS\."),),  # the dialogue, without Jowett's introduction
        drop_paragraphs=(r"\* The rest of the Dialogue",),
    ),
    Book(
        1497, "Republic, Book X: the myth of Er", "Plato", "Benjamin Jowett", CORE,
        ranges=(Range(r"Well, I said, I will tell you a tale; not one of the tales which"),),
    ),
    Book(
        8418, "Hippolytus; The Bacchae", "Euripides", "Gilbert Murray (verse)", CORE,
        ranges=(Range(r"DRAMATIS PERSONAE"),),  # skips Murray's introductory note
        verse=True,
        section=r"(DRAMATIS PERSONAE|THE BACCHAE)",
    ),
    Book(
        35451, "Medea", "Euripides", "Gilbert Murray (verse)", CORE,
        ranges=(Range(r"CHARACTERS OF THE PLAY", r"NOTES TO MEDEA"),),
        verse=True,
        section=r"CHARACTERS OF THE PLAY",
    ),
    Book(
        10096, "The Trojan Women", "Euripides", "Gilbert Murray (verse)", CORE,
        ranges=(Range(r"CHARACTERS IN THE PLAY", r"NOTES ON THE TROJAN WOMEN"),),
        verse=True,
        section=r"CHARACTERS IN THE PLAY",
    ),
    Book(
        31, "Oedipus the King; Oedipus at Colonus; Antigone", "Sophocles", "Francis Storr (verse)", CORE,
        ranges=(Range(r"DRAMATIS PERSONAE"),),
        drop_blocks=((r"ARGUMENT", r"DRAMATIS PERSONAE"),),  # Storr's plot summaries before each play
        verse=True,
        section=r"(DRAMATIS PERSONAE|OEDIPUS THE KING|OEDIPUS AT COLONUS|ANTIGONE)",
    ),
    Book(
        8604, "The House of Atreus (Agamemnon, Libation-Bearers, Furies)", "Aeschylus", "E. D. A. Morshead (verse)", CORE,
        ranges=(Range(r"DRAMATIS PERSONAE"),),  # skips the introductory note
        verse=True,
        section=r"(DRAMATIS PERSONAE|THE LIBATION-BEARERS|THE FURIES)",
    ),
    Book(
        55406, "Daphnis and Chloe", "Longus", "Rowland Smith", CORE,
        # Only Longus from this three-novel volume; a pastoral romance set among
        # the shepherds of Lesbos, the closest thing to Arcadia in the corpus.
        ranges=(Range(r"THE LOVES OF DAPHNIS AND CHLOE\.", r"THE END\."),),
        # Each of the four books ends with its footnotes ("[Footnote 1: ..." onwards,
        # some spanning several paragraphs): cut each block up to the next book.
        drop_blocks=((r"\[Footnote 1:.*", rf"BOOK {ROMAN}\."),),
        section=rf"(THE LOVES OF DAPHNIS AND CHLOE\.|BOOK {ROMAN}\.)",
    ),
    # ------------------------------------------------ DREAM, added for run 3
    Book(
        8129, "A Dreamer's Tales", "Lord Dunsany", None, DREAM,
        ranges=(Range(r"POLTARNEES, BEHOLDER OF OCEAN", r"FINIS"),),
    ),
    Book(
        7477, "The Book of Wonder", "Lord Dunsany", None, DREAM,
        ranges=(Range(r"THE BRIDE OF THE MAN-HORSE"),),  # keeps Dunsany's own epilogue
    ),
    Book(
        13821, "Tales of Wonder", "Lord Dunsany", None, DREAM,
        ranges=(Range(r"A Tale of London", r"THE END", nth=2),),  # skips the 1916 war preface
    ),
    Book(
        10806, "The Sword of Welleran and Other Stories", "Lord Dunsany", None, DREAM,
        ranges=(Range(r"The Sword of Welleran"),),
    ),
    Book(
        7838, "Fifty-One Tales", "Lord Dunsany", None, DREAM,
        ranges=(Range(r"THE ASSIGNATION"),),
    ),
    Book(
        3055, "The Wood Beyond the World", "William Morris", None, DREAM,
        ranges=(Range(r"CHAPTER I: OF GOLDEN WALTER AND HIS FATHER"),),
        section=r"CHAPTER [IVXL]+:.*",
    ),
    Book(
        67090, "The Worm Ouroboros", "E. R. Eddison", None, DREAM,
        ranges=(Range(r"THE INDUCTION", r"ARGUMENT: WITH DATES", nth=2),),  # skips contents; stops before the appendix
        section=r"(THE INDUCTION|[IVXL]+: .*)",
    ),
    # ----------------------------------------------------------- SEASONING
    Book(
        84, "Frankenstein", "Mary Shelley", None, SEASONING,
        ranges=(Range(r"Letter 1", nth=2),),
        section=r"(Letter|Chapter) \d+",
    ),
    Book(
        205, "Walden", "Henry David Thoreau", None, SEASONING,
        # Gutenberg bundles Civil Disobedience after Walden; stop before it.
        ranges=(Range(r"WALDEN", r"THE END", nth=3),),
        section=r"(Economy|Where I Lived, and What I Lived For|Reading|Sounds|Solitude|Visitors"
                r"|The Bean-Field|The Village|The Ponds|Baker Farm|Higher Laws|Brute Neighbors"
                r"|House-Warming|Former Inhabitants; and Winter Visitors|Winter Animals"
                r"|The Pond in Winter|Spring|Conclusion)",
    ),
    Book(
        2591, "Grimms' Fairy Tales", "Jacob and Wilhelm Grimm", "Edgar Taylor and Marian Edwardes", SEASONING,
        ranges=(Range(r"THE GOLDEN BIRD", r"\*{5}", nth=2),),  # stops before the editor's afterword
    ),
    Book(
        2148, "Tales (Works of Poe, Raven Edition, Vol. II)", "Edgar Allan Poe", None, SEASONING,
        ranges=(Range(r"THE PURLOINED LETTER", r"NOTES TO THE SECOND VOLUME", nth=2),),
        inline_refs=(r" ?\(\*\d+\)",),  # endnote markers: "(*1)"
    ),
    Book(
        597, "The Story of Burnt Njal", "Anonymous", "George Webbe Dasent", SEASONING,
        ranges=(Range(r"1\. OF FIDDLE MORD"),),
        drop_blocks=((r"ENDNOTES:", r"\d+\. .*"),),
        inline_refs=(r" ?\(\d+\)",),
        section=r"\d+\. .*",
    ),
)
