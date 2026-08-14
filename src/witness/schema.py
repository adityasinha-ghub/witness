"""Structural fingerprints — catch type/shape drift that ``==`` can't see.

Two values can be equal under ``==`` yet differ in type or structure: ``5`` vs
``5.0``, ``True`` vs ``1``, ``[1, 2]`` vs ``[1, 2.0]``, ``{"a": 1}`` vs
``{"a": 1.0}``. A generated test asserting ``==`` wouldn't notice, but such a change
is often a real regression (an API that started returning floats). ``witness check``
uses these fingerprints to report *drift* — same value, different shape — as its own
category, so it stays consistent with the ``==`` the tests use while still surfacing
the change.
"""

from __future__ import annotations

_MAX_DEPTH = 8


def fingerprint(value: object, depth: int = 0) -> str:
    """A canonical structural description of ``value`` (type + nested shape)."""
    if depth >= _MAX_DEPTH:
        return "…"
    if value is None:
        return "None"
    kind = type(value)
    if kind is bool:  # before int (bool subclasses int)
        return "bool"
    if kind in (int, float, complex, str, bytes, bytearray):
        return kind.__name__
    if kind in (list, tuple, set, frozenset):
        elems = sorted({fingerprint(v, depth + 1) for v in value})
        return f"{kind.__name__}[{'|'.join(elems)}]"
    if kind is dict:
        items = sorted(f"{k!r}:{fingerprint(v, depth + 1)}" for k, v in value.items())
        return "dict{" + ",".join(items) + "}"
    return kind.__qualname__  # any other object: its type
