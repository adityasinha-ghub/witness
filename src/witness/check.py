"""Cross-version replay-diff — check a recording against the current code.

Re-feeds each recorded call's inputs into the *current* function (with the recorded
clock/RNG/uuid seams replayed, so the comparison is fair) and diffs the fresh
outcome against the recorded one. Neither side is "correct": it reports what
behavior *changed* since the recording, which makes a recording a self-maintaining
regression check — run it in CI and it fails when observed behavior moves.

The verdict is kept consistent with the tests witness *emits*: it compares return
values with the same ``==`` the tests assert, and matches exceptions with
``isinstance`` against the class resolved from the recorded ``(module, qualname)`` —
exactly what ``pytest.raises`` does — so ``check`` never disagrees with the shipped
test about whether the code broke. Any capsule that can't be evaluated (a recorded
value that no longer loads, a module that moved) is reported as *uncheckable*
rather than crashing the run.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from . import schema, triage, value
from .capsule import Capsule, PartialOutcome, ReturnOutcome
from .deps import DepReplay
from .generate import _dedup
from .seams import Replay, WitnessReplayError


@dataclass
class Divergence:
    """One recorded behavior that the current code no longer reproduces."""

    call: str
    before: str
    after: str


@dataclass
class CheckResult:
    unchanged: int = 0
    changed: list[Divergence] = field(default_factory=list)
    drifted: list[Divergence] = field(default_factory=list)  # same value, different shape
    uncheckable: list[tuple[str, str]] = field(default_factory=list)


def check(recording) -> CheckResult:
    """Diff every recorded capsule against the current code."""
    result = CheckResult()
    for capsule in _dedup(recording.capsules):
        _check_one(capsule, result)
    return result


def _check_one(capsule: Capsule, result: CheckResult) -> None:
    qualified = f"{capsule.module}.{capsule.func}"
    if capsule.module == "__main__" or "." in capsule.func:
        result.uncheckable.append((qualified, "not importable (defined in __main__/nested)"))
        return
    try:
        module = importlib.import_module(capsule.module)
        func = getattr(module, capsule.func)
    except (ImportError, AttributeError) as exc:
        result.uncheckable.append((qualified, f"not importable: {exc}"))
        return
    # Call the underlying function, not witness's own recording wrapper.
    func = getattr(func, "__witness_wrapped__", func)

    # Reconstructing recorded values can fail across versions (a class was renamed
    # or removed) — that's a per-capsule "uncheckable", never a crash of the run.
    try:
        args = [value.reconstruct(e) for e in capsule.args]
        kwargs = {k: value.reconstruct(e) for k, e in capsule.kwargs.items()}
        boundary = {
            name: [value.reconstruct(e) for e in encs] for name, encs in capsule.boundary.items()
        }
        dep_tables = {
            name: {key: [value.reconstruct(e) for e in encs] for key, encs in table.items()}
            for name, table in capsule.deps.items()
        }
        call = _call_repr(capsule)
        before = _describe_recorded(capsule.outcome)
    except Exception as exc:  # noqa: BLE001 - any load failure is uncheckable
        result.uncheckable.append((qualified, f"recorded value no longer loads: {exc!r}"))
        return

    try:
        replay = Replay(boundary)
        replay.__enter__()
        dep_replay = DepReplay(dep_tables)
        dep_replay.__enter__()
    except Exception as exc:  # noqa: BLE001 - a seam/dep that won't patch is uncheckable
        replay.__exit__(None, None, None)
        result.uncheckable.append((qualified, f"could not replay recorded seams/deps: {exc!r}"))
        return
    try:
        try:
            current = func(*args, **kwargs)
            current_raised: BaseException | None = None
        except WitnessReplayError:
            after = "reached an unrecorded clock/RNG/dependency call (control flow changed)"
            result.changed.append(Divergence(call, before, after))
            return
        except BaseException as exc:  # noqa: BLE001 - characterize any raise
            current = None
            current_raised = exc
    finally:
        dep_replay.__exit__(None, None, None)
        replay.__exit__(None, None, None)

    if _reproduces(capsule.outcome, current, current_raised):
        drift = _drift(capsule.outcome, current, current_raised)
        if drift is not None:
            result.drifted.append(Divergence(call, drift[0], drift[1]))
        else:
            result.unchanged += 1
    else:
        result.changed.append(Divergence(call, before, _describe_current(current, current_raised)))


def _drift(outcome, current, current_raised) -> tuple[str, str] | None:
    """For an equal return value, (recorded_shape, current_shape) if they differ."""
    if not isinstance(outcome, ReturnOutcome) or current_raised is not None:
        return None
    try:
        recorded_shape = schema.fingerprint(value.reconstruct(outcome.value))
        current_shape = schema.fingerprint(current)
    except Exception:  # noqa: BLE001 - fingerprinting must never break the diff
        return None
    return (recorded_shape, current_shape) if recorded_shape != current_shape else None


def _reproduces(outcome, current, current_raised) -> bool:
    if isinstance(outcome, ReturnOutcome):
        if current_raised is not None:
            return False
        return value.values_equal(current, value.reconstruct(outcome.value))
    if isinstance(outcome, PartialOutcome):
        if current_raised is not None:
            return False
        return triage.partial_matches(outcome, current)
    # RaiseOutcome — match pytest.raises semantics: isinstance against the class
    # resolved from the recorded (module, qualname), so a subclass counts as a match
    # and a same-named class in a different module does not.
    if current_raised is None:
        return False
    recorded_cls = _resolve_exc(outcome.exc_module, outcome.exc_type)
    if recorded_cls is None:
        return False  # the recorded exception class no longer exists → the test would error
    return isinstance(current_raised, recorded_cls)


def _resolve_exc(module_name: str, qualname: str) -> type | None:
    try:
        obj: object = importlib.import_module(module_name)
        for part in qualname.split("."):
            obj = getattr(obj, part)
    except (ImportError, AttributeError):
        return None
    return obj if isinstance(obj, type) else None


def _describe_recorded(outcome) -> str:
    if isinstance(outcome, ReturnOutcome):
        return _short(value.reconstruct(outcome.value))
    if isinstance(outcome, PartialOutcome):
        return "dict{" + ", ".join(repr(k) for k in outcome.keys) + "}"
    return f"raises {outcome.exc_type}"


def _describe_current(current, current_raised) -> str:
    if current_raised is not None:
        return f"raises {type(current_raised).__qualname__}"
    return _short(current)


def _call_repr(capsule: Capsule) -> str:
    parts = []
    for enc in capsule.args:
        parts.append(enc.literal if enc.literal is not None else _short(value.reconstruct(enc)))
    for key, enc in capsule.kwargs.items():
        val = enc.literal if enc.literal is not None else _short(value.reconstruct(enc))
        parts.append(f"{key}={val}")
    return f"{capsule.func}({', '.join(parts)})"


def _short(val: object) -> str:
    try:
        text = repr(val)
    except Exception:  # noqa: BLE001 - a broken __repr__ must not crash the diff
        return "<unrepresentable>"
    return text if len(text) <= 60 else text[:57] + "..."
