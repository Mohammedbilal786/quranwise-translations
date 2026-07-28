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
