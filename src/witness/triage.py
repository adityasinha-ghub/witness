"""Volatility triage — certify the stable structure of a partly-volatile return.

When a function's return varies across the sampled re-invocations (a source of
nondeterminism witness doesn't record — an embedded timestamp, an id from an
undeclared dependency), witness used to refuse the whole call. Triage instead builds
a recursive :mod:`~witness.matcher` of what held in *every* sample — stable values
asserted exactly, values that varied but kept a type asserted by type, dicts/lists
matched by shape with their fields/items triaged recursively — and certifies that.

A call is certified only if the matcher pins at least one concrete value (so the
emitted test asserts a real value, not just a shape); otherwise it's still refused.
A "stable" field is only asserted exactly if it equals a fresh copy of itself, so a
non-reflexive value (`[nan]`) or an identity-`__eq__` object never becomes a broken
exact assertion — it degrades to a type assertion. (Like any exact assertion, a
low-cardinality field can rarely be exact by coincidence — the same bounded risk the
README documents for uncovered nondeterminism.)
"""

from __future__ import annotations

from . import matcher as m
from . import value
from .capsule import PartialOutcome

# Bounds recursion depth — also stops runaway recursion on cyclic return values.
_MAX_DEPTH = 6


def triage_return(samples: list) -> PartialOutcome | None:
    """Build a partial matcher from the observed returns, or None to refuse."""
    if len(samples) < 2:
        return None
    built = build_matcher(samples)
    if not m.has_exact(built):
        return None  # nothing concrete to pin → not worth a test; refuse instead
    return PartialOutcome(matcher=built)


def build_matcher(samples: list, depth: int = 0) -> m.Matcher:
    """Recursively describe what every sample in ``samples`` had in common."""
    first = samples[0]

    # Stable and safely assertable → an exact value.
    if all(value.values_equal(s, first) for s in samples):
        enc = _assertable(first)
        if enc is not None:
            return m.Exact(enc)
        # equal but not `==`-assertable (nan-in-container, identity __eq__) → type

    # Too deep (or cyclic) to keep descending — assert the type only.
    if depth >= _MAX_DEPTH:
        return _typed_or_any(samples)

    # A dict with the same (simple) key set in every sample → match by shape.
    if all(isinstance(s, dict) for s in samples):
        keyset = set(first.keys())
        simple = all(isinstance(k, (str, int)) and not isinstance(k, bool) for k in keyset)
        if simple and all(set(s.keys()) == keyset for s in samples):
            keys = tuple(sorted(keyset, key=lambda k: (type(k).__name__, k)))
            fields = []
            for key in keys:
                sub = build_matcher([s[key] for s in samples], depth + 1)
                if not isinstance(sub, m.Anything):
                    fields.append((key, sub))
            return m.DictMatch(keys, tuple(fields))

    # A list (or a tuple) with the same length in every sample → match by index.
    all_list = all(isinstance(s, list) for s in samples)
    all_tuple = all(isinstance(s, tuple) for s in samples)
    if (all_list or all_tuple) and len({len(s) for s in samples}) == 1:
        kind = "list" if all_list else "tuple"
        items = tuple(build_matcher([s[i] for s in samples], depth + 1) for i in range(len(first)))
        return m.SeqMatch(kind, items)

    return _typed_or_any(samples)


def _typed_or_any(samples: list) -> m.Matcher:
    """Assert the type if it's the same in every sample, else nothing."""
    if len({type(s).__name__ for s in samples}) == 1:
        return m.OfType(type(samples[0]).__name__)
    return m.Anything()


def _assertable(val: object):
    """Encode ``val`` only if it equals a fresh copy of itself (see module doc)."""
    try:
        enc = value.encode(val)
    except value.EncodeError:
        return None
    return enc if value.values_equal(value.reconstruct(enc), val) else None
