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
MOJIBAKE = re.compile("[\u00c3\u00c2\u00e2][\u0080-\u009f\u00ad]")

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
    # pl-bielawski is the one edition this applies to today.
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


def normalise_edition(data: dict, name: str | None = None) -> tuple[dict, int]:
    """Normalise every verse. Returns the new map and the count of changed verses.

    `name` selects the edition's STRIPPABLE_CONTROLS entry; without it no control
    byte is stripped, so callers that do not know the edition stay conservative.
    """
    strippable = STRIPPABLE_CONTROLS.get(name or "", frozenset())
    out, changed = {}, 0
    for key, value in data.items():
        text = value["t"]
        fixed = normalise_text(text, strip_controls=key in strippable)
        if fixed != text:
            changed += 1
        out[key] = {"t": fixed}
    return out, changed


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


def data_files() -> list[Path]:
    """Every file the app fetches, relative order stable for a stable manifest."""
    found: list[Path] = []
    for name in DATA_DIRS:
        directory = REPO / name
        if directory.is_dir():
            found.extend(sorted(directory.rglob("*.json")))
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
