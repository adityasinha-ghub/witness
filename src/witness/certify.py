"""Certification — the proof that turns an observation into a committable fact.

This is the wedge. Before witness will keep a recorded call, it:

1. serializes the entry-snapshot inputs, the recorded seam values, and the outcome
   (round-trip verified), then
2. **reconstructs** those inputs, **re-invokes** the real function ``samples`` times
   with the recorded nondeterminism seams *replayed* (not drawn fresh), and checks
   every re-invocation reproduces the observed outcome — comparing the value against
   a *fresh reconstruction*, exactly the comparison the emitted test performs.

Only if all samples agree does it yield a :class:`~witness.capsule.Capsule`;
anything else is a :class:`~witness.capsule.Refusal` with an explained reason.

What certification can and can't guarantee (honest bounds):
- It proves the call reproduced across ``samples`` immediate re-invocations with the
  *recorded* seams replayed. That reliably rejects high-entropy nondeterminism.
- It cannot see nondeterminism from sources witness doesn't record (see
  :mod:`witness.seams`) — a *low-cardinality* uncovered source can, rarely, re-roll
  the same value across all samples and slip through. More ``samples`` shrinks this;
  covering the source as a seam eliminates it.
- It re-invokes **in-process**, so a value cached once per process (e.g. a
  module-level ``uuid4()`` computed at import) always "reproduces" here yet varies
  between processes. Those remain a documented risk, not a caught one.
"""

from __future__ import annotations

from collections.abc import Callable

from . import triage, value
from .capsule import Capsule, PartialOutcome, RaiseOutcome, Refusal, ReturnOutcome
from .seams import WitnessReplayError


def certify(
    func: Callable,
    module: str,
    qualname: str,
    args: list,
    kwargs: dict,
    result: object,
    raised: BaseException | None,
    boundary: dict[str, list],
    dep_log: dict[str, dict[str, list]],
    session,
) -> Capsule | Refusal:
    """Certify one observed call into a :class:`Capsule`, or refuse it."""
    # 1. Serialize inputs (entry snapshots) with round-trip verification.
    try:
        arg_enc = [value.encode(a) for a in args]
        kwarg_enc = {k: value.encode(v) for k, v in kwargs.items()}
    except value.EncodeError as exc:
        return Refusal(qualname, f"inputs not reproducible: {exc}")

    # 2. Serialize the recorded seam values.
    try:
        boundary_enc = {name: [value.encode(v) for v in vals] for name, vals in boundary.items()}
    except value.EncodeError as exc:
        return Refusal(qualname, f"recorded seam value not reproducible: {exc}")

    # 2b. Serialize the recorded dependency responses.
    try:
        deps_enc = {
            name: {key: [value.encode(v) for v in vals] for key, vals in table.items()}
            for name, table in dep_log.items()
        }
    except value.EncodeError as exc:
        return Refusal(qualname, f"recorded dependency response not reproducible: {exc}")

    # 3. Re-invoke `samples` times, collecting each outcome. Control-flow divergence
    #    (an unrecorded seam/dep, or a different count of them) refuses immediately.
    samples = getattr(session, "samples", 1)
    sample_results: list = []
    sample_raises: list[BaseException | None] = []
    for _ in range(samples):
        # Fresh inputs each sample, so a function that mutates its args in place
        # doesn't corrupt the next sample.
        replay_args = [value.reconstruct(e) for e in arg_enc]
        replay_kwargs = {k: value.reconstruct(e) for k, e in kwarg_enc.items()}
        session._replaying = True
        session._replay_queues = {name: list(vals) for name, vals in boundary.items()}
        session._replay_deps = {
            name: {key: list(vals) for key, vals in table.items()}
            for name, table in dep_log.items()
        }
        try:
            try:
                replay_result = func(*replay_args, **replay_kwargs)
                replay_raised: BaseException | None = None
            except WitnessReplayError:
                return Refusal(
                    qualname,
                    "not reproducible: replay reached a clock/RNG/dependency call that "
                    "wasn't recorded — control flow is input/state dependent",
                )
            except BaseException as exc:  # noqa: BLE001 - characterize any raise
                replay_result = None
                replay_raised = exc
            leftover = any(session._replay_queues.get(n) for n in session._replay_queues) or any(
                q for table in session._replay_deps.values() for q in table.values()
            )
        finally:
            session._replaying = False
            session._replay_queues = None
            session._replay_deps = None

        if leftover:
            return Refusal(
                qualname,
                "not reproducible: replay consumed fewer recorded clock/RNG/dependency "
                "values than were captured — control flow is input/state dependent",
            )
        sample_results.append(replay_result)
        sample_raises.append(replay_raised)

    # 4. Decide the outcome from the observation plus every sample.
    outcome = _decide_outcome(qualname, result, raised, sample_results, sample_raises)
    if isinstance(outcome, Refusal):
        return outcome

    return Capsule(
        module=module,
        func=qualname,
        args=arg_enc,
        kwargs=kwarg_enc,
        outcome=outcome,
        boundary=boundary_enc,
        deps=deps_enc,
    )


def _decide_outcome(
    qualname: str,
    result: object,
    raised: BaseException | None,
    sample_results: list,
    sample_raises: list,
) -> Capsule | RaiseOutcome | ReturnOutcome | PartialOutcome | Refusal:
    """Turn the observed outcome + all samples into an outcome, or a Refusal."""
    if raised is not None or any(rr is not None for rr in sample_raises):
        # Exception path: the observation and every sample must raise the same type.
        if raised is None:
            return Refusal(qualname, "not reproducible: observed a return but replay raised")
        for rr in sample_raises:
            if rr is None:
                return Refusal(
                    qualname,
                    f"not reproducible: observed {type(raised).__name__} but replay returned",
                )
            if type(rr) is not type(raised):
                return Refusal(
                    qualname,
                    f"not reproducible: observed {type(raised).__name__} but replay "
                    f"raised {type(rr).__name__}",
                )
        exc_qualname = type(raised).__qualname__  # imports Outer.Inner nesting…
        if "<locals>" in exc_qualname:  # …but not a function-local class — can't reference it
            return Refusal(
                qualname,
                f"exception type {type(raised).__name__} is defined in a local scope "
                f"(<locals>) and can't be referenced portably",
            )
        return RaiseOutcome(exc_type=exc_qualname, exc_module=type(raised).__module__)

    # Return path — fully stable across every sample?
    if all(value.values_equal(r, result) for r in sample_results):
        try:
            result_enc = value.encode(result)
        except value.EncodeError as exc:
            return Refusal(qualname, f"return value not reproducible: {exc}")
        # The emitted test compares against a *reconstructed* value, so prove that
        # exact comparison — `result == replay` on live objects can pass via an
        # identity short-circuit (`[nan] == [nan]`, identity-`__eq__` singletons).
        if not value.values_equal(value.reconstruct(result_enc), result):
            return Refusal(
                qualname,
                "not assertable: value is not equal to a fresh copy of itself "
                "(identity-dependent equality, or a non-reflexive value like nan)",
            )
        return ReturnOutcome(value=result_enc)

    # Values differ across samples: certify the stable structure, or refuse.
    partial = triage.triage_return([result, *sample_results])
    if partial is None:
        return Refusal(
            qualname,
            "not reproducible: replay output differs (nondeterministic or state-dependent output)",
        )
    return partial
