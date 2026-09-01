# quranwise-translations

Quran translation text used by the [Quranwise](https://github.com/Mohammedbilal786/quranwise) app, served via [jsdelivr](https://www.jsdelivr.com/) from this repo since jsdelivr can't serve files from a private repo.

## Source

All files are sourced from [QUL — Quranic Universal Library](https://qul.tarteel.ai/resources/translation) (Tarteel AI), `simple.json` export format.

## Format

Each file is a flat map of every ayah in the Quran, keyed `"<surah>:<ayah>"`:

```json
{
  "1:1": { "t": "In the name of Allāh, the Entirely Merciful, the Especially Merciful." },
  "1:2": { "t": "[All] praise is [due] to Allāh, Lord of the worlds -" }
}
```

Every translation file carries all 6,236 ayahs, with one documented exception:
`ku-amin` has 6,235, because 108:3 is absent from
[its QUL source](https://qul.tarteel.ai/resources/translation/144) itself.

## Validation

`tools/` holds the conversion and validation pass — a completeness check against
the canonical 6,236 keys, normalisation of invisible export residue, Unicode NFC
composition, and script checks that flag stray characters. Run it before adding
or replacing any file:

```sh
python3 tools/qwt.py check                             # validate every edition
python3 tools/qwt.py convert <export.json> <edition>   # QUL export -> repo file
```

CI runs `check` on every push. See [tools/README.md](tools/README.md) for what
each check covers and, importantly, which characters must never be stripped.

## `versions.json`

A manifest mapping every file the app fetches to a short hash of its contents:

```json
{ "translations/ku-amin.json": "8d2f1a0c7b45" }
```

The app caches each whole-Quran blob on the device permanently, so without
this there is no way to tell a phone that a file it already holds has been
corrected — it would serve the stale copy forever (quranwise#73). The app
reads this manifest, compares it against what it cached, and re-fetches only
the files whose hash moved.

**Regenerate it in the same commit as any data change**, or readers who
already cached that file will never see the fix:

```sh
python3 tools/qwt.py versions
```

CI runs `versions --check` and fails the build if it is out of date.

## Licensing

Licensing varies per translation — see [QUL's translations page](https://qul.tarteel.ai/resources/translation) for the license note on each individual resource before adding more files here. Translations explicitly marked "© copyrighted" on that page are not included.

## Files

| File | Language | Translator |
|---|---|---|
| `translations/en-sahih.json` | English | Saheeh International |
| `translations/de-bubenheim.json` | German | Frank Bubenheim and Nadeem |
| `translations/ru-kuliev.json` | Russian | Elmir Kuliev |
| `translations/zh-majian.json` | Chinese (Simplified) | Ma Jian |
| `translations/ur-jalandhry.json` | Urdu | Fatah Muhammad Jalandhari |

## `topics/topics.json`

Quranic topics/concepts data, sourced from [QUL's Ayah Topics resource](https://qul.tarteel.ai/resources/ayah-topics/45) — a structured concept graph (topic names, Ontology/Thematic/General categorization, parent/child hierarchy, and which ayahs belong to each topic), not translated prose. Converted from QUL's downloadable SQLite export; the `description`/`wiki_link`/`related_topics` columns were deliberately dropped (short encyclopedic text with unclear sourcing/licensing, and not needed for a "browse by theme" feature). Topics with zero associated ayahs (pure category nodes) are also excluded.

Flat array, each entry:

```json
{
  "id": 1,
  "name": "Allah",
  "arabicName": "الله",
  "thematic": true,
  "ontology": true,
  "parentId": null,
  "thematicParentId": 1837,
  "ontologyParentId": null,
  "ayahs": ["1:1", "1:2", "2:255", "..."]
}
```

## `morphology/morphology.json`

Word-level meaning and root data, sourced from QUL's [English Word by Word Translation](https://qul.tarteel.ai/resources/translation/92) (gloss per word) and [Word root](https://qul.tarteel.ai/resources/morphology/76) (root letters + transliteration per word) resources — both from the Quranic Arabic Corpus (Kais Dukes), the same open academic linguistic-annotation project as `topics/topics.json`'s Ontology data. No Arabic word text is included here: the app splits its own already-displayed Arabic text into words and joins by position, so this file only needs to carry the per-word English gloss and, where the word has one, its root.

Flat map keyed `"<surah>:<ayah>"`, each value an array ordered by word position (1-based, implicit from array index) — the trailing ayah-number marker QUL's export includes as an extra "word" is stripped:

```json
{
  "73:4": [
    { "meaning": "Or" },
    { "meaning": "add", "root": "ز ي د", "rootTranslit": "zyd" },
    { "meaning": "to it" },
    { "meaning": "and recite", "root": "ر ت ل", "rootTranslit": "rtl" },
    { "meaning": "the Quran", "root": "ق ر ا", "rootTranslit": "qrA" },
    { "meaning": "(with) measured rhythmic recitation", "root": "ر ت ل", "rootTranslit": "rtl" }
  ]
}
```

Words with no root (particles, pronouns — about 39% of all words) simply omit `root`/`rootTranslit`.

## `similar-ayahs/similar-ayahs.json`

Related/similar-ayah data, sourced from QUL's [Similar Ayah](https://qul.tarteel.ai/resources/similar-ayah/74) resource — QUL's own computed word-overlap metric between ayah pairs (not translated prose, not even a named external corpus, just numeric relationships between ayah references).

The source data is directional and asymmetric (e.g. `1:1 → 27:30` scores 80, but the reverse `27:30 → 1:1` scores 50 — score is relative to the matched ayah's own length). Merged into one per-ayah view: for each ayah, combined the rows where it's the source (preferred when both directions exist for the same pair) with rows where it's only the target (deduped), sorted by score descending.

Flat map keyed `"<surah>:<ayah>"`, each value an array of related ayahs:

```json
{
  "1:1": [
    { "ayah": "27:30", "score": 80, "matchedWords": 4, "coverage": 50 },
    { "ayah": "59:22", "score": 56, "matchedWords": 2, "coverage": 15 },
    { "ayah": "1:3", "score": 50, "matchedWords": 2, "coverage": 100 },
    { "ayah": "41:2", "score": 50, "matchedWords": 2, "coverage": 50 }
  ]
}
```

Only the 1,644 ayahs (of 6,236) with at least one match are present.

## `quran-script/digital-khatt-indopak.json`

Indo-Pak Qur'an script text, sourced from QUL's [Digital Khatt Indopak Script - Word by Word](https://qul.tarteel.ai/resources/quran-script/565) resource. Replaces the app's previous Indo-Pak script source (a `fawazahmed0/quran-api` edition rendered in Noto Naskh Arabic, resolved in issue #21/#14) — a full replacement, not an addition, per an explicit call by the app owner after weighing both.

The raw export is word-by-word, keyed `"<surah>:<ayah>:<word>"`; converted here into one flat map keyed `"<surah>:<ayah>"`, each value the full ayah text with all its words joined by a single space in word order (matching this repo's other per-ayah files, and analogous to how `mushaf-layout/words-indopak-nastaleeq.json` above resolves its own word ranges). The trailing ayah-end marker QUL includes as the ayah's last "word" (e.g. `۝٢٨٦ࣖ` — the end-of-ayah glyph plus the ayah's own Arabic-Indic numeral and, where present, a ruku/waqf mark) is kept as authentic to the source and to real Indo-Pak Mushaf print convention, not stripped — the app's own separate ayah-number badge UI is additional context, not a replacement for it. One ayah (1:7) had a stray U+202E (right-to-left override, a zero-width bidi control code, not a visible glyph) in its raw export; stripped during conversion as noise, not data loss — no font renders a glyph for it regardless.

```json
{
  "1:1": "بِسْمِ اللّٰهِ الرَّحْمٰنِ الرَّحِيْمِ ۝"
}
```

All 114 surahs / 6,236 ayahs present and verified against the standard per-surah ayah-count table — no gaps, no extras.

**Licensing note — the FONT is confirmed clean; this file's TEXT is not.** These are two separate questions and they have different answers. Corrected 2026-08-31 — this note previously read "confirmed clean, not an exception" and was about the font throughout, which let it be read as a green light for the data. It was not one.

**Font — clean.** The companion font (`font/568`, see the [quranwise](https://github.com/Mohammedbilal786/quranwise) app repo's bundled `.otf`) is DigitalKhatt's Indopak font, `github.com/DigitalKhatt/indopakfont` — confirmed OFL-1.1 via the GitHub repo's own license metadata *and* the font file's own embedded OFL name-table entries, sponsored directly by Tarteel AI (QUL's own creator). Glyph coverage of the font against every character actually used in this file's text was verified via fontTools against the full dataset (not a spot check): 84/85 unique characters resolve, the one non-match being the U+202E control code described above (inherently glyph-less in any font, not a coverage gap).

**Text — ambiguous silence, same risk class as the resources below.** That OFL grant reaches the font and nothing else: `DigitalKhatt/indopakfont` ships font sources only (`indopak.mp`, `glyphs.mp`, `features.fea`, the C++ build) and contains no Qur'an text corpus, so it cannot be the licence for this wording. Checked for terms on the data itself and found none anywhere:

- [The resource page](https://qul.tarteel.ai/resources/quran-script/565) carries no copyright marker, no licence statement and no attribution note — grepping the raw 62 KB page for `copyright`/`licen[cs]e`/`permission`/`rights`/`©` returns zero occurrences. The `quran-script` category listing carries no category-level statement either.
- The downloaded JSON has no metadata or licence field — all 6,236 keys are `"<surah>:<ayah>"`; grep of the raw 1.48 MB for `licen[cs]e|copyright|tanzil|ofl|attribution` returns zero hits.
- QUL's [Credits](https://qul.tarteel.ai/credits) names Dr. Amin Anane "For developing and providing the DigitalKhatt fonts" — the fonts, not this compilation, which is credited to nobody. The same page states that "the majority of the resources currently available in QUL were created or curated by the community, not Tarteel."
- QUL's [FAQ](https://qul.tarteel.ai/faq) says to "review the licensing information provided by each resource's author before use" — the author published none, and its commercial-use answer is conditional on exactly that review.
- `TarteelAI/quranic-universal-library` is MIT, which covers the platform code and not resource content.

Provenance could not be established: no stated derivation from Tanzil or any named corpus. (The wording is empirically the standard text — 98.4% identical consonantal skeleton to `quran-script/59` once hamza encoding is normalised — but that is what any faithful edition looks like, so it identifies no rights holder.)

This is prose-like content, which under the app repo's standing rule means ambiguous silence blocks rather than permits. Note it is **not** covered by a recorded owner exception the way `transliteration/transliteration-tajweed.json` (#30) and the `mushaf-layout/` files are: no such decision was ever made for it, because it was published on the strength of the licensing note above at a time when that note only established the font. It is live now; whether to treat it as a further one-time exception, or otherwise, is an open call for the app owner. `quran-script/565` has been added to the outstanding Tarteel AI/QUL permission ask being pursued for issue #30, rather than tracked separately.

## `mushaf-layout/`

Print-accurate Mushaf page/line layout data, sourced from QUL's [Mushaf Layouts](https://qul.tarteel.ai/resources/mushaf-layout) resources — powers a real page-for-page Indo-Pak reading mode (16-liner and 13-liner) rather than plain reflowed text.

- `mushaf-layout/indopak-16-lines-taj.json` — [Indopak 16 lines layout (Taj company)](https://qul.tarteel.ai/resources/mushaf-layout/11), 548 pages.
- `mushaf-layout/indopak-13-lines-taj.json` — [Indopak 13 lines layout (Taj company)](https://qul.tarteel.ai/resources/mushaf-layout/313), 847 pages.
- `mushaf-layout/words-indopak-nastaleeq.json` — [Indopak Nastaleeq script - Word by Word](https://qul.tarteel.ai/resources/quran-script/59), the per-word glyph text both layouts above reference by word ID (shared, since both layouts use the same `indopak-nastaleeq` font/script).

Converted from QUL's downloadable SQLite exports, grouped by page at conversion time rather than shipping the raw per-line table. Layout files:

```json
{
  "info": { "linesPerPage": 16, "numberOfPages": 548, "fontName": "indopak-nastaleeq", "surahStartPages": { "1": 1, "2": 2 } },
  "pages": [
    [
      { "type": "surah_name", "centered": true, "surahNumber": 1 },
      { "type": "ayah", "centered": true, "firstWordId": 1, "lastWordId": 5 }
    ]
  ]
}
```

`pages[i]` is page `i+1`'s lines, in reading order. `type` is `surah_name` | `basmallah` | `ayah`; only `ayah` lines carry a word-ID range (resolved against `words-indopak-nastaleeq.json`), only `surah_name` lines carry `surahNumber`. `centered` distinguishes center- vs justify-alignment for that line — this is QUL's own documented rendering algorithm (`qul.tarteel.ai/docs/mushaf-layout`), not a reinterpretation.

The words file de-duplicates the per-word `"surah:ayah"` key QUL's export repeats on every word of the same ayah:

```json
{
  "words": ["بِسْمِ", "اللّٰهِ", "الرَّحْمٰنِ", "الرَّحِیْمِ", "۟"],
  "ayahBoundaries": [{ "key": "1:1", "start": 1 }, { "key": "1:2", "start": 6 }]
}
```

`words[i]` is word ID `i+1`'s text (word IDs are a single running index across the whole Quran, matching the layout files' `firstWordId`/`lastWordId`, per QUL's schema — not scoped per-ayah). `ayahBoundaries` gives the first word ID of each ayah, in order; the last ID belonging to an ayah is the entry before the next boundary (or the final word ID for 114:6). 83,668 words total, 6,236 ayah boundaries — full-Quran coverage confirmed (every layout file's highest referenced word ID is exactly 83,668, matching this file's word count).

**Licensing note:** none of these three resources carry QUL's `"This resource is © copyrighted."` marker on their detail or category pages, but there's no explicit redistribution grant either — the same ambiguous-silence situation as `transliteration/transliteration-tajweed.json` below. Two of the three (the layout files) are page/line geometry and numeric word-ID ranges with no Qur'an wording in them at all — arguably closer to the lower-risk structural/computed class (`topics.json`/`morphology.json`/`similar-ayahs.json`) than to prose. The third (the word-by-word script text) does contain the Qur'an's actual wording, so it's treated at the same risk level as the transliteration file. **All three hosted here as a deliberate, explicit, one-time exception made directly by the app owner**, each confirmed individually as it was discovered rather than assumed to be covered by a blanket instruction — not a change to the standing rule for this repo. The corresponding font (`Indopak Nastaleeq font`, [qul.tarteel.ai/resources/font/242](https://qul.tarteel.ai/resources/font/242)) needed to render ~8.3% of the word data (private-use-area glyphs with no meaning in any other font) is under the same one-time exception, but is bundled directly in the [quranwise](https://github.com/Mohammedbilal786/quranwise) app repo rather than here, since it's a fixed compile-time asset rather than fetched bulk content.

## `transliteration/transliteration-tajweed.json`

Tajweed-enhanced Latin transliteration, sourced from QUL's [English Transliteration(Tajweed)](https://qul.tarteel.ai/resources/transliteration/469) resource. This is a distinct edition from the app's default transliteration (a separate, non-QUL source, `src/api/quran.ts`'s `fetchSurahTransliteration`) — the "tajweed enhancement" here is baked into the respelling itself (reflecting connected-recitation pronunciation: hamzat-ul-wasl elision, idgham/assimilation across word boundaries, etc.), not a colour/markup annotation layer, so no bracket-tag parsing is needed to use it.

**Licensing note:** checked QUL's own copyright marker (`"This resource is © copyrighted."`, shown on some individual translation resources) on both this resource's detail page and its category listing — absent for this one. No named author/attribution for this specific resource on QUL's Credits page either. That's ambiguous silence, not a confirmed-clear finding — this content is prose-like (a full text rendering of the Qur'an's wording), the same risk class as a translation edition, not the lower-risk structural/computed data category (`topics.json`/`morphology.json`/`similar-ayahs.json`). **Hosted here as a deliberate, explicit, one-time exception made directly by the app owner**, who is personally pursuing redistribution permission from Tarteel AI/QUL afterward — this is not a change to the standing rule for this repo (verify license before hosting; default to mechanism-only on ambiguous silence for prose-like content). Future additions still follow that standing rule.

Flat map keyed `"<surah>:<ayah>"` → string, all 6,236 ayahs:

```json
{
  "1:1": "Bismil laahir Rahmaanir Raheem"
}
```
