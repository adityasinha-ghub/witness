"""Auto-instrument whole modules, so you don't decorate each function by hand.

The legacy-code path: point witness at a module (or a few) and every top-level
function *defined in that module* is wrapped with :func:`witness.record` for the
duration of the recording, then restored. This reuses the entire capture pipeline —
entry-snapshot, seam recording, certification — with no new capture logic.

Only functions **defined in** the target module (`__module__` matches) and bound
under their own name are wrapped, so re-exported imports aren't double-counted or
mis-attributed. Methods/nested functions are left alone (witness emits top-level
functions only). Same monkeypatch caveat as seams: a call through a reference bound
before instrumentation won't be seen.
"""

from __future__ import annotations

import importlib
import types
from collections.abc import Callable

Undo = list[tuple[object, str, object]]


def wrap_module_functions(module_names: list[str], wrap: Callable) -> Undo:
    """Wrap the top-level functions of each named module; return an undo list.

    If a later module can't be imported, everything already wrapped is unwound
    before the error propagates, so a bad target never leaves functions patched.
    """
    undo: Undo = []
    try:
        for name in module_names:
            module = importlib.import_module(name)
            module_name = getattr(module, "__name__", None)
            for attr, obj in list(vars(module).items()):
                if (
                    isinstance(obj, types.FunctionType)
                    and obj.__module__ == module_name  # defined here, not imported
                    and attr == obj.__name__  # bound under its own name, not an alias
                    and "." not in obj.__qualname__  # top-level (what witness emits)
                    and not hasattr(obj, "__witness_wrapped__")  # not already wrapped
                ):
                    setattr(module, attr, wrap(obj))
                    undo.append((module, attr, obj))
    except Exception:
        unwrap(undo)
        raise
    return undo


def unwrap(undo: Undo) -> None:
    """Restore everything :func:`wrap_module_functions` replaced."""
    for module, attr, original in reversed(undo):
        setattr(module, attr, original)
