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
