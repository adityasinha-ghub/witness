"""A recursive structural matcher — the shape volatility triage certifies.

A matcher describes what held across *every* sampled return, at any depth:

- :class:`Exact` — this position had the same (`==`-assertable) value every time.
- :class:`OfType` — it varied but was always the same type.
- :class:`Anything` — nothing could be grounded here (asserted only by position).
- :class:`DictMatch` — a dict with a stable key set; each field has its own matcher.
- :class:`SeqMatch` — a list/tuple with a stable length; each index has its own matcher.

The matcher is rendered to pytest asserts (:mod:`witness.generate`) and evaluated
against the current code (:mod:`witness.check`); both walk this same tree, so they
never disagree. Nothing in a matcher is ever a guess — each node reflects something
observed in every sample.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import value
from .value import Encoded


@dataclass(frozen=True)
class Exact:
    value: Encoded


@dataclass(frozen=True)
class OfType:
    type_name: str


@dataclass(frozen=True)
class Anything:
    pass


@dataclass(frozen=True)
class DictMatch:
    keys: tuple  # sorted (str/int) keys asserted as the exact key set
    fields: tuple  # ((key, Matcher), ...) — a matcher per asserted field


@dataclass(frozen=True)
class SeqMatch:
    kind: str  # "list" | "tuple"
    items: tuple  # (Matcher, ...) — a matcher per index


Matcher = Exact | OfType | Anything | DictMatch | SeqMatch


def matches(m: Matcher, val: object) -> bool:
    """Whether ``val`` satisfies matcher ``m`` (used by ``witness check``)."""
    if isinstance(m, Anything):
        return True
    if isinstance(m, Exact):
        return value.values_equal(val, value.reconstruct(m.value))
    if isinstance(m, OfType):
        return type(val).__name__ == m.type_name
    if isinstance(m, DictMatch):
        if not isinstance(val, dict) or set(val.keys()) != set(m.keys):
            return False
        return all(k in val and matches(sub, val[k]) for k, sub in m.fields)
    if isinstance(m, SeqMatch):
        cls = list if m.kind == "list" else tuple
        if not isinstance(val, cls) or len(val) != len(m.items):
            return False
        return all(matches(sub, v) for sub, v in zip(m.items, val, strict=False))
    return False


def has_exact(m: Matcher) -> bool:
    """Whether the tree pins at least one concrete value (else it's not worth a test)."""
    if isinstance(m, Exact):
        return True
    if isinstance(m, DictMatch):
        return any(has_exact(s) for _, s in m.fields)
    if isinstance(m, SeqMatch):
        return any(has_exact(s) for s in m.items)
    return False


def signature(m: Matcher) -> tuple:
    """A hashable structural signature (used to dedup capsules)."""
    if isinstance(m, Anything):
        return ("any",)
    if isinstance(m, Exact):
        return ("exact", m.value.hash)
    if isinstance(m, OfType):
        return ("type", m.type_name)
    if isinstance(m, DictMatch):
        return ("dict", m.keys, tuple((k, signature(s)) for k, s in m.fields))
    return ("seq", m.kind, tuple(signature(s) for s in m.items))


def summary(m: Matcher) -> str:
    """A short human description (for ``witness check`` output)."""
    if isinstance(m, DictMatch):
        return "dict{" + ", ".join(repr(k) for k in m.keys) + "}"
    if isinstance(m, SeqMatch):
        return f"{m.kind}[{len(m.items)}]"
    if isinstance(m, OfType):
        return m.type_name
    if isinstance(m, Exact):
        return "value"
    return "any"


def to_json(m: Matcher, write) -> dict:
    """Serialize a matcher; ``write(Encoded) -> dict`` stores exact values."""
    if isinstance(m, Anything):
        return {"m": "any"}
    if isinstance(m, Exact):
        return {"m": "exact", "v": write(m.value)}
    if isinstance(m, OfType):
        return {"m": "type", "t": m.type_name}
    if isinstance(m, DictMatch):
        return {
            "m": "dict",
            "keys": list(m.keys),
            "fields": [[k, to_json(s, write)] for k, s in m.fields],
        }
    return {"m": "seq", "kind": m.kind, "items": [to_json(s, write) for s in m.items]}


def from_json(d: dict, read) -> Matcher:
    """Deserialize a matcher; ``read(dict) -> Encoded`` loads exact values."""
    kind = d["m"]
    if kind == "any":
        return Anything()
    if kind == "exact":
        return Exact(read(d["v"]))
    if kind == "type":
        return OfType(d["t"])
    if kind == "dict":
        return DictMatch(
            tuple(d["keys"]),
            tuple((k, from_json(s, read)) for k, s in d["fields"]),
        )
    return SeqMatch(d["kind"], tuple(from_json(s, read) for s in d["items"]))
