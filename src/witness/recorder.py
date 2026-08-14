"""Capture: the ``@record`` decorator and the ``recording()`` session.

The decorator snapshots a call's inputs **at entry** (deep-copied, so a function
that mutates its arguments in place doesn't smuggle the post-call state back in as
"the input"), runs the real call once, then hands the snapshot and outcome to
certification. While a recorded call is in flight, nondeterminism *seams* (clock,
RNG, uuid — see :mod:`witness.seams`) are logged so certification can replay them.
Certified calls and explained refusals accumulate on the active :class:`Session`,
which persists them when the ``recording()`` context exits.
"""

from __future__ import annotations

import copy
import functools
from contextlib import contextmanager
from typing import Callable

from .capsule import Capsule, Refusal
from .certify import certify

_active: Session | None = None

# How many times certification re-invokes a call to check it reproduces. More
# samples catch more hidden nondeterminism (from sources witness doesn't record)
# at the cost of re-running the function more times.
DEFAULT_SAMPLES = 5


class Session:
    """Collects certified capsules and refusals during one recording run."""

    def __init__(self) -> None:
        self.capsules: list[Capsule] = []
        self.refusals: list[Refusal] = []
        # True while certification is re-invoking a target, so nested @record
        # calls pass through instead of recording the replay as fresh captures.
        self._replaying = False
        # Stack of per-call seam logs (dotted name -> values drawn, in order); the
        # innermost in-flight call is the top of the stack.
        self._call_stack: list[dict[str, list]] = []
        # Set to a call's seam queues while certification replays it.
        self._replay_queues: dict[str, list] | None = None
        self.samples = DEFAULT_SAMPLES

    def _refuse(self, qualname: str, reason: str) -> None:
        self.refusals.append(Refusal(qualname, reason))

    def _seam(self, name: str, original: Callable):
        """Wrap a seam function to replay (during certify) or log (during record)."""

        def wrapped(*args, **kwargs):
            if self._replay_queues is not None:
                from .seams import WitnessReplayError

                queue = self._replay_queues.get(name)
                if not queue:
                    raise WitnessReplayError(name)
                return queue.pop(0)
            if not self._replaying and self._call_stack:
                result = original(*args, **kwargs)
                self._call_stack[-1].setdefault(name, []).append(result)
                return result
            return original(*args, **kwargs)

        return wrapped

    def _observe(
        self,
        func: Callable,
        args: list,
        kwargs: dict,
        result: object,
        raised: BaseException | None,
        boundary: dict[str, list],
    ) -> None:
        outcome = certify(
            func,
            func.__module__,
            func.__qualname__,
            args,
            kwargs,
            result,
            raised,
            boundary,
            self,
        )
        if isinstance(outcome, Refusal):
            self.refusals.append(outcome)
        else:
            self.capsules.append(outcome)


def record(func: Callable) -> Callable:
    """Mark ``func`` for recording whenever a ``recording()`` session is active."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        session = _active
        if session is None:
            return func(*args, **kwargs)
        if session._replaying:
            # A nested @record call reached during certification's re-invoke: run it
            # for real, and suspend the enclosing call's replay queues so this call's
            # own seam draws aren't served/consumed from them (which would wrongly
            # refuse a deterministic outer function that calls a seam-using inner one).
            saved = session._replay_queues
            session._replay_queues = None
            try:
                return func(*args, **kwargs)
            finally:
                session._replay_queues = saved
        try:
            arg_snapshot = [copy.deepcopy(a) for a in args]
            kwarg_snapshot = {k: copy.deepcopy(v) for k, v in kwargs.items()}
        except Exception as exc:  # unpicklable/uncopyable inputs → honest refusal
            session._refuse(func.__qualname__, f"inputs not deep-copyable: {exc!r}")
            return func(*args, **kwargs)

        boundary: dict[str, list] = {}
        session._call_stack.append(boundary)
        try:
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - characterize any raise
                session._observe(
                    func, arg_snapshot, kwarg_snapshot, None, exc, boundary
                )
                raise
            session._observe(
                func, arg_snapshot, kwarg_snapshot, result, None, boundary
            )
            return result
        finally:
            session._call_stack.pop()

    wrapper.__witness_wrapped__ = func  # type: ignore[attr-defined]
    return wrapper


@contextmanager
def recording(
    path: str = ".witness",
    seams: list[str] | None = None,
    samples: int | None = None,
    targets: list[str] | None = None,
):
    """Record ``@record``-decorated calls made inside this block.

    Pass ``targets=["your.module", ...]`` to auto-instrument every top-level function
    in those modules — no decorators needed (the legacy-code path). Nondeterminism
    seams (``witness.seams.DEFAULT_SEAMS`` by default; pass ``seams`` to override, or
    ``[]`` to disable) are replayable. ``samples`` sets how many times each call is
    re-invoked to check it reproduces (default :data:`DEFAULT_SAMPLES`). On exit, the
    session's certified capsules and refusals are written to ``path``.
    """
    from . import instrument
    from . import seams as seams_mod
    from . import store

    global _active
    if _active is not None:
        raise RuntimeError("witness.recording() is already active in this process")
    session = Session()
    if samples is not None:
        session.samples = max(1, samples)
    _active = session
    resolved = seams_mod.resolve_seams(seams)
    seam_saved: list = []
    undo: list = []
    setup_ok = False
    # All global-state setup is inside the try so the finally always restores it —
    # a target that fails to import must not leave seams patched or _active set.
    try:
        for name, module, attr, original in resolved:
            setattr(module, attr, session._seam(name, original))
            seam_saved.append((module, attr, original))
        undo = instrument.wrap_module_functions(targets or [], record)
        setup_ok = True
        yield session
    finally:
        instrument.unwrap(undo)
        for module, attr, original in reversed(seam_saved):
            setattr(module, attr, original)
        _active = None
        if setup_ok:  # don't overwrite a good recording when setup itself failed
            store.save(session, path)
