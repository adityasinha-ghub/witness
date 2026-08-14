"""The recorded, certified unit: a :class:`Capsule` (one proven function call).

A capsule is only ever created by certification (:mod:`witness.certify`), so its
mere existence means: these recorded inputs, when fed back into the function,
reproduced this recorded outcome. A call that could not be certified becomes a
:class:`Refusal` instead — an explained absence, never a fabricated assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class PartialOutcome:
    """The call returned a dict with a stable key set but a partly-volatile value.

    Built by volatility triage from the several sampled returns: ``exact`` fields
    held the same value in every sample (asserted with ``==``); ``types`` fields
    varied but kept the same type (asserted by type name); keys with neither are
    asserted only by their presence in the key set. Every check is grounded in what
    every sample showed.
    """

    keys: tuple  # the asserted key set (str/int keys), sorted
    exact: tuple  # tuple of (key, Encoded) — stable values
    types: tuple  # tuple of (key, type_name) — volatile but stably-typed values


Outcome = ReturnOutcome | RaiseOutcome | PartialOutcome


@dataclass(frozen=True)
class Capsule:
    """One certified call: reconstructable inputs and a reproduced outcome."""

    module: str
    func: str  # top-level function name
    args: list[Encoded]
    kwargs: dict[str, Encoded]
    outcome: Outcome
    # Recorded nondeterminism seam values (dotted name -> values drawn, in order),
    # replayed on certify and in the generated test so the call is reproducible.
    boundary: dict[str, list[Encoded]] = field(default_factory=dict)
    # Recorded dependency responses (dotted name -> arg-hash -> returns, in order),
    # replayed by matching call arguments.
    deps: dict[str, dict[str, list[Encoded]]] = field(default_factory=dict)


@dataclass(frozen=True)
class Refusal:
    """A call witness observed but would not certify, with the honest reason."""

    qualname: str
    reason: str
