"""The ``witness`` command line: turn a recording into tests, or inspect it."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from . import check as check_mod
from . import generate as gen
from . import store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="witness",
        description="Generate committable, proof-carrying tests from a real run.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="emit pytest files from a recording")
    g.add_argument("--dir", default=".witness", help="recording directory")
    g.add_argument("--out", default="tests", help="where to write test files")

    s = sub.add_parser("status", help="show what was certified and what was refused")
    s.add_argument("--dir", default=".witness", help="recording directory")

    c = sub.add_parser(
        "check", help="diff a recording against the current code (exits 1 on changes)"
    )
    c.add_argument("--dir", default=".witness", help="recording directory")

    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            return _generate(args.dir, args.out)
        if args.command == "status":
            return _status(args.dir)
        if args.command == "check":
            return _check(args.dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"witness: {exc}", file=sys.stderr)
        return 1
    return 0


def _generate(recording_dir: str, out_dir: str) -> int:
    recording = store.load(recording_dir)
    result = gen.generate(recording.capsules)

    if not result.files:
        print("witness: no top-level function calls to generate tests from.")
        if recording.refusals:
            print(
                f"  ({len(recording.refusals)} call(s) refused — "
                f"`witness status` shows why)"
            )
        return 0

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, source in result.files.items():
        (out / name).write_text(source)
        print(f"  wrote {out / name}")

    print(
        f"witness: generated {result.test_count} test(s) "
        f"in {len(result.files)} file(s)."
    )
    if result.skipped:
        uniq = sorted(set(result.skipped))
        print(
            f"  skipped {len(uniq)} non-top-level target(s) "
            f"(methods/nested/lambdas): {', '.join(uniq)}"
        )
    if recording.refusals:
        print(
            f"  {len(recording.refusals)} call(s) refused (not reproducible) — "
            f"`witness status` for reasons."
        )
    return 0


def _status(recording_dir: str) -> int:
    recording = store.load(recording_dir)
    certified = Counter(c.func for c in recording.capsules)
    print(
        f"Recording: {len(recording.capsules)} certified capsule(s), "
        f"{len(recording.refusals)} refusal(s)."
    )
    if certified:
        print("\nCertified:")
        for func, count in sorted(certified.items()):
            print(f"  {count:>4}  {func}")
    if recording.refusals:
        print("\nRefused (witness won't assert what it can't reproduce):")
        reasons = Counter((r.qualname, r.reason) for r in recording.refusals)
        for (qualname, reason), count in sorted(reasons.items()):
            suffix = f" (x{count})" if count > 1 else ""
            print(f"  {qualname}: {reason}{suffix}")
    return 0


def _check(recording_dir: str) -> int:
    recording = store.load(recording_dir)
    result = check_mod.check(recording)
    total = result.unchanged + len(result.changed)
    print(
        f"Checking {total} recorded behavior(s) in '{recording_dir}' "
        f"against the current code:"
    )
    print(f"  ✓ {result.unchanged} unchanged")
    if result.changed:
        print(f"  ✗ {len(result.changed)} changed:")
        for d in result.changed:
            print(f"      {d.call}:  {d.before}  →  {d.after}")
    if result.uncheckable:
        print(f"  ⚠ {len(result.uncheckable)} could not be checked:")
        for qualified, why in result.uncheckable:
            print(f"      {qualified}: {why}")
    # Exit non-zero when behavior changed, so `witness check` works as a CI gate.
    return 1 if result.changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
