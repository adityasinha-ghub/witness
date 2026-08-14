"""The recorded, certified unit: a :class:`Capsule` (one proven function call).

A capsule is only ever created by certification (:mod:`witness.certify`), so its
mere existence means: these recorded inputs, when fed back into the function,
reproduced this recorded outcome. A call that could not be certified becomes a
:class:`Refusal` instead — an explained absence, never a fabricated assertion.
"""

from __future__ import annotations

from dataclasses import dataclass

from .value import Encoded


@dataclass(frozen=True)
class ReturnOutcome:
    """The call returned this (certified) value."""

    value: Encoded


@dataclass(frozen=True)
class RaiseOutcome:
    """The call raised this exception type (reproduced on replay)."""

    exc_type: str  # __qualname__ (may be dotted for a nested class)
    exc_module: str


Outcome = ReturnOutcome | RaiseOutcome


@dataclass(frozen=True)
class Capsule:
    """One certified call: reconstructable inputs and a reproduced outcome."""

    module: str
    func: str  # top-level function name
    args: list[Encoded]
    kwargs: dict[str, Encoded]
    outcome: Outcome


@dataclass(frozen=True)
class Refusal:
    """A call witness observed but would not certify, with the honest reason."""

    qualname: str
    reason: str
