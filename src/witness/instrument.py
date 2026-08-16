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
    """Wrap the top-level functions (and class methods) of each named module.

    Returns an undo list. If a later module can't be imported, everything already
    wrapped is unwound before the error propagates, so a bad target never leaves
    functions patched. Methods are wrapped too (``self`` is captured as the first
    argument); dunders, static/class methods, and inherited methods are left alone.
    """
    undo: Undo = []
    try:
        for name in module_names:
            module = importlib.import_module(name)
            module_name = getattr(module, "__name__", None)
            for attr, obj in list(vars(module).items()):
                if isinstance(obj, types.FunctionType) and _own_top_level(obj, module_name, attr):
                    setattr(module, attr, wrap(obj))
                    undo.append((module, attr, obj))
                elif isinstance(obj, type) and obj.__module__ == module_name:
                    _wrap_methods(obj, module_name, wrap, undo)
    except Exception:
        unwrap(undo)
        raise
    return undo


def _own_top_level(obj, module_name, attr: str) -> bool:
    return (
        obj.__module__ == module_name  # defined here, not imported
        and attr == obj.__name__  # bound under its own name, not an alias
        and "." not in obj.__qualname__  # top-level (not nested/lambda)
        and not hasattr(obj, "__witness_wrapped__")  # not already wrapped
        and not hasattr(obj, "__witness_patched__")  # not a seam/dep wrapper
    )


def _wrap_methods(cls: type, module_name, wrap: Callable, undo: Undo) -> None:
    """Wrap the instance and static methods a class defines itself.

    Instance methods capture ``self`` as the first argument. Static methods have no
    receiver, so they behave exactly like a top-level function under ``Cls.name``.
    ``classmethod`` is left alone (its auto-bound ``cls`` would need special call-
    site handling); dunders, properties, and inherited members are skipped.
    """
    for attr, obj in list(vars(cls).items()):
        if isinstance(obj, types.FunctionType):  # instance method
            func = obj
            rewrap = wrap
        elif isinstance(obj, staticmethod):  # static method
            func = obj.__func__
            rewrap = lambda f: staticmethod(wrap(f))  # noqa: E731
        else:
            continue  # classmethod / property / other descriptors → skip
        if (
            isinstance(func, types.FunctionType)
            and func.__module__ == module_name
            and attr == func.__name__
            and not (attr.startswith("__") and attr.endswith("__"))  # skip dunders
            and not hasattr(func, "__witness_wrapped__")
            and not hasattr(func, "__witness_patched__")
        ):
            setattr(cls, attr, rewrap(func))
            undo.append((cls, attr, obj))


def unwrap(undo: Undo) -> None:
    """Restore everything :func:`wrap_module_functions` replaced."""
    for module, attr, original in reversed(undo):
        setattr(module, attr, original)
