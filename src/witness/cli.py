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
    c.add_argument(
        "--strict",
        action="store_true",
        help="also fail (exit 1) on type/shape drift, not just value changes",
    )

    r = sub.add_parser("run", help="run a script with witness recording enabled (no code edits)")
    r.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="MODULE",
        help="module to auto-instrument (repeatable)",
    )
    r.add_argument("--dir", default=".witness", help="recording directory")
    r.add_argument("--samples", type=int, default=None, help="re-invocations per call")
    r.add_argument("script", help="path to the script to run")
    r.add_argument("script_args", nargs=argparse.REMAINDER, help="arguments passed to the script")

    args = parser.parse_args(argv)
    # `run` executes user code, so its exceptions (and the script's own) must surface
    # normally rather than be caught and relabelled as witness errors.
    if args.command == "run":
        return _run(args.target, args.script, args.script_args, args.dir, args.samples)
    try:
        if args.command == "generate":
            return _generate(args.dir, args.out)
        if args.command == "status":
            return _status(args.dir)
        if args.command == "check":
            return _check(args.dir, args.strict)
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
            print(f"  ({len(recording.refusals)} call(s) refused — `witness status` shows why)")
        return 0

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, source in result.files.items():
        (out / name).write_text(source)
        print(f"  wrote {out / name}")

    print(f"witness: generated {result.test_count} test(s) in {len(result.files)} file(s).")
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


def _check(recording_dir: str, strict: bool = False) -> int:
    recording = store.load(recording_dir)
    result = check_mod.check(recording)
    total = result.unchanged + len(result.changed) + len(result.drifted)
    print(f"Checking {total} recorded behavior(s) in '{recording_dir}' against the current code:")
    print(f"  ✓ {result.unchanged} unchanged")
    if result.changed:
        print(f"  ✗ {len(result.changed)} changed:")
        for d in result.changed:
            print(f"      {d.call}:  {d.before}  →  {d.after}")
    if result.drifted:
        note = "" if strict else " (tests still pass; use --strict to fail on these)"
        print(f"  ⧗ {len(result.drifted)} drifted — same value, different type/shape{note}:")
        for d in result.drifted:
            print(f"      {d.call}:  {d.before}  →  {d.after}")
    if result.uncheckable:
        print(f"  ⚠ {len(result.uncheckable)} could not be checked:")
        for qualified, why in result.uncheckable:
            print(f"      {qualified}: {why}")
    # Exit non-zero when behavior changed (and, with --strict, on drift too), so
    # `witness check` works as a CI gate. Drift alone is consistent with `==`, so by
    # default it's informational and doesn't fail.
    failed = bool(result.changed) or (strict and bool(result.drifted))
    return 1 if failed else 0


def _run(
    targets: list[str],
    script: str,
    script_args: list[str],
    recording_dir: str,
    samples: int | None,
) -> int:
    import runpy
    import sys

    from . import recording

    if not targets:
        print(
            "witness: pass at least one --target MODULE to instrument (nothing to "
            "record otherwise).",
            file=sys.stderr,
        )
        return 1

    # Make the script's own directory importable, like `python script.py` does.
    script_dir = str(Path(script).resolve().parent)
    sys.path.insert(0, script_dir)
    saved_argv = sys.argv
    sys.argv = [script, *script_args]
    try:
        with recording(recording_dir, samples=samples, targets=targets) as session:
            runpy.run_path(script, run_name="__main__")
    except (ImportError, AttributeError) as exc:
        print(f"witness: could not instrument a --target: {exc}", file=sys.stderr)
        return 1
    finally:
        sys.argv = saved_argv
        try:
            sys.path.remove(script_dir)
        except ValueError:
            pass

    if not session.capsules and not session.refusals:
        print(
            "witness: recorded nothing. Make sure --target names a module your "
            "script imports and calls through the module (functions defined in the "
            "script's own __main__ aren't captured).",
            file=sys.stderr,
        )
        return 1
    print(f"witness: recorded to '{recording_dir}' — run `witness generate` or `witness check`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
