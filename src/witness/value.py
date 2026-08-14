"""Encode observed values so a capsule can be reconstructed and a test can read.

Two concerns live here, both in service of the grounding invariant:

- **reconstruct** — turn a stored value back into a live object, so certification
  can re-invoke the function and confirm the recorded output reproduces. The
  canonical form is a pickle blob (robust for arbitrary objects).
- **render_literal** — produce *readable* Python source for a value, but only when
  that source provably evaluates back to an equal value. Readable literals make the
  generated tests standalone and legible; anything else falls back to a blob
  reference.

If a value cannot be faithfully round-tripped (pickle fails, or fails to reload
equal), encoding **refuses** — witness never stores a fixture it cannot reproduce.
"""

from __future__ import annotations

import hashlib
import math
import pickle
from dataclasses import dataclass


class EncodeError(Exception):
    """A value could not be faithfully serialized — the caller must refuse it."""


@dataclass(frozen=True)
class Encoded:
    """A faithfully round-tripped value.

    ``blob`` is the canonical pickle used for reconstruction. ``literal`` is a
    readable Python-source rendering when one provably round-trips, else ``None``.
    """

    blob: bytes
    literal: str | None

    @property
    def hash(self) -> str:
        return blob_hash(self.blob)


def blob_hash(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def encode(value: object) -> Encoded:
    """Serialize ``value``, or raise :class:`EncodeError` if it can't be.

    Encoding only establishes that the value *serializes and reloads*; it does not
    decide whether the value is safely assertable. That is deliberate: an input
    only needs to reconstruct well enough to drive the same execution (which
    certification proves by re-invoking), and whether a *return* value is faithfully
    assertable with ``==`` against its reconstruction is checked in one place —
    :mod:`witness.certify` — mirroring exactly what the emitted test does. Doing a
    self-``==`` or byte-stability check here would wrongly reject legitimate values
    (``nan`` inputs; string sets whose pickle byte-order is hash-seed dependent).
    """
    try:
        blob = pickle.dumps(value)
    except Exception as exc:  # unpicklable objects, lambdas, open handles, ...
        raise EncodeError(f"not picklable: {exc!r}") from exc
    try:
        pickle.loads(blob)
    except Exception as exc:
        raise EncodeError(f"pickle failed to reload: {exc!r}") from exc
    return Encoded(blob=blob, literal=_verified_literal(value))


def reconstruct(encoded: Encoded) -> object:
    """Rebuild the live object from its canonical blob."""
    return pickle.loads(encoded.blob)


def values_equal(a: object, b: object) -> bool:
    """``a == b`` reduced to a real bool, treating a non-bool/raising ``==`` as unequal.

    Some objects (numpy arrays, custom types) return non-bool or raise from ``==``;
    for the grounding invariant we can only certify equality we can actually decide,
    so anything we cannot cleanly compare is treated as *not equal* (→ refusal).
    """
    try:
        result = a == b
    except Exception:
        return False
    if isinstance(result, bool):
        return result
    return False


# ── readable literal rendering ────────────────────────────────────────────────

# Namespace the rendered literals are checked against — only plain builtins.
_LITERAL_GLOBALS = {"__builtins__": {}, "set": set, "frozenset": frozenset}


def _verified_literal(value: object) -> str | None:
    """Render ``value`` as source, but only return it if it evals back equal."""
    src = _render_literal(value)
    if src is None:
        return None
    try:
        restored = eval(src, dict(_LITERAL_GLOBALS))  # noqa: S307 - vetted source
    except Exception:
        return None
    if type(restored) is not type(value) or not values_equal(restored, value):
        return None
    return src


def _render_literal(value: object) -> str | None:
    """Best-effort readable source for a value composed only of plain data.

    Returns ``None`` for anything not built purely from literal-safe primitives and
    containers; the caller then falls back to a blob reference. The result is always
    re-verified by :func:`_verified_literal` before use.
    """
    # bool must precede int (bool is a subclass of int).
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, int):
        return repr(value)
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else None
    if isinstance(value, (str, bytes)):
        return repr(value)
    if isinstance(value, list):
        return _render_seq(value, "[", "]")
    if isinstance(value, tuple):
        parts = _render_items(value)
        if parts is None:
            return None
        if len(parts) == 1:
            return f"({parts[0]},)"
        return "(" + ", ".join(parts) + ")"
    if isinstance(value, set):
        if not value:
            return "set()"
        parts = _render_items(value)
        return "{" + ", ".join(parts) + "}" if parts is not None else None
    if isinstance(value, frozenset):
        if not value:
            return "frozenset()"
        parts = _render_items(value)
        return "frozenset({" + ", ".join(parts) + "})" if parts is not None else None
    if isinstance(value, dict):
        items = []
        for k, v in value.items():
            ks, vs = _render_literal(k), _render_literal(v)
            if ks is None or vs is None:
                return None
            items.append(f"{ks}: {vs}")
        return "{" + ", ".join(items) + "}"
    return None


def _render_items(values) -> list[str] | None:
    out = []
    for item in values:
        rendered = _render_literal(item)
        if rendered is None:
            return None
        out.append(rendered)
    return out


def _render_seq(values, open_c: str, close_c: str) -> str | None:
    parts = _render_items(values)
    if parts is None:
        return None
    return open_c + ", ".join(parts) + close_c
