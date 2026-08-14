"""Volatility triage — certify the stable structure of a partly-volatile return.

When a function's return varies across the sampled re-invocations (a source of
nondeterminism witness doesn't record — an embedded timestamp, an id from an
undeclared dependency), witness used to refuse the whole call. Triage instead looks
for the *stable* structure across every sample and, for the common case of a dict
with a fixed key set, emits a :class:`~witness.capsule.PartialOutcome`: stable fields
asserted exactly, volatile-but-stably-typed fields asserted by type. Every check
held in *every* sample, so nothing asserted is fiction.

v0 scope: a top-level dict with the same (str/int) keys in every sample, and at
least one stably-valued field (so the emitted test pins a real value, not just a
shape). Anything else still refuses.
"""

from __future__ import annotations

from . import value
from .capsule import PartialOutcome


def triage_return(samples: list) -> PartialOutcome | None:
    """Build a partial matcher from the observed returns, or None to refuse."""
    if len(samples) < 2 or not all(isinstance(s, dict) for s in samples):
        return None
    keyset = set(samples[0].keys())
    if any(set(s.keys()) != keyset for s in samples):
        return None
    # Only simple, renderable keys (exclude bool, which is an int subclass).
    if not all(isinstance(k, (str, int)) and not isinstance(k, bool) for k in keyset):
        return None

    keys = sorted(keyset, key=lambda k: (type(k).__name__, k))
    exact: list = []
    types: list = []
    for key in keys:
        vals = [s[key] for s in samples]
        enc = _assertable(vals[0]) if all(value.values_equal(v, vals[0]) for v in vals) else None
        if enc is not None:
            exact.append((key, enc))
        elif _one_type(vals):
            # Volatile, or stable-but-not-`==`-assertable (nan-in-container, identity
            # __eq__): assert only the type witness observed in every sample.
            types.append((key, type(vals[0]).__name__))
        # else: fully volatile — presence only (covered by the key-set assertion)

    if not exact:
        return None  # nothing concrete to pin → not worth a test; refuse instead
    return PartialOutcome(keys=tuple(keys), exact=tuple(exact), types=tuple(types))


def partial_matches(outcome: PartialOutcome, val: object) -> bool:
    """Whether ``val`` satisfies a partial matcher (used by ``witness check``)."""
    if not isinstance(val, dict) or set(val.keys()) != set(outcome.keys):
        return False
    for key, enc in outcome.exact:
        if key not in val or not value.values_equal(val[key], value.reconstruct(enc)):
            return False
    for key, type_name in outcome.types:
        if key not in val or type(val[key]).__name__ != type_name:
            return False
    return True


def _one_type(vals: list) -> bool:
    return len({type(v).__name__ for v in vals}) == 1


def _assertable(val: object):
    """Encode ``val`` only if it equals a fresh copy of itself, mirroring the
    full-return "not assertable" guard — so a non-reflexive value (`[nan]`) or an
    identity-`__eq__` object is never emitted as an exact field that would fail once
    the test loads a fresh copy. Returns the :class:`Encoded`, or None."""
    try:
        enc = value.encode(val)
    except value.EncodeError:
        return None
    return enc if value.values_equal(value.reconstruct(enc), val) else None
