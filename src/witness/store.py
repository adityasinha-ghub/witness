"""Persist a recording to ``.witness/`` and load it back.

Layout::

    .witness/
      manifest.json     # capsules + refusals, referencing blobs by content hash
      blobs/<sha256>    # pickled value bytes, content-addressed (deduplicated)

The manifest is versioned: a mismatched ``format_version`` is refused on load
rather than silently mis-read, so stale recordings are re-recorded, not trusted.
A recording is one run — :func:`save` overwrites the manifest (blobs are additive
and content-addressed, so they simply accumulate the referenced set).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import matcher as matcher_mod
from .capsule import Capsule, PartialOutcome, RaiseOutcome, Refusal, ReturnOutcome
from .value import Encoded

# Bumped when the dependency-arg key algorithm changes (v2: canonical form;
# v3: canonical recursion into object state).
FORMAT_VERSION = 3


@dataclass
class Recording:
    """A loaded recording: everything certified, and everything refused."""

    capsules: list[Capsule]
    refusals: list[Refusal]


def save(session, path: str = ".witness") -> None:
    """Write a session's capsules and refusals to ``path``."""
    root = Path(path)
    blobs = root / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format_version": FORMAT_VERSION,
        "capsules": [_capsule_to_json(c, blobs) for c in session.capsules],
        "refusals": [{"qualname": r.qualname, "reason": r.reason} for r in session.refusals],
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))


def load(path: str = ".witness") -> Recording:
    """Load a recording from ``path``, or raise if missing/incompatible."""
    root = Path(path)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"no recording at '{path}/manifest.json' — run your program inside "
            f"`with witness.recording():` first"
        )
    data = json.loads(manifest_path.read_text())
    version = data.get("format_version")
    if version != FORMAT_VERSION:
        raise ValueError(
            f"recording at '{path}' uses format v{version}, but this witness expects "
            f"v{FORMAT_VERSION} — re-record with the current version"
        )
    blobs = root / "blobs"
    capsules = [_capsule_from_json(c, blobs) for c in data["capsules"]]
    refusals = [Refusal(r["qualname"], r["reason"]) for r in data["refusals"]]
    return Recording(capsules=capsules, refusals=refusals)


# ── (de)serialization ─────────────────────────────────────────────────────────


def _write_encoded(enc: Encoded, blobs: Path) -> dict:
    blob_path = blobs / enc.hash
    if not blob_path.exists():
        blob_path.write_bytes(enc.blob)
    return {"literal": enc.literal, "blob": enc.hash}


def _read_encoded(entry: dict, blobs: Path) -> Encoded:
    blob = (blobs / entry["blob"]).read_bytes()
    return Encoded(blob=blob, literal=entry["literal"])


def _capsule_to_json(capsule: Capsule, blobs: Path) -> dict:
    out: dict = {
        "module": capsule.module,
        "func": capsule.func,
        "args": [_write_encoded(e, blobs) for e in capsule.args],
        "kwargs": {k: _write_encoded(e, blobs) for k, e in capsule.kwargs.items()},
        "boundary": {
            name: [_write_encoded(e, blobs) for e in vals]
            for name, vals in capsule.boundary.items()
        },
        "deps": {
            name: {key: [_write_encoded(e, blobs) for e in vals] for key, vals in table.items()}
            for name, table in capsule.deps.items()
        },
    }
    outcome = capsule.outcome
    if isinstance(outcome, ReturnOutcome):
        out["outcome"] = {"kind": "return", "value": _write_encoded(outcome.value, blobs)}
    elif isinstance(outcome, PartialOutcome):
        out["outcome"] = {
            "kind": "partial",
            "matcher": matcher_mod.to_json(outcome.matcher, lambda e: _write_encoded(e, blobs)),
        }
    else:
        out["outcome"] = {
            "kind": "raise",
            "exc_type": outcome.exc_type,
            "exc_module": outcome.exc_module,
        }
    return out


def _capsule_from_json(data: dict, blobs: Path) -> Capsule:
    outcome_data = data["outcome"]
    kind = outcome_data["kind"]
    outcome: ReturnOutcome | RaiseOutcome | PartialOutcome
    if kind == "return":
        outcome = ReturnOutcome(value=_read_encoded(outcome_data["value"], blobs))
    elif kind == "partial":
        outcome = PartialOutcome(
            matcher=matcher_mod.from_json(
                outcome_data["matcher"], lambda ed: _read_encoded(ed, blobs)
            )
        )
    else:
        outcome = RaiseOutcome(
            exc_type=outcome_data["exc_type"], exc_module=outcome_data["exc_module"]
        )
    return Capsule(
        module=data["module"],
        func=data["func"],
        args=[_read_encoded(e, blobs) for e in data["args"]],
        kwargs={k: _read_encoded(e, blobs) for k, e in data["kwargs"].items()},
        outcome=outcome,
        boundary={
            name: [_read_encoded(e, blobs) for e in vals]
            for name, vals in data.get("boundary", {}).items()
        },
        deps={
            name: {key: [_read_encoded(e, blobs) for e in vals] for key, vals in table.items()}
            for name, table in data.get("deps", {}).items()
        },
    )
