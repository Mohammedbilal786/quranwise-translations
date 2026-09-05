# Translation data checks

Everything under `translations/` is a flat map of all 6,236 ayahs, keyed
`"<surah>:<ayah>"` → `{"t": text}` — QUL's `simple.json` export shape. Until now
nothing checked that the shape held. Two defects found by hand in August 2026
([#71], [#72]) turned out to be two of many:

- `ku-amin` was missing 108:3 entirely, and had been since it was added
- `ku-amin` carried 56 stray LRMs, two of which flipped a verse to LTR on Android
- `dv-maldives` carried 20 literal TABs and a Latin `s` inside a Thaana word
- `ku-amin` carried 3 stray `U+009D` control bytes, present in QUL's own resource

Running the same checks across all 46 editions flagged **25 of them**. This is
that pass, kept so the next edition doesn't repeat it.

## Usage

```sh
python3 tools/qwt.py check                    # report on every edition
python3 tools/qwt.py check ku-amin fa-taji    # ...or just these
python3 tools/qwt.py check --strict           # ...including the known backlog
python3 tools/qwt.py normalise --dry-run      # show the mechanical fixes
python3 tools/qwt.py normalise                # apply them
python3 tools/qwt.py convert <export.json> <edition>   # QUL export -> repo file
```

`check` exits non-zero on any *new* blocker-severity finding, which is what CI
runs. `convert` normalises on import and refuses to write if a blocker survives;
`--force` overrides that, and is for documented upstream gaps only.

### The baseline

Seven blocking findings already existed in the data when these checks were
written, across `ku-amin`, `ko-choi`, `pl-bielawski`, `ha-gumi` and `pt-elhayek`.
Two have since been repaired rather than accepted — `ku-amin`'s three stray
`U+009D` bytes and `ko-choi` 49:10 (both [#75]) — so `check` reports **five**
today. That number is meant to fall: it is the size of the backlog, not a
constant.

They are recorded verse by verse in `known-issues.json` so that CI fails on new
breakage rather than on the backlog it was added to expose.

That file is a baseline, not a suppression list. Every entry names real damage in
a shipped file and carries a `why`; delete entries as the files are fixed, and
run `check --strict` to see the whole picture at any time. Because verses are
listed explicitly, the same defect appearing in a *new* ayah still fails the
build — a stub added to `ha-gumi` 2:100 fails even though 27:55 is baselined.

Standard library only. `tools/scriptdata.py` is generated — see
[Regenerating the script tables](#regenerating-the-script-tables).

## The split that matters

**Normalise** covers mechanical, meaning-preserving defects. These are rewritten
in place, and the change reads as a diff.

**Report** covers anything that would change a word. A stray Latin `c` standing
in for a Cyrillic `с` is a typo in a scripture translation; guessing at the
intended character is a content edit, and belongs to a person with the source
open. The checker names it and stops.

### What gets normalised

| Fix | Why |
|---|---|
| Strip bidi controls — LRM, RLM, ALM, the embedding/override/isolate families | No role in prose that is uniformly one direction; `ku-amin` 78:14 and 78:37 opened with an LRM, which flips those verses to LTR on Android |
| Fold control whitespace (TAB, CR, LF, …) to a single space | Covered by no bundled font; `dv-maldives`, `sv-bernstrom` and `th-kfqc` all carried literal TABs mid-sentence |
| Strip soft hyphen and BOM-as-ZWNBSP | Invisible, and they break substring search and copy-paste |
| Trim leading and trailing whitespace | |
| Compose to NFC, cluster by cluster | The same word arrived from QUL in two different encodings across editions; composing makes search, comparison and diffing behave. Applied only where it will not reorder a mark — see below |
| Strip a C1 control byte, **only** for verses listed in `STRIPPABLE_CONTROLS` | Reviewed by hand and confirmed to be residue rather than half a mis-decoded character. `ku-amin` 33:36/33:39/33:40 (issue #75) |

#### NFC, but never reordering a mark

Composition is applied per base-plus-marks cluster, and any cluster where
canonical ordering would *move* a mark is left byte for byte as found.

That exception is not theoretical. Canonical ordering sorts combining marks by
combining class, and Arabic is not typed in that order: shadda (ccc 33) is
written before its vowel (ccc 27–32), so NFC swaps the pair. The two forms are
canonically equivalent, and HarfBuzz — Android, and this repo's own Arabic
script data — shapes them identically. **CoreText does not.** Rendering all
9,841 verses that strict NFC would touch, before and after, through CoreText at
the size the app uses:

| | verses NFC would change | render differently on CoreText |
|---|---:|---:|
| Composition only (applied) | 7,877 | **0** |
| Mark reordering (held back) | 1,964 | 1,948 |

The largest group is `dv-maldives`, where 1,920 verses carry ﷲ as
`ل + shadda + fatha`; reordering shifts the mark cluster off the lām ligature.
1:1 is among them. Holding these back also keeps the translations consistent
with `quran-script/` and `mushaf-layout/`, where shadda precedes its vowel in
21,260 places and follows it in none.

The held-back verses are reported by the `mark-order` check rather than being
silently skipped, so the remaining gap between these files and strict NFC stays
countable. Closing it is a rendering decision, not a mechanical one.

Two further things are deliberately **not** normalised, though they look like
they could be. Runs of ordinary spaces are left alone — 681 verses in `it-piccardo` are
double-spaced, which is cosmetic rather than a defect, and rewriting them would
bury the real fixes. NO-BREAK SPACE is left alone too: it is correct typography
before punctuation in French and Italian, and appears legitimately in seven
editions.

#### When a control byte can be stripped

`control-character` was originally report-only with no exceptions, on the
reasoning that a stray C1 byte is a decoding failure and deleting it would hide a
file that needs re-exporting. That reasoning holds most of the time and is still
the default. It does not hold when **there is no export that fixes it**.

`ku-amin` 33:36, 33:39 and 33:40 each carried one `U+009D`. Fetching those three
verses from QUL resource 144 returned strings identical to ours character for
character, `U+009D` included, at the same lengths (248 / 172 / 150). The source of
record already has the fault, so re-exporting can never remove it and there is no
evidence left to preserve by keeping it.

Stripping is allowed only where all of this holds, verified by reading the verses:

- **A fresh pull from the source shows the same byte**, so no re-export helps.
- **Position is consistent and inert.** All three sat second-to-last, between the
  final letter and the sentence-ending stop.
- **The surrounding words are complete.** `سه‌رلێشێواوه`, `بپرسێته‌وه` and `زانایه`
  are whole Kurdish words, not words missing a letter.
- **The byte is isolated**, not the tail of a `MOJIBAKE` pair. Double-encoded
  verses are still returned untouched by `normalise_text()`.

The gate is a per-verse allowlist, `STRIPPABLE_CONTROLS` in `tools/qwtrans.py`,
never a blanket rule — because a blanket rule would be wrong. `ko-choi` 49:10
carries an isolated `U+0098` that fails the bar: it sits beside a broken Latin
fragment, so the byte is a symptom of real corruption and deleting it would erase
the evidence. It stays reported and stays in the baseline.

Adding an entry is a content decision about scripture text. Read the verses, pull
them from the source, and record the reasoning — do not fold it into a routine
normalisation pass.

### What gets reported

| Check | Severity | Meaning |
|---|---|---|
| `missing-ayah` / `unknown-ayah` | blocker | Key set doesn't match the canonical 6,236 |
| `empty-text` | blocker | Verse present, no text |
| `non-prose-stub` | blocker | Value contains none of the edition's own scripts — `ha-gumi` 27:55 is the string `"49."` |
| `control-character` | blocker | A stray C1 byte, where the evidence does not support stripping it. Usually a decoding failure, and deleting it would hide a file that needs re-exporting — but see [When a control byte can be stripped](#when-a-control-byte-can-be-stripped) |
| `double-encoded-utf8` | blocker | UTF-8 bytes re-read as cp1252 — `pl-bielawski` has 11 such verses |
| `foreign-script` | review | A character from a script the edition doesn't use, almost always a homoglyph typo |
| `mark-script-mismatch` | review | A combining mark on a base script it is never used with — an Arabic fatha inside a Dutch word |
| `private-use` | review | Renders only in one specific font; tofu everywhere else |
| `mark-order` | review | Marks stored in an order canonical ordering would change. `normalise` leaves these alone on purpose — see [NFC, but never reordering a mark](#nfc-but-never-reordering-a-mark) |
| `pending-normalisation` | info | Mechanical residue a hand-edit reintroduced. Run `normalise` |

## The one thing that must never be stripped

`U+200C ZERO WIDTH NON-JOINER` and `U+200D ZERO WIDTH JOINER` share Unicode
category `Cf` with the bidi marks, so a naive "strip formatting characters" pass
takes them too. They are **orthography, not residue**: ZWNJ separates prefixes
and plural markers in Persian and Kurdish, ZWJ forms Malayalam chillu letters.

| Edition | ZWNJ | ZWJ |
|---|---:|---:|
| `ku-amin` | 124,737 | — |
| `ml-karakunnu` | 1 | 25,060 |
| `fa-taji` | 16,208 | — |
| `bn-zakaria` | 1,650 | 1 |

Stripping these would corrupt four editions far worse than any defect this tool
exists to fix. They are in `PROTECTED` and are never touched.

## How the script checks work

A character's script is resolved from generated tables rather than a regex
engine, so the tool needs nothing but the standard library:

- **Base letters** (Unicode category `L*`) map to a script. Punctuation, digits,
  spaces and symbols are script-neutral and never attributed — every edition
  uses ASCII punctuation and Latin digits. So are letters belonging to no single
  script: the Japanese prolonged sound mark, Arabic tatweel, and the modifier
  half-ring standing in for ʿayn in English transliteration.
- **Combining marks** (category `M*`) are judged against the base they sit on,
  using Unicode's Script_Extensions. A combining macron over a Latin vowel is
  fine; an Arabic fatha on the same vowel is not. This is what caught
  `nl-siregar` 44:37 and `tg-pioneers` 28:56.

A script present in fewer than 2% of an edition's verses is treated as
contamination rather than as part of its writing system. Across all 46 editions
that threshold produced exactly two false positives, both recorded in
`allowlist.json`: the honorific ﷺ in `en-sahih`, and a genuine Greek etymology
note in `it-piccardo` 35:45.

Keep that allowlist short, and only add to it after actually reading the verses.

## Known upstream gaps

`ku-amin` 108:3 is **absent from QUL resource 144 itself** — its own ayah-by-ayah
preview returns "Translation is not available for this ayah", while three other
Kurdish editions return 108:3 normally. Re-exporting will not fix it. Tracked in
[#71]; the file is 6,235 verses by necessity, not by conversion error.

`ku-amin` 33:36/33:39/33:40 carried a `U+009D` that is **also present in resource
144 itself** — the same upstream-defect shape, but recoverable, because the byte
carried no content. Stripped under the rule above and tracked in [#75].

`ko-choi` is corrupted upstream in a way no re-export fixes either. 49:10 carried
the four characters `\`, `x`, `C`, `U+0098` where one Hangul syllable belongs.
QUL resource 204, quran.com translation 219 and AlQuran.cloud `ko.korean` all
carry the same mangling, and a different Korean edition (quran.com 36) mangles
the same syllable differently — so the fault predates every published copy. It
was repaired editorially to `한 형제라`, by explicit owner decision, because the
word `형제` appears spelled correctly later in that very verse; see [#75].

The same corruption ran through six more verses, and those are repaired too.
Only TWO distinct byte pairs were involved, not seven separate faults, and the
corrupt pair is the true CP949 bytes with a constant −5 on the first byte:

| corrupt run | true CP949 | syllable | occurrences |
|---|---|---|---|
| `\xC` + `U+0098` | `c7fc` | `형` | 49:10 |
| `\xCg` | `c7df` | `했` | 30:55, 32:25, 33:7, 89:24 (×2) |
| `\xCD` | `c8eb` | `흙` | 16:59, 78:40 |

Because one systematic corruption produced all of them, identical runs must come
from identical source syllables — which is what made five occurrences of `\xCg`
one decision rather than five guesses. Each was independently confirmed by
grammar and sense: `했` is the past tense of 하다, demanded by 되곤 ___노라,
달리___던, 성약을 ___노라 and 선행을 ___어야 ___는데; `흙` is soil, demanded by
"bury it in the ground" (16:59) and "I wish I were dust" (78:40).

Reading the corrupt bytes as CP949 anyway yields `혱`, `헸` and `홁` — near
misses differing by one vowel, and `혱` is exactly what a different Korean
edition (quran.com 36) shows at 49:10. That is how the corruption is known to be
systematic rather than incidental.

Two verses still carry a stray trailing `q` (17:110, 33:18), a different
artifact and not repaired. `foreign-script` lists them.

## Regenerating the script tables

`tools/scriptdata.py` is generated from the `regex` module's Unicode database and
checked in so the tool itself has no dependencies. It only needs regenerating
when adding support for a script no edition currently uses:

```sh
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install regex
/tmp/venv/bin/python tools/genranges.py > tools/scriptdata.py
```

[#71]: https://github.com/Mohammedbilal786/quranwise/issues/71
[#72]: https://github.com/Mohammedbilal786/quranwise/issues/72

[#75]: https://github.com/Mohammedbilal786/quranwise/issues/75
