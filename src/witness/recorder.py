"""Capture: the ``@record`` decorator and the ``recording()`` session.

The decorator snapshots a call's inputs **at entry** (deep-copied, so a function
that mutates its arguments in place doesn't smuggle the post-call state back in as
"the input"), runs the real call once, then hands the snapshot and outcome to
certification. Certified calls and explained refusals accumulate on the active
:class:`Session`, which persists them when the ``recording()`` context exits.
"""

from __future__ import annotations

import copy
import functools
from contextlib import contextmanager
from typing import Callable

from .capsule import Capsule, Refusal
from .certify import certify

_active: Session | None = None


class Session:
    """Collects certified capsules and refusals during one recording run."""

    def __init__(self) -> None:
        self.capsules: list[Capsule] = []
        self.refusals: list[Refusal] = []
        # True while certification is re-invoking a target, so nested @record
        # calls pass through instead of recording the replay as fresh captures.
        self._replaying = False

    def _refuse(self, qualname: str, reason: str) -> None:
        self.refusals.append(Refusal(qualname, reason))

    def _observe(
        self,
        func: Callable,
        args: list,
        kwargs: dict,
        result: object,
        raised: BaseException | None,
    ) -> None:
        self._replaying = True
        try:
            outcome = certify(
                func, func.__module__, func.__qualname__, args, kwargs, result, raised
            )
        finally:
            self._replaying = False
        if isinstance(outcome, Refusal):
            self.refusals.append(outcome)
        else:
            self.capsules.append(outcome)


def record(func: Callable) -> Callable:
    """Mark ``func`` for recording whenever a ``recording()`` session is active."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        session = _active
        if session is None or session._replaying:
            return func(*args, **kwargs)
        try:
            arg_snapshot = [copy.deepcopy(a) for a in args]
            kwarg_snapshot = {k: copy.deepcopy(v) for k, v in kwargs.items()}
        except Exception as exc:  # unpicklable/uncopyable inputs → honest refusal
            session._refuse(func.__qualname__, f"inputs not deep-copyable: {exc!r}")
            return func(*args, **kwargs)
        try:
            result = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - characterize any raise
            session._observe(func, arg_snapshot, kwarg_snapshot, None, exc)
            raise
        session._observe(func, arg_snapshot, kwarg_snapshot, result, None)
        return result

    wrapper.__witness_wrapped__ = func  # type: ignore[attr-defined]
    return wrapper


@contextmanager
def recording(path: str = ".witness"):
    """Record every ``@record``-decorated call made inside this block.

    On exit, the session's certified capsules and refusals are written to ``path``
    (default ``.witness/``), ready for ``witness generate``.
    """
    from . import store

    global _active
    if _active is not None:
        raise RuntimeError("witness.recording() is already active in this process")
    session = Session()
    _active = session
    try:
        yield session
    finally:
        _active = None
        store.save(session, path)
