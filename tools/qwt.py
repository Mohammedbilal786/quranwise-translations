#!/usr/bin/env python3
"""Command line for the translation data checks.

    python3 tools/qwt.py check                 # report on every edition
    python3 tools/qwt.py check ku-amin fa-taji # ...or just these
    python3 tools/qwt.py normalise             # apply the mechanical fixes
    python3 tools/qwt.py normalise --dry-run   # ...show what would change
    python3 tools/qwt.py convert <in.json> <edition>   # QUL export -> repo file

`check` exits non-zero on any new blocker-severity finding, which is what
makes it usable from CI; --strict also fails on the known backlog. `convert`
refuses to write on a blocker.

Needs nothing but the standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qwtrans as Q

SEVERITY_ORDER = {"blocker": 0, "review": 1, "normalised": 2}
MARK = {"blocker": "FAIL", "review": "WARN", "normalised": "OK  "}


def _selected(names: list[str]) -> list[Path]:
    if not names:
        return Q.editions()
    picked = []
    for name in names:
        path = Q.TRANSLATIONS / f"{name.removesuffix('.json')}.json"
        if not path.exists():
            sys.exit(f"no such edition: {path.name}")
        picked.append(path)
    return picked


def _verse_summary(verses: list[str], limit: int = 12) -> str:
    shown = ", ".join(verses[:limit])
    if len(verses) > limit:
        shown += f", ... (+{len(verses) - limit} more)"
    return shown


# --------------------------------------------------------------------------

def cmd_check(args) -> int:
    allow = Q.allowlist()
    baseline = {} if args.strict else Q.known_issues()
    blockers = reviews = accepted = 0
    clean: list[str] = []

    for path in _selected(args.editions):
        name = path.stem
        data = Q.load(path)
        allowed = allow.get(name, {}).get("allow", [])
        findings = Q.check_edition(name, data, allowed)

        if not findings:
            clean.append(name)
            continue

        findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.check))
        print(f"\n{name}  ({len(data)} verses)")
        for f in findings:
            # A blocker counts against the build only where it is new: a verse
            # not already recorded in the baseline for this edition and check.
            known = set(baseline.get(name, {}).get(f.check, {}).get("verses", []))
            new_verses = [v for v in f.verses if v not in known]
            if f.severity == "blocker":
                if new_verses:
                    blockers += 1
                else:
                    accepted += 1
            elif f.severity == "review":
                reviews += 1
            mark = MARK[f.severity]
            if f.severity == "blocker" and not new_verses:
                mark = "KNOWN"
            print(f"  {mark}  {f.check}  [{f.count}]")
            if f.detail:
                print(f"        {f.detail}")
            print(f"        {_verse_summary(f.verses)}")

    print()
    print(f"{len(clean)} clean, {blockers} new blocking finding(s), "
          f"{accepted} accepted in the baseline, {reviews} needing review")
    if clean and args.verbose:
        print("clean: " + ", ".join(clean))
    if blockers:
        print("\nNew blocking findings need a fresh export from QUL or a content")
        print("decision; they are never auto-repaired. See tools/README.md.")
    if accepted and not args.strict:
        print("\nFindings marked KNOWN are recorded in tools/known-issues.json.")
        print("Run with --strict to fail on those too.")
    return 1 if blockers else 0


def cmd_normalise(args) -> int:
    total_files = total_verses = 0

    for path in _selected(args.editions):
        data = Q.load(path)
        fixed, changed = Q.normalise_edition(data)
        if not changed:
            continue
        total_files += 1
        total_verses += changed
        print(f"{path.stem:20} {changed:5} verse(s) normalised")
        if not args.dry_run:
            Q.dump(path, fixed)

    verb = "would change" if args.dry_run else "changed"
    print(f"\n{verb} {total_verses} verse(s) across {total_files} edition(s)")
    if args.dry_run:
        print("(dry run -- nothing written)")
    return 0


def cmd_convert(args) -> int:
    """Convert a QUL `simple.json` export into this repo's file shape.

    QUL gates every download behind sign-in and offers no API, so the export has
    to be downloaded by hand first; this takes the file from disk.
    """
    source = Path(args.source)
    raw = json.loads(source.read_text(encoding="utf-8"))

    # QUL ships either a flat {"1:1": "text"} map or a nested per-surah array.
    if isinstance(raw, dict):
        data = {k: {"t": v["t"] if isinstance(v, dict) else v} for k, v in raw.items()}
    elif isinstance(raw, list):
        data = {}
        for surah_index, verses in enumerate(raw, start=1):
            for ayah_index, text in enumerate(verses, start=1):
                data[f"{surah_index}:{ayah_index}"] = {"t": text}
    else:
        sys.exit("unrecognised export shape: expected an object or an array")

    data, changed = Q.normalise_edition(data)
    print(f"normalised {changed} verse(s) on import")

    allow = Q.allowlist().get(args.edition, {}).get("allow", [])
    findings = Q.check_edition(args.edition, data, allow)
    blocking = [f for f in findings if f.severity == "blocker"]

    for f in sorted(findings, key=lambda f: SEVERITY_ORDER[f.severity]):
        print(f"  {MARK[f.severity]}  {f.check}  [{f.count}]  {f.detail}")
        print(f"        {_verse_summary(f.verses)}")

    if blocking and not args.force:
        print("\nRefusing to write: fix the blocking findings at the source, or")
        print("pass --force if the gap is genuinely upstream and documented.")
        return 1

    target = Q.TRANSLATIONS / f"{args.edition}.json"
    Q.dump(target, data)
    print(f"\nwrote {target.relative_to(Q.REPO)}  ({len(data)} verses)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="qwt.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="report defects across the editions")
    p.add_argument("editions", nargs="*", help="edition names; default is all of them")
    p.add_argument("-v", "--verbose", action="store_true", help="also list the clean editions")
    p.add_argument("--strict", action="store_true",
                   help="ignore tools/known-issues.json and fail on the whole backlog")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("normalise", help="apply the mechanical fixes in place")
    p.add_argument("editions", nargs="*")
    p.add_argument("-n", "--dry-run", action="store_true")
    p.set_defaults(fn=cmd_normalise)

    p = sub.add_parser("convert", help="QUL simple.json export -> repo file")
    p.add_argument("source", help="path to the downloaded QUL export")
    p.add_argument("edition", help="edition name, e.g. ku-amin")
    p.add_argument("--force", action="store_true",
                   help="write even with blocking findings (documented upstream gaps only)")
    p.set_defaults(fn=cmd_convert)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
