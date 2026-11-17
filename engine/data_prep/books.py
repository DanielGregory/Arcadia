"""The Arcadia reading list: which Gutenberg texts make up the corpus, and how to clean each one.

Each Gutenberg text is one `Book`. Cleaning rules are per book because every
edition hides its apparatus (prefaces, notes, indexes) in a different way.

Regex fields are matched with `re.fullmatch` against a single *stripped* line,
unless noted otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Source tags (run 5). Each book's passages are wrapped in its tag, e.g.
# <myth>...</myth>, so the model learns which voice it is reading and we can
# ask for a voice when sampling. DreamBank reports are <dream>.
MYTH = "myth"            # mythology, epic, scripture
TALE = "tale"            # dreams and strange fiction, fairy tales, folklore
POEM = "poem"            # plays and poetry
WISDOM = "wisdom"        # philosophy
CHRONICLE = "chronicle"  # history
TAGS = (MYTH, TALE, POEM, WISDOM, CHRONICLE)


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
    tag: str
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
    # Plays: read as verse or prose, not as a script. Speaker names, stage
    # directions and cast lists are removed (see build_corpus.play_lines).
    play: bool = False
    # Extra speaker-name prefixes to strip at the start of a line, for editions
    # that write them in mixed case ("Strepsiades (sitting up). Ah me!").
    speakers: str | None = None
    # Several Gutenberg files that are one work (the Mahabharata's 4 volumes)
    # share a `work` name; the 4% cap applies to the work as a whole.
    work: str | None = None
    notes: str = field(default="", compare=False)

    @property
    def work_name(self) -> str:
        return self.work or self.title


ROMAN = r"[IVXLC]+"

BOOKS: tuple[Book, ...] = (
    Book(
        1727, "The Odyssey", "Homer", "Samuel Butler", MYTH,
        ranges=(Range(r"BOOK I", r"FOOTNOTES:"),),
        # Butler's footnote numbers are glued to the preceding word: "East.1 He had".
        # Butler's footnote numbers sit after a word, mark or space: "East.1 He", "tune.]38", "them. 44 Early".
        # Butler spells out real numbers, so any bare 1-3 digit number is a marker.
        # His [square brackets] mark supplied words; keep the words.
        inline_refs=(r"\s?(?<!\d)\d{1,3}(?!\d)", r"[\[\]]"),
        section=rf"BOOK {ROMAN}",
    ),
    Book(
        21765, "Metamorphoses, Books I–VII", "Ovid", "Henry T. Riley (prose)", MYTH,
        ranges=(Range(r"BOOK THE FIRST\.", r"The Hamilton, Locke and Clark"),),
        # Riley follows every fable with an "EXPLANATION." essay; drop them.
        drop_blocks=((r"EXPLANATION\.", rf"(FABLES?\s.*|BOOK THE \w+\.)"),),
        inline_refs=(r"\s*\[[IVXLC]+\.\s*\d+[-–]\d+\]",),
        drop_indented=True,  # argument summaries and footnotes are indented
        section=r"(FABLES?\s.*|BOOK THE \w+\.)",
    ),
    Book(
        26073, "Metamorphoses, Books VIII–XV", "Ovid", "Henry T. Riley (prose)", MYTH,
        ranges=(Range(r"BOOK THE EIGHTH\.", r"THE END\."),),
        drop_blocks=((r"EXPLANATION\.", rf"(FABLES?\s.*|BOOK THE \w+\.)"),),
        inline_refs=(r"\s*\[[IVXLC]+\.\s*\d+[-–]\d+\]",),
        drop_indented=True,
        section=r"(FABLES?\s.*|BOOK THE \w+\.)",
    ),
    Book(
        4775, "Theocritus, Bion and Moschus", "Theocritus, Bion, Moschus", "Andrew Lang (prose)", POEM,
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
        230, "Eclogues", "Virgil", "J. B. Greenough (verse; uncredited in this edition)", POEM,
        ranges=(Range(r"ECLOGUE I"),),
        verse=True,
        section=rf"ECLOGUE {ROMAN}",
        notes="No public-domain prose translation is on Gutenberg; this is the closest available.",
    ),
    Book(
        232, "Georgics", "Virgil", "James Rhoades (verse)", POEM,
        ranges=(Range(r"GEORGIC I"),),
        verse=True,
        section=rf"GEORGIC {ROMAN}",
        notes="No public-domain prose translation is on Gutenberg; this is the closest available.",
    ),
    Book(
        348, "Works and Days, Theogony, and the Homeric Hymns", "Hesiod / Homer", "Hugh G. Evelyn-White", MYTH,
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
        11339, "Aesop's Fables", "Aesop", "V. S. Vernon Jones", TALE,
        ranges=(Range(r"THE FOX AND THE GRAPES", r"ILLUSTRATIONS", nth=3),),
    ),
    # ------------------------------------------------- (run 1-2 reading list)
    Book(
        8395, "The Gods of Pegana", "Lord Dunsany", None, TALE,
        ranges=(Range(r"PREFACE"),),  # Dunsany's own preface is part of the mythos
        # cp1252 text mis-read as Mac Roman: Eimës, Zänës, Segástrion.
        replace=(("Î", "ë"), ("‰", "ä"), ("·", "á")),
    ),
    Book(
        8183, "Time and the Gods", "Lord Dunsany", None, TALE,
        ranges=(Range(r"PREFACE", r"THE END"),),
    ),
    Book(
        325, "Phantastes", "George MacDonald", None, TALE,
        ranges=(Range(r"CHAPTER I"),),  # skips Greville MacDonald's 1905 preface
        section=rf"CHAPTER {ROMAN}",
    ),
    Book(
        1640, "Lilith", "George MacDonald", None, TALE,
        # Skips the Thoreau epigraph; stops before the end-notes on chapter epigraphs.
        ranges=(Range(r"CHAPTER I\. THE LIBRARY", r"\*Chapter \d+:.*"),),
        inline_refs=(r" ?\*+",),
        section=rf"(?i:CHAPTER {ROMAN}\..*)",
    ),
    Book(
        8208, "Poems of Coleridge", "Samuel Taylor Coleridge", None, POEM,
        ranges=(Range(r"THE RIME OF THE ANCIENT MARINER", r"NOTES", nth=2),),  # skips Symons's intro
        verse=True,
    ),
    Book(
        11, "Alice's Adventures in Wonderland", "Lewis Carroll", None, TALE,
        ranges=(Range(r"CHAPTER I\.", r"THE END"),),
        # Gutenberg's editor brackets two poem variants; keep Carroll's lines.
        inline_refs=(r"\[later editions continued as follows\s*", r"\]"),
        section=rf"CHAPTER {ROMAN}\.",
    ),
    Book(
        12, "Through the Looking-Glass", "Lewis Carroll", None, TALE,
        ranges=(Range(r"Child of the pure unclouded brow", r"THE END"),),  # skips the chess problem
        section=rf"CHAPTER {ROMAN}\..*",
    ),
    Book(
        128, "The Arabian Nights Entertainments", "Anonymous", "Andrew Lang (selection)", TALE,
        ranges=(Range(r"The Arabian Nights", r"End of Project Gutenberg.*", nth=2),),  # skips the contents and Lang's preface
        section=r"(The (Story|Adventures|Seven Voyages|Little Hunchback|Enchanted Horse)\b.*"
                r"|\w+ Voyage|(Seventh and Last) Voyage|Noureddin.*|Aladdin.*)",
    ),
    # ---------------------------------------------------------- added for run 3
    Book(
        2199, "The Iliad", "Homer", "Samuel Butler", MYTH,
        ranges=(Range(r"BOOK I\.", nth=2),),  # the first is in the contents
        section=rf"BOOK {ROMAN}\.",
    ),
    Book(
        22456, "The Aeneid", "Virgil", "J. W. Mackail (prose)", MYTH,
        ranges=(Range(r"BOOK FIRST", r"NOTES"),),  # skips the preface; stops before the Latin textual notes
        inline_refs=(r"\[\d+-\d+\]",),             # Mackail's line references: "[20-53]Troy"
        section=r"BOOK [A-Z]+",
    ),
    Book(
        830, "The Argonautica", "Apollonius of Rhodes", "R. C. Seaton (prose)", MYTH,
        ranges=(Range(r"BOOK I", r"ENDNOTES:", nth=2),),  # skips contents, bibliography and introduction
        section=rf"BOOK {ROMAN}",
    ),
    Book(
        1666, "The Golden Ass", "Apuleius", "William Adlington (1566)", TALE,
        ranges=(Range(r"THE FIRST BOOKE", nth=2),),  # skips contents, dedication and Adlington's address
        inline_refs=(r"[\[\]]",),                    # editor's supplied words "[in]": keep the word
        section=r"THE [A-Z-]+ (BOOKE|CHAPTER)",
    ),
    Book(
        6585, "A True Story (True History)", "Lucian", "H. W. and F. G. Fowler", TALE,
        ranges=(Range(r"BOOK I", r"THE TYRANNICIDE"),),  # only the True History from this volume
        section=r"BOOK II?",
        notes="Starts at Book I, after Lucian's own short preface.",
    ),
    Book(
        1572, "Timaeus (the Atlantis story)", "Plato", "Benjamin Jowett", WISDOM,
        # The dialogue only (Jowett's ~3,900-line introduction is skipped), and only
        # up to where Timaeus begins his cosmology: the Atlantis story is Critias's.
        ranges=(Range(r"TIMAEUS\.", r"TIMAEUS: All men, Socrates, who have any degree of right feeling,"),),
    ),
    Book(
        1571, "Critias", "Plato", "Benjamin Jowett", WISDOM,
        ranges=(Range(r"CRITIAS\."),),  # the dialogue, without Jowett's introduction
        drop_paragraphs=(r"\* The rest of the Dialogue",),
    ),
    Book(
        1497, "The Republic", "Plato", "Benjamin Jowett", WISDOM,
        # The whole dialogue now (run 5); Jowett's long introduction and analysis is skipped.
        ranges=(Range(r"I went down yesterday to the Piraeus with Glaucon the son of Ariston,"),),
        section=r"BOOK [IVX]+\.?",
    ),
    Book(
        8418, "Hippolytus; The Bacchae", "Euripides", "Gilbert Murray (verse)", POEM,
        ranges=(Range(r"DRAMATIS PERSONAE"),),  # skips Murray's introductory note
        verse=True,
        play=True,
        section=r"(DRAMATIS PERSONAE|THE BACCHAE)",
    ),
    Book(
        35451, "Medea", "Euripides", "Gilbert Murray (verse)", POEM,
        ranges=(Range(r"CHARACTERS OF THE PLAY", r"NOTES TO MEDEA"),),
        drop_paragraphs=(r"CHORUS of Corinthian Women",),
        verse=True,
        play=True,
        section=r"CHARACTERS OF THE PLAY",
    ),
    Book(
        10096, "The Trojan Women", "Euripides", "Gilbert Murray (verse)", POEM,
        ranges=(Range(r"_The scene represents a battlefield.*", r"NOTES ON THE TROJAN WOMEN"),),
        drop_paragraphs=(r"The Troädes was first acted", r"(?:The )?[Ss]cene"),
        verse=True,
        play=True,
        section=r"CHARACTERS IN THE PLAY",
    ),
    Book(
        31, "Oedipus the King; Oedipus at Colonus; Antigone", "Sophocles", "Francis Storr (verse)", POEM,
        ranges=(Range(r"DRAMATIS PERSONAE"),),
        drop_blocks=((r"ARGUMENT", r"DRAMATIS PERSONAE"),),  # Storr's plot summaries before each play
        verse=True,
        play=True,
        section=r"(DRAMATIS PERSONAE|OEDIPUS THE KING|OEDIPUS AT COLONUS|ANTIGONE)",
    ),
    Book(
        8604, "The House of Atreus (Agamemnon, Libation-Bearers, Furies)", "Aeschylus", "E. D. A. Morshead (verse)", POEM,
        ranges=(Range(r"DRAMATIS PERSONAE"),),  # skips the introductory note
        verse=True,
        play=True,
        section=r"(DRAMATIS PERSONAE|THE LIBATION-BEARERS|THE FURIES)",
    ),
    Book(
        55406, "Daphnis and Chloe", "Longus", "Rowland Smith", TALE,
        # Only Longus from this three-novel volume; a pastoral romance set among
        # the shepherds of Lesbos, the closest thing to Arcadia in the corpus.
        ranges=(Range(r"THE LOVES OF DAPHNIS AND CHLOE\.", r"THE END\."),),
        # Each of the four books ends with its footnotes ("[Footnote 1: ..." onwards,
        # some spanning several paragraphs): cut each block up to the next book.
        drop_blocks=((r"\[Footnote 1:.*", rf"BOOK {ROMAN}\."),),
        section=rf"(THE LOVES OF DAPHNIS AND CHLOE\.|BOOK {ROMAN}\.)",
    ),
    Book(
        8129, "A Dreamer's Tales", "Lord Dunsany", None, TALE,
        ranges=(Range(r"POLTARNEES, BEHOLDER OF OCEAN", r"FINIS"),),
    ),
    Book(
        7477, "The Book of Wonder", "Lord Dunsany", None, TALE,
        ranges=(Range(r"THE BRIDE OF THE MAN-HORSE"),),  # keeps Dunsany's own epilogue
    ),
    Book(
        13821, "Tales of Wonder", "Lord Dunsany", None, TALE,
        ranges=(Range(r"A Tale of London", r"THE END", nth=2),),  # skips the 1916 war preface
    ),
    Book(
        10806, "The Sword of Welleran and Other Stories", "Lord Dunsany", None, TALE,
        ranges=(Range(r"The Sword of Welleran"),),
    ),
    Book(
        7838, "Fifty-One Tales", "Lord Dunsany", None, TALE,
        ranges=(Range(r"THE ASSIGNATION"),),
    ),
    Book(
        3055, "The Wood Beyond the World", "William Morris", None, TALE,
        ranges=(Range(r"CHAPTER I: OF GOLDEN WALTER AND HIS FATHER"),),
        section=r"CHAPTER [IVXL]+:.*",
    ),
    Book(
        67090, "The Worm Ouroboros", "E. R. Eddison", None, TALE,
        ranges=(Range(r"THE INDUCTION", r"ARGUMENT: WITH DATES", nth=2),),  # skips contents; stops before the appendix
        section=r"(THE INDUCTION|[IVXL]+: .*)",
    ),
    Book(
        84, "Frankenstein", "Mary Shelley", None, TALE,
        ranges=(Range(r"Letter 1", nth=2),),
        section=r"(Letter|Chapter) \d+",
    ),
    Book(
        205, "Walden", "Henry David Thoreau", None, WISDOM,
        # Gutenberg bundles Civil Disobedience after Walden; stop before it.
        ranges=(Range(r"WALDEN", r"THE END", nth=3),),
        section=r"(Economy|Where I Lived, and What I Lived For|Reading|Sounds|Solitude|Visitors"
                r"|The Bean-Field|The Village|The Ponds|Baker Farm|Higher Laws|Brute Neighbors"
                r"|House-Warming|Former Inhabitants; and Winter Visitors|Winter Animals"
                r"|The Pond in Winter|Spring|Conclusion)",
    ),
    Book(
        2591, "Grimms' Fairy Tales", "Jacob and Wilhelm Grimm", "Edgar Taylor and Marian Edwardes", TALE,
        ranges=(Range(r"THE GOLDEN BIRD", r"\*{5}", nth=2),),  # stops before the editor's afterword
    ),
    Book(
        2148, "Tales (Works of Poe, Raven Edition, Vol. II)", "Edgar Allan Poe", None, TALE,
        ranges=(Range(r"THE PURLOINED LETTER", r"NOTES TO THE SECOND VOLUME", nth=2),),
        inline_refs=(r" ?\(\*\d+\)",),  # endnote markers: "(*1)"
    ),
    Book(
        597, "The Story of Burnt Njal", "Anonymous", "George Webbe Dasent", MYTH,
        ranges=(Range(r"1\. OF FIDDLE MORD"),),
        drop_blocks=((r"ENDNOTES:", r"\d+\. .*"),),
        inline_refs=(r" ?\(\d+\)",),
        section=r"\d+\. .*",
    ),

    # ======================================================== added for run 5
    # ------------------------------------------------------------ PLAYS <poem>
    Book(
        27458, "Prometheus Bound", "Aeschylus", "Theodore Alois Buckley (prose)", POEM,
        ranges=(Range(r"PERSONS REPRESENTED\.", r"THE SEVEN AGAINST THEBES\."),),  # this volume's other play is not on the list
        inline_refs=(r"\[\d+\]",),
        play=True,
    ),
    Book(
        2562, "The Clouds", "Aristophanes", "William James Hickie (prose)", POEM,
        ranges=(Range(r"Scene: The interior of a sleeping-apartment:"),),
        play=True,
        speakers=r"(?:Strepsiades|Phidippides|Servant(?: of Strepsiades)?|Disciple|Socrates|Chorus|Cho|Just Cause|Unjust Cause"
                 r"|Pasias|Amynias|Witness|Chaerephon|Creditor|Second Creditor|First Creditor)",
    ),
    Book(
        7998, "The Frogs", "Aristophanes", "B. B. Rogers (verse)", POEM,
        ranges=(Range(r"\*{5}"),),
        verse=True, play=True,
    ),
    Book(1532, "King Lear", "William Shakespeare", None, POEM,
         ranges=(Range(r"SCENE I\. .*"),), verse=True, play=True, section=r"(ACT [IVX]+|SCENE [IVX]+\. .*)"),
    Book(1524, "Hamlet", "William Shakespeare", None, POEM,
         ranges=(Range(r"SCENE I\. .*"),), verse=True, play=True, section=r"(ACT [IVX]+|SCENE [IVX]+\. .*)"),
    Book(1533, "Macbeth", "William Shakespeare", None, POEM,
         ranges=(Range(r"SCENE I\. .*"),), verse=True, play=True, section=r"(ACT [IVX]+|SCENE [IVX]+\. .*)"),
    Book(1540, "The Tempest", "William Shakespeare", None, POEM,
         ranges=(Range(r"SCENE I\. .*"),), verse=True, play=True, section=r"(ACT [IVX]+|SCENE [IVX]+\. .*)"),
    # ----------------------------------------------------------- POETRY <poem>
    Book(
        1934, "Songs of Innocence and of Experience", "William Blake", None, POEM,
        ranges=(Range(r"INTRODUCTION"),),
        drop_paragraphs=(r"\[Picture",),
        verse=True,
    ),
    Book(
        8209, "Poems 1817", "John Keats", None, POEM,
        ranges=(Range(r"I stood tip-toe upon a little hill,", r"Line \d+:.*"),),  # stops at the errata list
        drop_paragraphs=(r"To \* \* \* \*\s*$", r".*Project Gutenberg", r"The original lines appeared"),
        verse=True, work="The Poems of Keats",
    ),
    Book(
        24280, "Endymion", "John Keats", None, POEM,
        ranges=(Range(r"A thing of beauty is a joy for ever:", r"THE END\."),),
        inline_refs=(r"\s+\d{1,4}$",),
        verse=True, work="The Poems of Keats",
    ),
    Book(
        23684, "Poems Published in 1820 (Lamia, Isabella, St. Agnes, Odes, Hyperion)", "John Keats", None, POEM,
        ranges=(Range(r"Upon a time, before the faery broods", r"THE END\."),),
        drop_blocks=((r"FOOTNOTES:", r"[A-Z][A-Z .,'’]{3,}"),),
        inline_refs=(r"\s+\d{1,4}$", r"\s*\[\d+\]", r"(?:\s*\*)+\s*$"),
        verse=True, work="The Poems of Keats",
    ),
    Book(
        12383, "The Prelude", "William Wordsworth", None, POEM,
        ranges=(Range(r"BOOK FIRST", r"APPENDIX\."),),
        drop_blocks=((r"FOOTNOTES ON THE TEXT", r"BOOK [A-Z]+"),  # Knight's notes after every book
                     (r"FOOTNOTES TO BOOK .*", r"BOOK [A-Z]+")),
        drop_paragraphs=(r"\d{4}\.?$", r"(?s).*Ed\.\]\s*$"),  # the editor's notes end "--Ed.]"
        inline_refs=(r"\s*\[[A-Za-z]\]", r"\s*\[\d+\]", r"\s+\d{1,4}$"),
        verse=True,
    ),
    Book(
        76996, "The Raven and Other Poems", "Edgar Allan Poe", None, POEM,
        ranges=(Range(r"THE RAVEN", r"POEMS WRITTEN IN YOUTH"),),
        verse=True,
    ),
    Book(26, "Paradise Lost", "John Milton", None, POEM, ranges=(Range(r"Book I", r"Transcriber’s Notes"),), verse=True, section=r"Book [IVX]+"),
    Book(
        1321, "The Waste Land", "T. S. Eliot", None, POEM,
        ranges=(Range(r"I\. THE BURIAL OF THE DEAD", r"NOTES ON “THE WASTE LAND”", nth=2),),  # #1 is the contents
        inline_refs=(r"\s+\d{1,4}$",),
        drop_paragraphs=(r"Line \d+ ",),  # the editor's variant readings
        verse=True,
    ),
    Book(1322, "Leaves of Grass", "Walt Whitman", None, POEM, ranges=(Range(r"BOOK I\. +INSCRIPTIONS"),), verse=True,
         drop_paragraphs=(r"\d+\s*$",),
         section=r"BOOK [IVXL]+\.?.*"),
    Book(36098, "The Flowers of Evil", "Charles Baudelaire", "Cyril Scott (selection)", POEM,
         ranges=(Range(r"Benediction", nth=2),), verse=True,
         drop_paragraphs=(r"End of (?:the )?Project Gutenberg",)),
    Book(1041, "Shakespeare's Sonnets", "William Shakespeare", None, POEM,
         ranges=(Range(r"From fairest creatures we desire increase,"),), verse=True,
         drop_paragraphs=(r"[IVXLC]+\s*$", r"\d+\s*$")),
    Book(
        1004, "The Divine Comedy", "Dante Alighieri", "Henry Wadsworth Longfellow (verse)", POEM,
        ranges=(Range(r"Inferno: Canto I", r"The Love which moves the sun and the other stars\."),),
        verse=True, section=r"(Inferno|Purgatorio|Paradiso): Canto [IVXL]+",
    ),
    # ------------------------------------------------------ PHILOSOPHY <wisdom>
    Book(1600, "Symposium", "Plato", "Benjamin Jowett", WISDOM,
         ranges=(Range(r"Concerning the things about which you ask to be informed.*"),)),
    Book(1636, "Phaedrus", "Plato", "Benjamin Jowett", WISDOM, ranges=(Range(r"SOCRATES: My dear Phaedrus.*"),),
         inline_refs=(r"^[A-Z]+: ",)),  # the dialogue's speaker names
    Book(1656, "Apology", "Plato", "Benjamin Jowett", WISDOM, ranges=(Range(r"How you, O Athenians.*"),)),
    Book(
        2680, "Meditations", "Marcus Aurelius", "Meric Casaubon", WISDOM,
        ranges=(Range(r"THE FIRST BOOK", r"APPENDIX", nth=1),),
        section=r"THE \w+ BOOK", inline_refs=(r"\[\d+\]", r"^[IVXLC]+\. "),
    ),
    Book(785, "On the Nature of Things", "Lucretius", "William Ellery Leonard (verse)", WISDOM,
         ranges=(Range(r"PROEM", nth=1),), verse=True, section=r"(PROEM|BOOK [IVX]+)"),
    Book(8438, "Nicomachean Ethics", "Aristotle", "D. P. Chase", WISDOM,
         ranges=(Range(r"BOOK I", nth=2),), section=r"BOOK [IVX]+", inline_refs=(r"\s*\[[^\]]*\]",),
         drop_paragraphs=(r"Chapter [IVXL]+\.?$",)),
    Book(216, "Tao Te Ching", "Laozi", "James Legge", WISDOM, ranges=(Range(r"Ch\. 1\. 1\..*"),),
         inline_refs=(r"^Ch\. \d+\. ", r"(?<=\s)\d+\. ", r"^\d+\. ")),
    Book(132, "The Art of War", "Sun Tzu", "Lionel Giles", WISDOM, ranges=(Range(r"Chapter I\. LAYING PLANS"),),
         # Giles prints the old commentators' notes in [brackets] between Sun Tzu's lines; keep Sun Tzu.
         inline_refs=(r"^\d+\.\s+", r"\s*\[[^\]]*\]"), drop_paragraphs=(r"\[",), section=r"Chapter [IVX]+\..*"),
    # --------------------------------------------- MYTHOLOGY AND EPIC <myth>
    Book(
        11000, "The Epic of Gilgamesh (Old Babylonian tablets)", "Anonymous", "Morris Jastrow and Albert T. Clay", MYTH,
        ranges=(Range(r"TRANSLATION\.", r"COMMENTARY ON THE PENNSYLVANIA TABLET\."),
                Range(r"TRANSLATION\.", r"L\.E\.")),
        drop_paragraphs=(r"Col\.? [IVX]+\.?$", r"\(Rest of column", r"\((?:About )?\w+ lines? missing",
                         r"TRANSLATION\.$"),
        inline_refs=(r"\s*\[\d+\]", r"\s*\(\?\)", r"[\[\]]", r"^\s*(?:Col\.? [IVX]+\.)\s*", r"\s+\d{1,3}$",
                     r"^\.{3,}\s*$", r"\.{4,}"),
        verse=True,
    ),
    Book(
        73533, "The Poetic Edda", "Anonymous", "Henry Adams Bellows", MYTH,
        ranges=(Range(r"VOLUSPO", r"PRONOUNCING INDEX OF PROPER NAMES"),),
        # Bellows introduces every poem with a prose note; skip from it to the first stanza.
        drop_blocks=((r"INTRODUCTORY NOTE", r"1\.\s.*"),),
        # Stanzas have a caesura bar ("Hearing I ask | from the holy races"); Bellows's
        # numbered notes do not, so a numbered paragraph without a bar is a note.
        drop_paragraphs=(r"\[", r"\d+\.[^|]*$", r"Prose\. ", r"Lines? \d"),
        inline_refs=(r"^\d+\.\s+", r"\s+\|", r"\s*\[\d+\]"),
        verse=True,
    ),
    Book(5186, "The Kalevala", "Elias Lönnrot (compiler)", "John Martin Crawford (verse)", MYTH,
         ranges=(Range(r"PROEM", r"THE END", nth=2),), verse=True, section=r"(PROEM|RUNE [IVXL]+\.)"),
    Book(24869, "The Ramayana", "Valmiki", "Ralph T. H. Griffith (verse)", MYTH,
         ranges=(Range(r"INVOCATION\.\(1\)", r"APPENDIX\."),), verse=True, inline_refs=(r"\(\d+\)",),
         section=r"(BOOK [IVX]+\.|CANTO [IVXLC]+\.|INVOCATION\.).*"),
    *[Book(gid, f"The Mahabharata, Volume {n}", "Vyasa", "Kisari Mohan Ganguli", MYTH,
           ranges=(Range(r"SECTION I" if n == 1 else r"SECTION I", r"FOOTNOTES"),),
           inline_refs=(r"\s*\[\d+\]", r"\(\d+\)"), section=r"SECTION [IVXLCDM]+", work="The Mahabharata")
      for n, gid in enumerate((15474, 15475, 15476, 15477), 1)],
    Book(56550, "The Popol Vuh", "Anonymous", "Lewis Spence (summary and translation)", MYTH,
         # Spence's 1908 study: his retelling of the Popol Vuh with long quotations; the only
         # public-domain English version on Project Gutenberg.
         ranges=(Range(r"THE POPOL VUH", r"EVIDENCE OF METRICAL COMPOSITION", nth=2),),
         drop_paragraphs=(r"\[The numbers",), inline_refs=(r"\s*\[\d+\]", r"\s*\(\d+\)")),
    # ------------------------------------------------ ANCIENT TEXTS <myth>
    Book(69566, "The Egyptian Book of the Dead", "Anonymous", "P. Le Page Renouf and Edouard Naville", MYTH,
         ranges=(Range(r"CHAPTER I\."),),
         drop_blocks=((r"NOTES\.", r"CHAPTER [IVXLC]+\.?.*"),),  # the translators' notes after every chapter
         inline_refs=(r"\s*\[\d+\]", r"\(\d+\.?\)", r"[\[\]]"), section=r"CHAPTER [IVXLC]+\.?.*"),
    Book(9914, "Enuma Elish (The Babylonian Legends of the Creation)", "Anonymous", "E. A. Wallis Budge", MYTH,
         ranges=(Range(r"THE SEVEN TABLETS OF CREATION\.--TRANSLATION\.", r"LIST OF THE NAMES OF THE STARS.*"),),
         inline_refs=(r"^\d+\.\s*", r"\s*\[\d+\]", r"\(\?\)", r"[\[\]]"), verse=True,
         section=r"(\w+ TABLET\.|EPILOGUE\.)"),
    Book(8018, "The Book of Job", "Anonymous", "King James Version", MYTH, ranges=(Range(r"Book 18 +Job"),),
         inline_refs=(r"^\d+:\d+:\d+\s*",), drop_paragraphs=(r"Book \d+ ",)),
    Book(8021, "Ecclesiastes", "Anonymous", "King James Version", MYTH, ranges=(Range(r"Book 21 +Ecclesiastes"),),
         inline_refs=(r"^\d+:\d+:\d+\s*",), drop_paragraphs=(r"Book \d+ ",)),
    Book(8022, "The Song of Songs", "Anonymous", "King James Version", MYTH, ranges=(Range(r"Book 22 +Song of Solomon"),),
         inline_refs=(r"^\d+:\d+:\d+\s*",), drop_paragraphs=(r"Book \d+ ",)),
    # --------------------------------------------- DREAMS AND STRANGE FICTION <tale>
    Book(174, "The Picture of Dorian Gray", "Oscar Wilde", None, TALE, ranges=(Range(r"CHAPTER I\.", r"THE END", nth=2),),
         section=r"CHAPTER [IVXL]+\."),
    Book(43, "The Strange Case of Dr Jekyll and Mr Hyde", "Robert Louis Stevenson", None, TALE,
         ranges=(Range(r"STORY OF THE DOOR", nth=2),)),
    Book(209, "The Turn of the Screw", "Henry James", None, TALE, ranges=(Range(r"The story had held us.*"),),
         section=r"[IVXL]+"),
    Book(1952, "The Yellow Wallpaper", "Charlotte Perkins Gilman", None, TALE, ranges=(Range(r"It is very seldom that.*"),)),
    # ----------------------------------------------------------- FOLKLORE <tale>
    Book(1597, "Andersen's Fairy Tales", "Hans Christian Andersen", None, TALE,
         ranges=(Range(r"THE EMPEROR'S NEW CLOTHES"),)),
    Book(5160, "The Mabinogion", "Anonymous", "Charlotte Guest", TALE,
         ranges=(Range(r"THE LADY OF THE FOUNTAIN", r"FOOTNOTES"),), inline_refs=(r"\s*\[\d+[a-z]?\]",)),
    Book(66057, "The Tale of Genji (Part I)", "Murasaki Shikibu", "Arthur Waley", TALE,
         ranges=(Range(r"CHAPTER I", r"APPENDIX I"),), inline_refs=(r"\[\d+\]",), section=r"CHAPTER [IVXL]+"),
    # ----------------------------------------------------------- HISTORY <chronicle>
    Book(2707, "The Histories, Volume 1", "Herodotus", "G. C. Macaulay", CHRONICLE,
         ranges=(Range(r"BOOK I\. THE FIRST BOOK OF THE HISTORIES.*"),),
         drop_blocks=((r"NOTES TO BOOK [IVX]+\.?", r"BOOK [IVX]+\. .*"),),
         inline_refs=(r"^\d+\.\s+", r"\s*\(\d+[a-z]?\)", r"(?<=\s)\d{1,3}\s"), drop_paragraphs=(r"—{3,}",),
         section=r"BOOK [IVX]+\. .*", work="The Histories"),
    Book(2456, "The Histories, Volume 2", "Herodotus", "G. C. Macaulay", CHRONICLE,
         ranges=(Range(r"BOOK V\. .*"),),
         drop_blocks=((r"NOTES TO BOOK [IVX]+\.?", r"BOOK [IVX]+\. .*"),),
         inline_refs=(r"^\d+\.\s+", r"\s*\(\d+[a-z]?\)", r"(?<=\s)\d{1,3}\s"), drop_paragraphs=(r"—{3,}",),
         section=r"BOOK [IVX]+\. .*", work="The Histories"),
    Book(7142, "The History of the Peloponnesian War", "Thucydides", "Richard Crawley", CHRONICLE,
         ranges=(Range(r"CHAPTER I", nth=2),), section=r"(BOOK [IVX]+|CHAPTER [IVXL]+.*)"),
    Book(1170, "Anabasis", "Xenophon", "H. G. Dakyns", CHRONICLE, ranges=(Range(r"BOOK I"),),
         # Dakyns prints section numbers between words ("and 1 the younger Cyrus").
         inline_refs=(r"\s*\[\d+\]", r"(?<=\s)\d{1,3}\s", r"\s*\(\d+\)"), section=r"(BOOK [IVX]+|[IVX]+\.?)"),
    *[Book(gid, f"The Twelve Caesars, Volume {n}", "Suetonius", "Alexander Thomson", CHRONICLE,
           ranges=(Range(r"I\.\s+[A-Z][a-z].*"),), inline_refs=(r"\s*\[\d+\]", r"^[IVXLC]+\.\s+"),
           drop_blocks=((r"FOOTNOTES:?", r"(?!x)x"),),  # the notes run to the end of each volume
           work="The Twelve Caesars")
      for n, gid in enumerate(range(6386, 6398), 1)],
    Book(3623, "The Golden Bough", "James George Frazer", None, CHRONICLE,
         ranges=(Range(r"I\. The King of the Wood"),), section=r"[IVXL]+\. [A-Z].*"),
)

# Dream-interpretation books: set aside in data/interpretation/, NOT trained on.
INTERPRETATION = (
    Book(66048, "The Interpretation of Dreams", "Sigmund Freud", "A. A. Brill", TALE,
         ranges=(Range(r"THE SCIENTIFIC LITERATURE ON THE PROBLEMS OF.*", r"INDEX"),), inline_refs=(r"\s*\[\d+\]",)),
)

# Books on the run 5 reading list that are NOT in the corpus, and why.
SKIPPED = (
    ("The Castle (Kafka)", "no public-domain English translation available as text: the Muirs' 1930 translation "
     "only entered the US public domain in 2026 and is not on Project Gutenberg"),
    ("The Trial (Kafka)", "the only English text on Project Gutenberg is David Wyllie's 2003 translation, which "
     "is copyrighted (Gutenberg distributes it with his permission); the Muirs' 1937 translation is public domain "
     "in the US only from 2033"),
    ("Letters from a Stoic (Seneca)", "Gummere's translation (1917-25) is public domain but not on Project Gutenberg; "
     "Gutenberg has only other Seneca (On Benefits, Minor Dialogues)"),
    ("The Enneads (Plotinus)", "MacKenna's translation (1917-30) is not on Project Gutenberg; only one short essay is"),
    ("The Panchatantra", "no public-domain English translation on Project Gutenberg (Ryder's 1925 one is PD in the "
     "US but not digitised there)"),
    ("The Book of Dede Korkut", "no public-domain English translation exists (the first full ones are from 1972 and 1974)"),
    ("The Descent of Inanna", "no public-domain English translation: the Sumerian text was pieced together and "
     "translated (Kramer) from the 1930s on"),
    ("One Thousand and One Nights", "dropped as a duplicate of The Arabian Nights (Lang's selection is already in)"),
    ("The Oneirocritica (Artemidorus)", "for data/interpretation/: no public-domain English translation on Project "
     "Gutenberg (Wood's 1644 version is not digitised there)"),
)
