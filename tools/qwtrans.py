"""Validation and normalisation for the translation editions in this repo.

Every file under `translations/` is a flat map of all 6,236 ayahs, keyed
"<surah>:<ayah>" -> {"t": text} -- QUL's `simple.json` export shape. Nothing
used to check that shape held. This module is what does.

The split that matters here is between normalising and reporting:

  * NORMALISE covers mechanical, meaning-preserving defects -- invisible
    formatting residue left by an export. These are rewritten in place, and the
    change is legible as a diff.

  * REPORT covers everything that would change a word. A stray Latin `c` in a
    Cyrillic edition is a typo in scripture translation; guessing at the intended
    character is a content edit, and belongs to a person with the source open.
    The checker names it and stops.

See tools/README.md for the reasoning behind each check.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scriptdata import MARK_SCRIPTS, NEUTRAL_LETTERS, SCRIPT_RANGES

REPO = Path(__file__).resolve().parent.parent
TRANSLATIONS = REPO / "translations"

# Directories whose files the app fetches over the CDN, and so whose contents
# need a version in versions.json. tools/ and the READMEs are deliberately
# absent: nothing downloads them, and listing them would churn the manifest
# on every documentation edit.
DATA_DIRS = (
    "translations",
    "topics",
    "morphology",
    "similar-ayahs",
    "transliteration",
    "mushaf-layout",
    "quran-script",
    "audio-segments",
)

VERSIONS = REPO / "versions.json"

# --------------------------------------------------------------------------
# Canonical ayah structure
# --------------------------------------------------------------------------

# Ayah count per surah, 1..114, in the Hafs numbering the app and QUL both use.
AYAH_COUNTS = [
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128,
    111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73,
    54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29, 18, 45, 60,
    49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30, 52, 52, 44,
    28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22, 17, 19, 26, 30,
    20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6, 3, 5, 4,
    5, 6,
]

CANONICAL_KEYS = [
    f"{surah}:{ayah}"
    for surah, count in enumerate(AYAH_COUNTS, start=1)
    for ayah in range(1, count + 1)
]
CANONICAL_SET = frozenset(CANONICAL_KEYS)
TOTAL_AYAHS = len(CANONICAL_KEYS)

assert len(AYAH_COUNTS) == 114
assert TOTAL_AYAHS == 6236

# --------------------------------------------------------------------------
# Character classes
# --------------------------------------------------------------------------

# ZWNJ and ZWJ share Unicode category Cf with the bidi marks below, but they are
# orthography, not residue: ZWNJ separates prefixes and plural markers in Persian
# and Kurdish, ZWJ forms Malayalam chillu letters. ku-amin alone carries 124,737
# ZWNJ. Stripping these would corrupt four editions far worse than any defect
# this tool exists to fix. They are never touched.
PROTECTED = frozenset({0x200C, 0x200D})

# Directional controls. In prose that is uniformly one direction they do nothing
# but confuse base-direction inference -- ku-amin 78:14 and 78:37 open with an
# LRM, which flips those verses to LTR on Android (issue #72).
BIDI_CONTROLS = frozenset({
    0x200E,  # LEFT-TO-RIGHT MARK
    0x200F,  # RIGHT-TO-LEFT MARK
    0x061C,  # ARABIC LETTER MARK
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,          # embedding / override
    0x2066, 0x2067, 0x2068, 0x2069,                  # isolates
})

# Invisible, and carried by no bundled font. Soft hyphen and BOM-as-ZWNBSP also
# break substring search and copy-paste.
INVISIBLE_STRIP = frozenset({0x00AD, 0xFEFF})

# Control-category whitespace, which has no place in a single-line verse and is
# folded to a plain space. NO-BREAK SPACE is deliberately absent: it is correct
# typography before punctuation in French and Italian, and appears legitimately
# in seven editions.
WHITESPACE_FOLD = frozenset({0x0009, 0x000A, 0x000B, 0x000C, 0x000D, 0x0085})

# UTF-8 bytes re-read as cp1252 leave a lead byte rendered as A-tilde /
# A-circumflex / a-circumflex followed by a C1 control or soft hyphen. Narrowed
# to a C1 continuation deliberately: allowing cp1252 punctuation as the second
# character matches ordinary French and Italian typography ("Sa'ibah", "râ'inâ").
#
# The second alternative is that same damage read through ISO-8859-2 rather than
# cp1252, which is what a Central European export pipeline does. Latin-2 has no
# undefined C1 positions, so the continuation byte surfaces as an ordinary letter
# and the first alternative never fires: U+00AB and U+00BB encode to C2 AB and
# C2 BB, and Latin-2 renders AB and BB as T-caron and t-caron. Deliberately
# limited to that one pair rather than the whole Latin-2 continuation range
# (0xA0-0xBF), because most of that range is ordinary Polish and Czech letters,
# and A-circumflex followed by a letter is ordinary Vietnamese and French --
# vi-abdulkarim alone carries 123 legitimate U+00C2 verses.
MOJIBAKE = re.compile("[\u00c3\u00c2\u00e2][\u0080-\u009f\u00ad]|\u00c2[\u0164\u0165]")

# C1 controls (U+0080-U+009F) reviewed by hand and confirmed to be residue rather
# than half of a mis-decoded character, keyed edition -> verses. Only these are
# stripped; every other stray control byte is still reported and left alone.
#
# The gate is deliberately per verse rather than a blanket rule. ko-choi 49:10
# carries an isolated U+0098 too, but it sits beside a broken Latin fragment --
# evidence of real corruption, where deleting the byte would hide the damage.
# Stripping every isolated C1 would silently rewrite that verse as well.
#
# ku-amin 33:36 / 33:39 / 33:40 (issue #75) meet the bar: one U+009D each, always
# the second-to-last character between the final letter and the sentence-ending
# stop, with the preceding words complete and nothing plausibly lost. Confirmed
# character for character against QUL resource 144, which carries the same byte
# -- so no re-export can fix them and there is nothing to preserve the evidence
# for. See tools/README.md, "When a control byte can be stripped".
STRIPPABLE_CONTROLS: dict[str, frozenset[str]] = {
    "ku-amin": frozenset({"33:36", "33:39", "33:40"}),
}

C1_CONTROLS = frozenset(range(0x80, 0xA0))

# Double-decoded UTF-8 sequences repaired by hand, keyed edition -> verses.
#
# DIFFERENT MECHANISM FROM STRIPPABLE_CONTROLS ABOVE, and deliberately so.
# There, an isolated C1 byte is residue and deleting it loses nothing. Here the
# C1 byte is HALF OF A REAL CHARACTER: "\u00e2\u0080\u0093" is the three bytes
# of an en dash read as Latin-1. Stripping the controls would leave a bare "â"
# behind -- visibly worse than the defect -- which is exactly why
# normalise_text() bails out on any verse matching MOJIBAKE and why this table
# has to put the intended character back rather than remove anything.
#
# Gated per verse for the same reason STRIPPABLE_CONTROLS is: a blanket rule
# would rewrite text nobody has read. Each verse below was inspected
# individually and the intended punctuation is unambiguous from context.
MOJIBAKE_REPAIRS: dict[str, frozenset[str]] = {
    "pl-bielawski": frozenset({
        "3:140", "7:156", "18:94", "56:60", "69:41", "7:161",
        # U+00C2 + U+00AD, a double-encoded SOFT HYPHEN, dropped whole rather
        # than restored -- see _SOFT_HYPHEN_PAIR below. Authorised by the app
        # owner as a specific content decision, not a general rule. 6:136
        # carries two occurrences; seven across the six verses, and they are
        # the only soft hyphens anywhere in the repo.
        "6:136", "6:138", "6:145", "7:135", "7:148", "20:131",
    }),
}

# The only sequences this repairs. Anything else stays untouched and keeps
# tripping the checker, so a genuinely mis-exported file still gets reported.
_MOJIBAKE_SEQUENCES = {
    "\u00e2\u0080\u0093": "\u2013",  # EN DASH
    "\u00e2\u0080\u0099": "\u2019",  # RIGHT SINGLE QUOTATION MARK
    "\u00e2\u0080\u009d": "\u201d",  # RIGHT DOUBLE QUOTATION MARK
    # Read through ISO-8859-2 rather than cp1252 -- see MOJIBAKE above. The pair
    # brackets a quotation, and pl-bielawski 7:161 is the only verse carrying it.
    "\u00c2\u0164": "\u00ab",        # LEFT-POINTING DOUBLE ANGLE QUOTATION MARK
    "\u00c2\u0165": "\u00bb",        # RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK
}

# The one mis-decoded sequence that is DROPPED rather than put back: U+00C2
# followed by U+00AD, the two bytes of a SOFT HYPHEN read as Latin-1. The
# intended character is itself invisible and its role in the sentence is not
# recoverable, so restoring it would only re-hide the damage; the app owner
# authorised dropping the pair outright for the six pl-bielawski verses listed
# in MOJIBAKE_REPAIRS.
#
# Matched with its flanking spaces because deleting the two characters on their
# own leaves a VISIBLE DOUBLE SPACE wherever the pair sat between two words --
# 6:136, 6:138 and 7:148 all do. React Native's <Text> does not collapse
# whitespace, and normalise_text() deliberately leaves runs of ordinary spaces
# alone, so nothing downstream would tidy it up. A match that swallowed any
# space collapses to exactly one; a match with no space either side leaves
# nothing behind, which is right for "twierdz\u0105,<pair> a" and "\u015bwiecie<pair> by".
_SOFT_HYPHEN_PAIR = re.compile(" *\u00c2\u00ad *")


def repair_mojibake(text: str) -> str:
    """Put back the characters a Latin-1 misread broke apart.

    Returns the text unchanged if any C1 control survives the pass -- that means
    a sequence outside _MOJIBAKE_SEQUENCES is present, and a partial repair
    would both corrupt the verse and hide the rest of the damage.
    """
    fixed = text
    for broken, intended in _MOJIBAKE_SEQUENCES.items():
        fixed = fixed.replace(broken, intended)
    fixed = _SOFT_HYPHEN_PAIR.sub(
        lambda m: " " if " " in m.group(0) else "", fixed
    )
    if any(0x80 <= ord(ch) <= 0x9F for ch in fixed):
        return text
    return fixed

# Everything normalise_text() removes or folds. The checker reports only the
# control characters it deliberately leaves alone -- a stray C1 byte is a
# decoding failure, and deleting it would hide a file that needs re-exporting.
NORMALISED_AWAY = BIDI_CONTROLS | INVISIBLE_STRIP | WHITESPACE_FOLD

# A script appearing in fewer than this share of an edition's verses is treated
# as contamination rather than as part of the edition's writing system.
RARE_SCRIPT_RATIO = 0.02


@lru_cache(maxsize=None)
def script_of(ch: str) -> str | None:
    """Return the script of a base letter, or None if the character is neutral.

    Punctuation, digits, spaces, symbols and combining marks are all neutral
    here -- every edition uses ASCII punctuation and Latin digits, and marks are
    judged against their base by mark_scripts() instead. So are letters that
    belong to no single script: the Japanese prolonged sound mark, Arabic
    tatweel, the modifier half-ring standing in for 'ayn in English.
    """
    if not unicodedata.category(ch).startswith("L"):
        return None
    cp = ord(ch)
    for lo, hi in NEUTRAL_LETTERS:
        if lo <= cp <= hi:
            return None
    for script, ranges in SCRIPT_RANGES.items():
        for lo, hi in ranges:
            if lo <= cp <= hi:
                return script
    return "Unknown"


@lru_cache(maxsize=None)
def mark_scripts(ch: str) -> tuple[str, ...] | None:
    """Scripts a combining mark is legitimately used with, or None if not a mark."""
    if not unicodedata.category(ch).startswith("M"):
        return None
    cp = ord(ch)
    for lo, hi, allowed in MARK_SCRIPTS:
        if lo <= cp <= hi:
            return allowed
    return ()


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

# A run of control whitespace together with any plain spaces flanking it. Matched
# as one unit so the whole run folds to exactly one space, rather than leaving
# behind the spaces that happened to sit either side of a TAB.
_FOLD_RUN = re.compile(
    " *[%s]+ *" % "".join("\\u%04x" % cp for cp in sorted(WHITESPACE_FOLD))
)


def combining_sequences(text: str) -> list[str]:
    """Split into base-plus-marks clusters, the unit NFC is applied to here.

    A cluster is one non-mark character followed by every combining mark that
    attaches to it. Splitting this way is what lets composition be applied to
    one cluster while the cluster next to it is left exactly as found.
    """
    out: list[str] = []
    current = ""
    for ch in text:
        if current and not unicodedata.category(ch).startswith("M"):
            out.append(current)
            current = ch
        else:
            current += ch
    if current:
        out.append(current)
    return out


def reorders_marks(cluster: str) -> bool:
    """Whether NFC would move a combining mark within this cluster.

    Canonical ordering sorts marks by combining class, which is not the order
    Arabic is typed or stored in: shadda (ccc 33) is written before its vowel
    (ccc 27-32), so NFC swaps the pair. The two forms are canonically
    equivalent and HarfBuzz shapes them identically, but CoreText does not --
    see the note in tools/README.md.

    Detected by decomposing twice: once canonically, which sorts, and once
    character by character, which preserves the stored order. Where those agree
    NFC only composes, and composition is safe.
    """
    return unicodedata.normalize("NFD", cluster) != "".join(
        unicodedata.normalize("NFD", ch) for ch in cluster
    )


def compose_text(text: str) -> str:
    """NFC, applied only where it will not reorder a combining mark.

    Clusters that would be reordered are left byte for byte as found and
    reported by the `mark-order` check instead. That keeps this function in the
    same lane as the rest of normalise_text(): it changes nothing a reader can
    see.
    """
    return "".join(
        cluster if reorders_marks(cluster) else unicodedata.normalize("NFC", cluster)
        for cluster in combining_sequences(text)
    )


def normalise_text(text: str, *, strip_controls: bool = False) -> str:
    """Apply every mechanical, meaning-preserving fix. Never changes a word.

    `strip_controls` additionally removes C1 control bytes, and is set only for
    the verses listed in STRIPPABLE_CONTROLS -- never wholesale.
    """
    # A verse carrying double-encoded UTF-8 is left exactly as found. Its soft
    # hyphens and C1 bytes are halves of mis-decoded characters, not residue:
    # stripping them would leave a stray "Â" behind and, worse, destroy the
    # signature the checker uses to report the file as needing a re-export.
    # No edition in the repo trips this today -- pl-bielawski was the last, and
    # its verses are all repaired through MOJIBAKE_REPAIRS now. The guard stays
    # for the next mis-exported file.
    if MOJIBAKE.search(text):
        return text

    out = []
    for ch in text:
        cp = ord(ch)
        if cp in PROTECTED:
            out.append(ch)
        elif cp in BIDI_CONTROLS or cp in INVISIBLE_STRIP:
            continue
        elif strip_controls and cp in C1_CONTROLS:
            continue
        else:
            out.append(ch)

    # Fold each run of control whitespace, plus any spaces flanking it, down to a
    # single space. Runs of ordinary spaces elsewhere are left alone: 681 verses
    # in it-piccardo are double-spaced, which is cosmetic rather than a defect,
    # and rewriting them would bury the real fixes in the diff.
    folded = _FOLD_RUN.sub(" ", "".join(out)).strip()

    # Compose last, so it sees the text with the residue already gone.
    return compose_text(folded)


# Editions whose SOURCE LICENCE forbids altering the text, so the mechanical
# normalisation above must not touch them at all.
#
# ka-rwwad comes from QuranEnc.com, not QUL, and is re-published under terms
# whose first condition is "No modification, addition, or deletion of the
# content" -- with no de-minimis carve-out for whitespace. Its 146 verses
# carrying literal newlines are the source's own line breaks, and folding them
# to spaces would be exactly the modification the licence prohibits. Keeping
# them is a deliberate decision by the app owner, not an oversight, so
# `check` reporting them as "pending-normalisation" is expected and must stay
# unresolved.
#
# Distinct from STRIPPABLE_CONTROLS above, which is an opt-IN to one extra
# repair for named verses. This is an opt-OUT of all of them for a whole
# edition, and the justification bar is different: a written term forbidding
# modification, not a hand review of the damage.
#
# ro-islam4ro (added 2026-09-17, replacing ro-grigore in the app -- see
# quranwise#112) comes from QuranEnc.com under the same seven terms, so it is
# held to the same rule: stored exactly as the API returns it, footnotes and all.
UNMODIFIABLE = frozenset({"ka-rwwad", "ro-islam4ro"})


def normalise_edition(data: dict, name: str | None = None) -> tuple[dict, int]:
    """Normalise every verse. Returns the new map and the count of changed verses.

    `name` selects the edition's STRIPPABLE_CONTROLS entry; without it no control
    byte is stripped, so callers that do not know the edition stay conservative.
    It also gates UNMODIFIABLE, which skips normalisation for the edition
    entirely.

    Preserves every field on each entry, not just "t". Rebuilding entries as
    {"t": ...} silently dropped any other key -- which would have deleted all
    372 of ka-rwwad's footnote bodies the first time this ran over it, and
    deleting a footnote is a content deletion under that edition's terms.
    """
    if name in UNMODIFIABLE:
        return data, 0

    strippable = STRIPPABLE_CONTROLS.get(name or "", frozenset())
    repairable = MOJIBAKE_REPAIRS.get(name or "", frozenset())
    out, changed = {}, 0
    for key, value in data.items():
        original = value["t"]
        # Repair BEFORE normalise_text, which bails out on any verse still
        # matching MOJIBAKE and would otherwise return it untouched.
        text = repair_mojibake(original) if key in repairable else original
        fixed = normalise_text(text, strip_controls=key in strippable)
        if fixed != original:
            changed += 1
        out[key] = {**value, "t": fixed}
    return out, changed


# --------------------------------------------------------------------------
# Corpus-level heuristics
# --------------------------------------------------------------------------

# Spreadsheet error sentinels, in the localisations a QUL contributor's export
# could plausibly have been produced in. A cell that failed to evaluate is
# written out as its error literal, and a whole verse consisting of nothing but
# one of these is an export failure, not a translation.
#
# MATCHED ANCHORED, against the whole trimmed value -- never as a substring.
# That is what makes the check free of false positives: a translation that
# happens to discuss a number or a reference still contains prose around it.
# Measured across the corpus, exactly three verses match, and only three verses
# in the entire repo contain a "#" at all.
_ERROR_LITERALS = (
    # Excel / Google Sheets, en-US
    "#NAME?", "#VALUE!", "#REF!", "#DIV/0!", "#N/A", "#NUM!", "#NULL!",
    "#ERROR!", "#SPILL!", "#CALC!", "#GETTING_DATA",
    # Czech -- the form actually found, in cs-czech
    "#NÁZEV?", "#HODNOTA!", "#ODKAZ!", "#DĚLENÍ_NULOU!", "#ČÍSLO!",
    "#NENÍ_K_DISPOZICI", "#NEPLATNÝ!",
    # German
    "#WERT!", "#BEZUG!", "#NV", "#ZAHL!", "#LEER!",
    # French
    "#NOM?", "#VALEUR!", "#NOMBRE!", "#NUL!",
    # Dutch
    "#NAAM?", "#WAARDE!", "#VERW!", "#DEEL/0!", "#N/B", "#GETAL!",
    # Swedish
    "#NAMN?", "#VÄRDEFEL!", "#REFERENS!", "#DIVISION/0!", "#SAKNAS!",
    "#OGILTIGT!", "#SKÄRNING!",
    # Danish / Norwegian
    "#NAVN?", "#VÆRDI!", "#REFERENCE!", "#I/T", "#TOM!",
    # Finnish
    "#NIMI?", "#ARVO!", "#VIITTAUS!", "#JAKO/0!", "#PUUTTUU", "#LUKU!", "#TYHJÄ!",
    # Russian
    "#ИМЯ?", "#ЗНАЧ!", "#ССЫЛКА!", "#ДЕЛ/0!", "#Н/Д", "#ЧИСЛО!", "#ПУСТО!",
)

ERROR_LITERAL = re.compile(
    r"\A[\s.]*(?:%s)[\s.]*\Z"
    % "|".join(re.escape(s) for s in dict.fromkeys(_ERROR_LITERALS)),
    re.IGNORECASE,
)

# Editions exempted from one of the heuristic checks below, keyed check ->
# editions. Same shape and the same bar as UNMODIFIABLE: an opt-OUT for a whole
# edition, added only after reading the verses it covers.
#
# These four checks are heuristics over text length and repetition. They cannot
# prove a defect, only point a human at one, so each is severity `review` and
# each carries an escape hatch for editions whose house style trips it by
# design. `verse-offset` in particular must NEVER be promoted to a blocker.
HEURISTIC_OPT_OUT: dict[str, frozenset[str]] = {
    # Editions whose glossing style legitimately runs several times the
    # cross-edition median: bracketed exegetical expansion inside the verse
    # text. Measured, these six account for 88 of the 198 raw flags, and every
    # one sampled was ordinary expansive translation rather than damage.
    "length-outlier": frozenset({
        "tr-diyanet", "tt-tatar", "ku-amin", "dv-maldives", "fi-finnish",
        "fa-taji",
    }),
    # GROUPED-BLOCK EDITIONS. These translate a run of ayahs as one block and
    # then store that identical block in every slot of the group, so adjacent
    # duplicates are the format, not a defect. Without this gate the check is
    # useless: tr-diyanet alone contributes 843 of 960 raw pairs and
    # dv-maldives another 77 -- 96% of the total, all by design.
    "adjacent-duplicate": frozenset({"tr-diyanet", "dv-maldives"}),
    # Confirmed correctly aligned by reading each flagged run against en-sahih
    # verse by verse. All three are short-verse passages where the cross-edition
    # profile is too small to carry a reliable signal, and the run happens to
    # correlate better with its neighbour by chance.
    "verse-offset": frozenset({"bn-zakaria", "sv-bernstrom", "vi-abdulkarim"}),
}

# length-outlier fires when a verse is BOTH more than this many times the
# cross-edition median AND this many characters above it. Two conditions rather
# than one because either alone is noise: short verses trip a ratio easily, and
# long ones trip an absolute delta easily.
OUTLIER_RATIO = 3.0
OUTLIER_DELTA = 400

# adjacent-duplicate's second gate. Some consecutive ayahs ARE near-identical in
# the Arabic -- 94:5-6, 102:3-4, 82:17-18, 78:4-5, 75:34-35 -- and a faithful
# translation of them is legitimately identical. Similarity is measured on the
# diacritic-stripped Arabic from quran-script/qpc-hafs.json. Measured over the
# 40 pairs surviving the opt-out, the split is wide open: nine pairs score
# 0.9167 and above, and the next value down is 0.4381. Anything in that gap
# would do; 0.85 sits well inside it.
ARABIC_SIMILARITY_GATE = 0.85

# verse-offset. A verse votes for an offset only when the neighbouring slot's
# expected length beats its own by this margin, and only a run of this many
# consecutive agreeing votes is reported. Deliberately tuned for RECALL: a
# minimum-profile guard would cut the false positives from three editions to
# none, but it also loses cs-czech and ha-gumi, both confirmed genuine. Missing
# a real misalignment is the expensive failure here; a false one costs a human
# five minutes and an opt-out line.
OFFSET_RUN = 6
OFFSET_MARGIN = 1.30


def _verse_text(value) -> str:
    text = value.get("t") if isinstance(value, dict) else value
    return text if isinstance(text, str) else ""


@lru_cache(maxsize=1)
def length_profile() -> dict[str, float]:
    """Median verse length across every edition on disk, per ayah key.

    The profile is a property of the CORPUS, not of whichever editions the
    caller selected, so it is always built from all of them -- checking one
    edition against a profile derived from itself would measure nothing.
    """
    import statistics

    lengths: dict[str, list[int]] = {}
    for path in editions():
        try:
            data = load(path)
        except (OSError, json.JSONDecodeError):
            continue
        for key, value in data.items():
            text = _verse_text(value)
            if text.strip():
                lengths.setdefault(key, []).append(len(text))
    return {k: statistics.median(v) for k, v in lengths.items() if v}


@lru_cache(maxsize=1)
def arabic_skeletons() -> dict[str, str]:
    """Diacritic-stripped Arabic per ayah, or {} if the script file is absent.

    Letters only: combining marks, the end-of-ayah number and its NO-BREAK
    SPACE, tatweel and punctuation all go, leaving the consonantal skeleton --
    the part two near-identical ayahs actually share.
    """
    path = REPO / "quran-script" / "qpc-hafs.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    out = {}
    for key, value in raw.items():
        text = value.get("text", "") if isinstance(value, dict) else str(value)
        decomposed = unicodedata.normalize("NFD", text)
        out[key] = "".join(
            ch for ch in decomposed if unicodedata.category(ch).startswith("L")
        )
    return out


def arabic_similarity(first: str, second: str) -> float:
    """How alike two ayahs are in the bare Arabic. 0.0 when either is unknown."""
    import difflib

    skeletons = arabic_skeletons()
    a, b = skeletons.get(first, ""), skeletons.get(second, "")
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# Canonical keys grouped by surah, so the heuristics never compare the last
# ayah of one surah with the first of the next.
SURAH_KEYS: list[list[str]] = [
    [f"{surah}:{ayah}" for ayah in range(1, count + 1)]
    for surah, count in enumerate(AYAH_COUNTS, start=1)
]


def _length_outliers(name: str, data: dict, profile: dict[str, float]) -> list[str]:
    if name in HEURISTIC_OPT_OUT["length-outlier"]:
        return []
    flagged = []
    for key, value in data.items():
        expected = profile.get(key, 0.0)
        if not expected:
            continue
        length = len(_verse_text(value))
        if length > OUTLIER_RATIO * expected and length - expected > OUTLIER_DELTA:
            flagged.append(key)
    return flagged


def _adjacent_duplicates(name: str, data: dict) -> list[str]:
    """Consecutive ayahs within a surah whose translations are byte-identical.

    Both gates are mandatory -- see HEURISTIC_OPT_OUT and
    ARABIC_SIMILARITY_GATE. Ungated this check is 97% false.

    Reports the pair as the SECOND key of each pair, which is the one a repair
    would have to touch.
    """
    if name in HEURISTIC_OPT_OUT["adjacent-duplicate"]:
        return []
    flagged = []
    for keys in SURAH_KEYS:
        for first, second in zip(keys, keys[1:]):
            if first not in data or second not in data:
                continue
            text = _verse_text(data[first]).strip()
            if not text or text != _verse_text(data[second]).strip():
                continue
            if arabic_similarity(first, second) >= ARABIC_SIMILARITY_GATE:
                continue
            flagged.append(second)
    return flagged


def _offset_runs(name: str, data: dict, profile: dict[str, float]):
    """Runs of verses whose length fits a NEIGHBOURING slot better than their own.

    A length-profile correlation with a windowed +/-1 vote: for each ayah, the
    expected length of its own slot and of the two beside it are compared
    against what this edition actually stores, scaled by how verbose the edition
    is overall. A run of consecutive ayahs all voting the same way is the
    signature of a block that slipped by one.

    HEURISTIC, AND ONLY EVER SEVERITY `review`. It is a correlation over
    character counts. It cannot prove a misalignment and must never be promoted
    to a blocker -- a shift it points at still has to be read by a person
    against the Arabic before anything is changed.
    """
    if name in HEURISTIC_OPT_OUT["verse-offset"]:
        return []

    import statistics

    ratios = [
        len(_verse_text(data[k])) / profile[k]
        for k in profile
        if profile[k] and k in data and _verse_text(data[k]).strip()
    ]
    if not ratios:
        return []
    scale = statistics.median(ratios)

    runs = []
    for keys in SURAH_KEYS:
        votes = []
        for index, key in enumerate(keys):
            length = len(_verse_text(data.get(key, "")))
            if not length or not profile.get(key):
                votes.append(0)
                continue
            error = {}
            for offset in (-1, 0, 1):
                neighbour = index + offset
                if 0 <= neighbour < len(keys) and profile.get(keys[neighbour]):
                    expected = scale * profile[keys[neighbour]]
                    error[offset] = abs(length - expected) / max(expected, 1.0)
            if 0 not in error:
                votes.append(0)
                continue
            best = min(error, key=error.get)
            fits_better = error[0] > OFFSET_MARGIN * error[best] + 0.02
            votes.append(best if best != 0 and fits_better else 0)

        start = 0
        while start < len(votes):
            if votes[start] == 0:
                start += 1
                continue
            end = start
            while end < len(votes) and votes[end] == votes[start]:
                end += 1
            if end - start >= OFFSET_RUN:
                runs.append((keys[start], keys[end - 1], votes[start], end - start))
            start = end
    return runs


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

@dataclass
class Finding:
    check: str
    severity: str          # "blocker" | "review" | "normalised"
    verses: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def count(self) -> int:
        return len(self.verses)


def _codepoint_label(ch: str) -> str:
    try:
        name = unicodedata.name(ch)
    except ValueError:
        name = "<control>"
    return f"U+{ord(ch):04X} {name}"


def check_edition(name: str, data: dict, allow_scripts: list[str]) -> list[Finding]:
    """Run every check against one edition. Assumes `data` is the raw file."""
    findings: list[Finding] = []

    def add(check, severity, verses, detail=""):
        if verses:
            findings.append(Finding(check, severity, sorted(set(verses), key=_key_order), detail))

    keys = set(data)
    add("missing-ayah", "blocker", CANONICAL_SET - keys,
        f"expected {TOTAL_AYAHS} canonical keys, found {len(keys)}")
    add("unknown-ayah", "blocker", keys - CANONICAL_SET,
        "key is not a valid surah:ayah reference")

    # A whole verse that is nothing but a spreadsheet error sentinel is an
    # export failure. Blocker: unlike the heuristics below there is no judgement
    # in it -- the value is not a translation, and no re-reading will make it one.
    add("error-literal", "blocker",
        [k for k, v in data.items() if ERROR_LITERAL.match(_verse_text(v))],
        "value is a spreadsheet error sentinel, not a translation")

    empty, stub, controls, mojibake, private, marks = [], [], [], [], [], []
    mark_detail: dict[str, int] = {}
    control_chars: dict[str, int] = {}
    private_chars: dict[str, int] = {}
    script_verses: dict[str, set] = {}

    for key, value in data.items():
        text = value.get("t") if isinstance(value, dict) else value
        if not isinstance(text, str):
            add("bad-shape", "blocker", [key], "value is not {'t': str}")
            continue

        if not text.strip():
            empty.append(key)

        if MOJIBAKE.search(text):
            mojibake.append(key)

        seen_scripts = set()
        base_script = None
        for ch in text:
            cp, cat = ord(ch), unicodedata.category(ch)
            if cp in PROTECTED:
                continue
            if cat in ("Cc", "Cf") and cp not in NORMALISED_AWAY:
                controls.append(key)
                label = _codepoint_label(ch)
                control_chars[label] = control_chars.get(label, 0) + 1
            elif cat == "Co":
                private.append(key)
                label = _codepoint_label(ch)
                private_chars[label] = private_chars.get(label, 0) + 1
            script = script_of(ch)
            if script:
                seen_scripts.add(script)
                base_script = script
                continue

            # A combining mark belongs to a known set of scripts. One sitting on
            # a base outside that set is corruption, not orthography -- an Arabic
            # fatha inside a Dutch word (nl-siregar 44:37) rather than a macron
            # over a Latin vowel.
            allowed = mark_scripts(ch)
            if allowed is not None and base_script and base_script not in allowed:
                marks.append(key)
                label = f"{_codepoint_label(ch)} on {base_script}"
                mark_detail[label] = mark_detail.get(label, 0) + 1
        for script in seen_scripts:
            script_verses.setdefault(script, set()).add(key)

    total = len(data) or 1
    dominant = {s for s, vs in script_verses.items() if len(vs) >= total * RARE_SCRIPT_RATIO}

    # A verse carrying none of the edition's own scripts and almost no text is a
    # placeholder, not a translation -- ha-gumi 27:55 is the string "49.".
    for key, value in data.items():
        text = value.get("t") if isinstance(value, dict) else ""
        if not isinstance(text, str) or not text.strip():
            continue
        if dominant and not any(script_of(ch) in dominant for ch in text):
            stub.append(key)

    add("empty-text", "blocker", empty, "verse present but has no text")
    add("non-prose-stub", "blocker", stub, "value contains none of this edition's scripts")
    add("control-character", "blocker", controls,
        "; ".join(f"{k} x{v}" for k, v in sorted(control_chars.items())) or "stray control byte")
    add("double-encoded-utf8", "blocker", mojibake, "UTF-8 bytes re-read as cp1252")
    add("private-use", "review", private,
        "; ".join(f"{k} x{v}" for k, v in sorted(private_chars.items()))
        + " -- renders only in the font it was authored for")
    add("mark-script-mismatch", "review", marks,
        "; ".join(f"{k} x{v}" for k, v in sorted(mark_detail.items()))
        or "combining mark on a base script it is never used with")

    # Mechanical residue that `normalise` would remove. Not a defect in the data
    # so much as a sign the file was hand-edited or converted without the tool.
    pending = [k for k, v in data.items()
               if isinstance(v, dict) and isinstance(v.get("t"), str)
               and normalise_text(v["t"]) != v["t"]]
    add("pending-normalisation", "normalised", pending,
        "run `python3 tools/qwt.py normalise` to clear")

    # Verses whose marks are stored in an order canonical ordering would change,
    # and which `normalise` therefore leaves alone. Reported so the gap between
    # these files and strict NFC stays visible and countable rather than being
    # quietly absorbed by the composition pass.
    held, held_detail = [], {}
    for key, value in data.items():
        text = value.get("t") if isinstance(value, dict) else None
        if not isinstance(text, str):
            continue
        for cluster in combining_sequences(text):
            if len(cluster) > 1 and reorders_marks(cluster):
                held.append(key)
                marks = "+".join(_codepoint_label(ch) for ch in cluster[1:])
                held_detail[marks] = held_detail.get(marks, 0) + 1
    add("mark-order", "review", held,
        "; ".join(f"{k} x{v}" for k, v in sorted(held_detail.items(), key=lambda kv: -kv[1])[:4])
        + " -- stored order kept; NFC would reorder these and CoreText renders"
          " the two differently")

    for script, verses in sorted(script_verses.items()):
        if script in dominant or script in allow_scripts:
            continue
        samples = ", ".join(sorted(verses, key=_key_order)[:5])
        add("foreign-script", "review", verses,
            f"{script} in {len(verses)} of {total} verses (e.g. {samples})")

    # Corpus-level heuristics. All three are `review` and all three are gated --
    # see HEURISTIC_OPT_OUT. `verse-offset` must never become a blocker.
    profile = length_profile()

    outliers = _length_outliers(name, data, profile)
    if outliers:
        worst = max(outliers, key=lambda k: len(_verse_text(data[k])))
        # Names the edition's longest outlier for scale, which is not
        # necessarily one of the verses printed below -- the rest may already
        # be in the heuristics baseline.
        add("length-outlier", "review", outliers,
            f"over {OUTLIER_RATIO:g}x the cross-edition median and +{OUTLIER_DELTA}"
            f" chars; this edition's longest such verse is {worst} at"
            f" {len(_verse_text(data[worst]))} chars against a median of"
            f" {profile.get(worst, 0):.0f}")

    add("adjacent-duplicate", "review", _adjacent_duplicates(name, data),
        "identical to the preceding ayah, which the Arabic does not explain"
        f" (similarity below {ARABIC_SIMILARITY_GATE})")

    runs = _offset_runs(name, data, profile)
    if runs:
        described = "; ".join(
            f"{a}..{b} by {off:+d} ({length} verses)" for a, b, off, length in
            sorted(runs, key=lambda r: -r[3])[:4]
        )
        add("verse-offset", "review", [a for a, _b, _o, _l in runs],
            f"length profile fits a neighbouring slot better across {described}"
            " -- a heuristic over character counts, never proof; read the range"
            " against the Arabic before changing anything")

    return findings


def _key_order(key: str):
    try:
        surah, ayah = key.split(":")
        return (int(surah), int(ayah))
    except (ValueError, AttributeError):
        return (999, 0)


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------

def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def dump(path: Path, data: dict) -> None:
    """Write in the exact shape the CDN already serves.

    Compact separators, no ASCII escaping, no trailing newline -- and crucially
    the caller's key order, untouched. The QUL exports are not in surah:ayah
    order and never were; re-sorting them would rewrite every one of the 46
    files end to end and bury the real change in the diff.
    """
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))


def known_issues() -> dict:
    """Blocking findings accepted for now, so CI fails on new breakage only.

    A baseline, not a suppression list -- see tools/known-issues.json.
    """
    path = Path(__file__).resolve().parent / "known-issues.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh).get("accepted", {})


# The three corpus-level heuristics, whose steady-state cost has to be near
# zero or nobody will read the output. `check` reports only the verses these
# flag that are NOT already in the heuristics baseline, and drops the finding
# entirely when there are none -- so a run is quiet until an edition's outliers
# CHANGE, which is the event worth a human's attention.
#
# Verse lists rather than bare counts, matching the rest of known-issues.json:
# a count cannot tell "one outlier went away and another appeared" from "nothing
# happened", and that swap is exactly the shape of a bad re-export.
HEURISTIC_CHECKS = frozenset({"length-outlier", "adjacent-duplicate", "verse-offset"})


def heuristic_baseline() -> dict:
    """Accepted heuristic flags, keyed edition -> check -> {"verses": [...]}.

    Kept in a separate top-level section from `accepted`, which is specifically
    about BLOCKING findings. Nothing here ever fails a build; this section only
    decides what gets printed.
    """
    path = Path(__file__).resolve().parent / "known-issues.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh).get("heuristics", {})


def allowlist() -> dict:
    path = Path(__file__).resolve().parent / "allowlist.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh).get("scripts", {})


def editions() -> list[Path]:
    return sorted(TRANSLATIONS.glob("*.json"))


# --------------------------------------------------------------------------
# Version manifest
# --------------------------------------------------------------------------

# Why this file exists: the app caches each whole-Quran blob in AsyncStorage
# cache-first and forever, with no expiry. Before versions.json there was no
# way to tell a phone that a file it already holds has been corrected, so a
# reader kept a stale copy indefinitely (quranwise#73).
#
# The token is a hash of the file's bytes, NOT a commit sha. Two reasons.
# A commit sha for the file could only be known after committing it, which
# would force every data change into two commits and leave the first one
# failing CI. And a repo-wide sha would change whenever anything at all
# changed, invalidating all 46 editions over a README edit. A content hash
# changes exactly when that one file's bytes change, which is the property
# the cache actually needs.


# Extensions the app actually fetches. `.txt` is here for the Quranic Arabic
# Corpus export (morphology/quran-morphology-corpus.txt), which is a tab-
# separated text file rather than JSON -- it was invisible to the manifest
# while this only globbed *.json, which would have left it the one dataset
# that could never be revalidated. Documentation (*.md) stays out: the app
# never fetches it, and hashing it would churn the manifest for prose edits.
DATA_SUFFIXES = (".json", ".txt")


def data_files() -> list[Path]:
    """Every file the app fetches, relative order stable for a stable manifest."""
    found: list[Path] = []
    for name in DATA_DIRS:
        directory = REPO / name
        if directory.is_dir():
            found.extend(
                sorted(
                    path
                    for path in directory.rglob("*")
                    if path.is_file() and path.suffix in DATA_SUFFIXES
                )
            )
    return found


def content_version(path: Path) -> str:
    """Short content hash. Hashed from bytes, so it is blind to formatting."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def build_versions() -> dict:
    return {
        str(path.relative_to(REPO)): content_version(path)
        for path in data_files()
    }


def write_versions(versions: dict) -> None:
    """Written sorted and newline-terminated so regenerating is a no-op diff.

    Deliberately carries no timestamp or generator field: anything that
    changes on every run would defeat the CI check that regenerates this file
    and fails on a diff.
    """
    with VERSIONS.open("w", encoding="utf-8") as fh:
        json.dump(versions, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def read_versions() -> dict:
    if not VERSIONS.exists():
        return {}
    with VERSIONS.open(encoding="utf-8") as fh:
        return json.load(fh)
