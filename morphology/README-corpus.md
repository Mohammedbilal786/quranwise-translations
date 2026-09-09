# quran-morphology-corpus.txt — the Quranic Arabic Corpus

A **verbatim** copy of the Quranic Arabic Corpus morphology export (Kais Dukes,
<http://corpus.quran.com>), mirrored here so the app does not depend on a
third-party repository at runtime.

Mirrored from <https://github.com/mustafa0x/quran-morphology> (itself a mirror of
the file corpus.quran.com's own download page distributes), 2026-09-09.
SHA-256 of the copy in this directory is recorded below; the file is byte-identical
to what was fetched and has not been edited.

## Licence and required attribution

The corpus is distributed under the GNU General Public License. Its terms state:

> Permission is granted to copy and distribute verbatim copies of this file, but
> changing it is not allowed. This annotation can be used in any website or
> application, provided its source (the Quranic Arabic Corpus) is clearly
> indicated, and a link is made to http://corpus.quran.com

Accordingly:

- This file is redistributed **verbatim** and must not be edited in place. If a
  correction is ever needed, take it up with the upstream corpus rather than
  patching the copy here.
- Any surface that shows this data must credit **the Quranic Arabic Corpus** and
  link to <http://corpus.quran.com>.

## Format

One segment per line, tab-separated:

    surah:ayah:word:segment <TAB> arabic <TAB> POS <TAB> tags

`tags` is a `|`-delimited mix of bare flags (`GEN`, `ACT_PCPL`, …) and key:value
pairs (`ROOT:`, `LEM:`, `VF:`, `MOOD:`, `FAM:`). A single word may span several
segments (prefix + stem + suffix), all sharing one `surah:ayah:word`.

**Note for consumers:** a bare `P` tag is ambiguous by position — on a particle
(`POS = P`) it means *preposition*; on a noun (`POS = N`) it means *plural*.
Decoding it without checking the POS column mislabels every preposition in the
Quran (12,992 segments).

    SHA-256: 742bfac59941b2cb09736d5b7aae694af50792261fb8450cbf6afafcc340645f
