"""Content-keyed dependency ledger — record & replay declared dependency functions.

Seams (:mod:`witness.seams`) replay clock/RNG in FIFO order because that's how a
single deterministic run consumes them. Dependencies are different: a call like
``fetch(url_a)`` and ``fetch(url_b)`` must each get *their own* recorded response, so
replay is keyed by the **arguments**, not call order. That's the correctness line
for turning "the world" into a faithful mock: a replayed call whose arguments were
never recorded fails loud rather than serving some other call's answer.

Declare dependency functions with ``recording(deps=["httpx.get", "app.db.query"])``.
During recording each call's ``(args, kwargs) -> return`` is stored keyed by a hash
of the pickled arguments; during certification and in the generated test, the
recorded return is served for a matching-argument call, and an unrecorded call
raises :class:`~witness.seams.WitnessReplayError`.

Same limits as seams: only module-level callables can be patched, and only calls
made *through the module* are seen. The return value (and the arguments) must be
picklable, or the call can't be replayed and the function is refused.
"""

from __future__ import annotations

import hashlib
import importlib
import pickle


def _canonical(obj: object) -> str:
    """A process-stable, order-independent string form of an argument value.

    Sets/frozensets and dict entries are sorted, so the key does not depend on
    ``PYTHONHASHSEED`` (which would otherwise make a generated test compute a
    different key than was recorded and fail on unchanged code). Arbitrary objects
    fall back to a pickle hash, which is only as stable as their pickling.
    """
    if obj is None or isinstance(obj, bool):
        return repr(obj)
    if isinstance(obj, (int, float, complex, str, bytes, bytearray)):
        return repr(obj)
    if isinstance(obj, (list, tuple)):
        return type(obj).__name__ + "(" + ",".join(_canonical(x) for x in obj) + ")"
    if isinstance(obj, (set, frozenset)):
        return type(obj).__name__ + "{" + ",".join(sorted(_canonical(x) for x in obj)) + "}"
    if isinstance(obj, dict):
        return (
            "{"
            + ",".join(sorted(_canonical(k) + ":" + _canonical(v) for k, v in obj.items()))
            + "}"
        )
    return "pickle:" + hashlib.sha256(pickle.dumps(obj)).hexdigest()


def dep_key(args: tuple, kwargs: dict) -> str:
    """A stable, order-independent content hash of a dependency call's arguments."""
    payload = _canonical((tuple(args), dict(kwargs)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_deps(names: list[str] | None) -> list[tuple[str, object, str, object]]:
    """Resolve dependency dotted-names to ``(name, module, attr, original)`` tuples.

    Dependencies are declared explicitly, so an unresolvable name is a loud error
    (unlike best-effort seams) — a silent skip would make the function look
    nondeterministic and be refused with no hint that the name was wrong.
    """
    resolved: list[tuple[str, object, str, object]] = []
    for name in names or []:
        module_name, _, attr = name.rpartition(".")
        if not module_name:
            raise ValueError(f"witness: invalid dependency name '{name}' (expected 'module.func')")
        try:
            module = importlib.import_module(module_name)
            original = getattr(module, attr)
        except (ImportError, AttributeError) as exc:
            raise ValueError(f"witness: could not resolve dependency '{name}': {exc}") from exc
        resolved.append((name, module, attr, original))
    return resolved


# Standalone replay harness embedded in generated tests (no witness import).
DEP_HARNESS = (
    "import hashlib as _hashlib\n"
    "import importlib as _importlib\n"
    "import pickle as _pickle\n"
    "\n"
    "\n"
    "def _canonical(obj):\n"
    "    if obj is None or isinstance(obj, bool):\n"
    "        return repr(obj)\n"
    "    if isinstance(obj, (int, float, complex, str, bytes, bytearray)):\n"
    "        return repr(obj)\n"
    "    if isinstance(obj, (list, tuple)):\n"
    '        return type(obj).__name__ + "(" + ",".join(_canonical(x) for x in obj) + ")"\n'
    "    if isinstance(obj, (set, frozenset)):\n"
    '        return type(obj).__name__ + "{" + ",".join(sorted(_canonical(x) for x in obj)) + "}"\n'
    "    if isinstance(obj, dict):\n"
    '        return "{" + ",".join('
    'sorted(_canonical(k) + ":" + _canonical(v) for k, v in obj.items())) + "}"\n'
    '    return "pickle:" + _hashlib.sha256(_pickle.dumps(obj)).hexdigest()\n'
    "\n"
    "\n"
    "def _dep_key(args, kwargs):\n"
    "    payload = _canonical((tuple(args), dict(kwargs)))\n"
    '    return _hashlib.sha256(payload.encode("utf-8")).hexdigest()\n'
    "\n"
    "\n"
    "class _Deps:\n"
    '    """Replays recorded dependency responses, matched by call arguments."""\n'
    "\n"
    "    def __init__(self, tables):\n"
    "        self._tables = {n: {k: list(v) for k, v in t.items()} for n, t in tables.items()}\n"
    "        self._saved = []\n"
    "\n"
    "    def __enter__(self):\n"
    "        try:\n"
    "            for name, table in self._tables.items():\n"
    '                module_name, _, attr = name.rpartition(".")\n'
    "                module = _importlib.import_module(module_name)\n"
    "                self._saved.append((module, attr, getattr(module, attr)))\n"
    "\n"
    "                def _replay(*a, _table=table, _name=name, **k):\n"
    "                    queue = _table.get(_dep_key(a, k))\n"
    "                    if not queue:\n"
    '                        raise AssertionError("witness: unrecorded call to " + _name)\n'
    "                    return queue.pop(0)\n"
    "\n"
    "                setattr(module, attr, _replay)\n"
    "        except Exception:\n"
    "            self.__exit__(None, None, None)\n"
    "            raise\n"
    "        return self\n"
    "\n"
    "    def __exit__(self, *exc):\n"
    "        for module, attr, original in reversed(self._saved):\n"
    "            setattr(module, attr, original)\n"
    "        return False\n"
)


class DepReplay:
    """Runtime arg-keyed dependency replay (used by ``witness check``)."""

    def __init__(self, tables: dict[str, dict[str, list]]) -> None:
        self._tables = {n: {k: list(v) for k, v in t.items()} for n, t in tables.items()}
        self._saved: list = []

    def __enter__(self) -> DepReplay:
        from .seams import WitnessReplayError

        try:
            for name, table in self._tables.items():
                module_name, _, attr = name.rpartition(".")
                module = importlib.import_module(module_name)
                self._saved.append((module, attr, getattr(module, attr)))

                def _replay(*a, _table=table, _name=name, **k):
                    try:
                        key = dep_key(a, k)
                    except Exception as exc:
                        raise WitnessReplayError(_name) from exc
                    queue = _table.get(key)
                    if not queue:
                        raise WitnessReplayError(_name)
                    return queue.pop(0)

                setattr(module, attr, _replay)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc) -> bool:
        for module, attr, original in reversed(self._saved):
            setattr(module, attr, original)
        return False
