"""Certification — the proof that turns an observation into a committable fact.

This is the wedge. Before witness will keep a recorded call, it:

1. serializes the entry-snapshot inputs and the outcome (round-trip verified), then
2. **reconstructs** those inputs from their serialized form, **re-invokes** the
   real function, and **compares** the replayed outcome to the observed one.

Only a match yields a :class:`~witness.capsule.Capsule`; anything else is a
:class:`~witness.capsule.Refusal` with an explained reason. So an emitted test
passes by construction, or it is never emitted.

Honest v0 limitation: step 2 re-invokes the function, so a function with side
effects runs a second time during recording, and a function whose output depends
on external/mutable state (clock, network, globals) will legitimately fail to
reproduce and be refused. The hermetic boundary ledger (roadmap) removes this by
replaying dependencies instead of re-running them.
"""

from __future__ import annotations

from typing import Callable

from . import value
from .capsule import Capsule, RaiseOutcome, Refusal, ReturnOutcome


def certify(
    func: Callable,
    module: str,
    qualname: str,
    args: list,
    kwargs: dict,
    result: object,
    raised: BaseException | None,
) -> Capsule | Refusal:
    """Certify one observed call into a :class:`Capsule`, or refuse it."""
    # 1. Serialize inputs (entry snapshots) with round-trip verification.
    try:
        arg_enc = [value.encode(a) for a in args]
        kwarg_enc = {k: value.encode(v) for k, v in kwargs.items()}
    except value.EncodeError as exc:
        return Refusal(qualname, f"inputs not reproducible: {exc}")

    # 2. Serialize the outcome (only a returned value needs a stored blob).
    if raised is None:
        try:
            result_enc = value.encode(result)
        except value.EncodeError as exc:
            return Refusal(qualname, f"return value not reproducible: {exc}")

    # 3. Reconstruct inputs and re-invoke the real function.
    replay_args = [value.reconstruct(e) for e in arg_enc]
    replay_kwargs = {k: value.reconstruct(e) for k, e in kwarg_enc.items()}
    try:
        replay_result = func(*replay_args, **replay_kwargs)
        replay_raised: BaseException | None = None
    except BaseException as exc:  # noqa: BLE001 - we are characterizing any raise
        replay_result = None
        replay_raised = exc

    # 4. Compare the replayed outcome to what we observed.
    if raised is not None:
        if replay_raised is None:
            return Refusal(
                qualname,
                f"not reproducible: observed {type(raised).__name__} but replay returned",
            )
        if type(replay_raised) is not type(raised):
            return Refusal(
                qualname,
                f"not reproducible: observed {type(raised).__name__} but replay "
                f"raised {type(replay_raised).__name__}",
            )
        return Capsule(
            module=module,
            func=qualname,
            args=arg_enc,
            kwargs=kwarg_enc,
            outcome=RaiseOutcome(
                # __qualname__ so nested exception classes import correctly.
                exc_type=type(raised).__qualname__,
                exc_module=type(raised).__module__,
            ),
        )

    # Observed a normal return.
    if replay_raised is not None:
        return Refusal(
            qualname,
            f"not reproducible: replay raised {type(replay_raised).__name__}",
        )
    if not value.values_equal(replay_result, result):
        return Refusal(
            qualname,
            "not reproducible: replay output differs (nondeterministic or "
            "state-dependent output)",
        )
    # The emitted test compares the live result against a *reconstructed* value, so
    # certification must prove that exact comparison — not `result == replay_result`
    # on two live objects, which can pass via an identity short-circuit
    # (`[nan] == [nan]`, singletons with identity `__eq__`) yet fail once the test
    # loads a fresh copy. Check what the test will actually check.
    if not value.values_equal(value.reconstruct(result_enc), result):
        return Refusal(
            qualname,
            "not assertable: value is not equal to a fresh copy of itself "
            "(identity-dependent equality, or a non-reflexive value like nan)",
        )
    return Capsule(
        module=module,
        func=qualname,
        args=arg_enc,
        kwargs=kwarg_enc,
        outcome=ReturnOutcome(value=result_enc),
    )
