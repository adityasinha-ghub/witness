"""Nondeterminism *seams* — the boundary ledger, v0 slice.

A "seam" is a well-known source of nondeterminism a function reads from: the clock,
the RNG, uuid generation. During recording, witness patches these module-level
functions and logs the value each call returned, tagged to the recorded call in
flight. During certification (and in the generated test) those recorded values are
**replayed** instead of drawn fresh — so a function that reads the clock or random
becomes reproducible and its test becomes hermetic, instead of being refused.

Scope and honest limits:
- Only module-level functions can be patched. ``datetime.datetime.now()`` is a
  method on a C type whose attributes can't be reassigned, so it is **not** covered
  (use ``time.time()`` or record via a wrapper). DB/network/filesystem interception
  is a later, larger slice.
- Patching replaces *module attributes*, so a value bound before recording via
  ``from time import time`` won't be seen — call through the module (``time.time()``).
- Single-threaded model (matches the rest of v0).
"""

from __future__ import annotations

import importlib

# Module-level, picklable-returning nondeterminism sources we can safely patch.
DEFAULT_SEAMS: list[str] = [
    "time.time",
    "time.time_ns",
    "time.monotonic",
    "time.monotonic_ns",
    "time.perf_counter",
    "time.perf_counter_ns",
    "random.random",
    "random.randint",
    "random.randrange",
    "random.uniform",
    "random.choice",
    "random.getrandbits",
    "uuid.uuid1",
    "uuid.uuid4",
]


class WitnessReplayError(Exception):
    """A replayed seam ran out of recorded values — execution diverged from the record."""


class Replay:
    """Runtime replay of recorded seam values (used by ``witness check``).

    Patches each named seam to hand back its recorded values in order; a draw past
    the end raises :class:`WitnessReplayError` (the code now draws more than it did
    when recorded). Mirrors the standalone ``REPLAY_HARNESS`` emitted into tests.
    """

    def __init__(self, queues: dict[str, list]) -> None:
        self._queues = {name: list(values) for name, values in queues.items()}
        self._saved: list = []

    def __enter__(self) -> Replay:
        try:
            for name, values in self._queues.items():
                module_name, _, attr = name.rpartition(".")
                module = importlib.import_module(module_name)
                self._saved.append((module, attr, getattr(module, attr)))
                queue = list(values)

                def _replay(*a, _q=queue, _name=name, **k):
                    if not _q:
                        raise WitnessReplayError(_name)
                    return _q.pop(0)

                setattr(module, attr, _replay)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc) -> bool:
        for module, attr, original in reversed(self._saved):
            setattr(module, attr, original)
        return False


def resolve_seams(names: list[str] | None) -> list[tuple[str, object, str, object]]:
    """Resolve seam dotted-names to ``(name, module, attr, original)`` tuples.

    Names whose module can't be imported or whose attribute is missing are skipped
    (so an environment without, say, a given module simply doesn't patch it).
    """
    resolved: list[tuple[str, object, str, object]] = []
    for name in names if names is not None else DEFAULT_SEAMS:
        module_name, _, attr = name.rpartition(".")
        if not module_name:
            continue
        try:
            module = importlib.import_module(module_name)
            original = getattr(module, attr)
        except (ImportError, AttributeError):
            continue
        resolved.append((name, module, attr, original))
    return resolved


# The replay harness embedded in generated tests — standalone, no witness import.
REPLAY_HARNESS = (
    "import importlib as _importlib\n"
    "\n"
    "\n"
    "class _Replay:\n"
    '    """Replays the recorded values for the nondeterminism seams a call used."""\n'
    "\n"
    "    def __init__(self, queues):\n"
    "        self._queues = queues\n"
    "        self._saved = []\n"
    "\n"
    "    def __enter__(self):\n"
    "        try:\n"
    "            for name, values in self._queues.items():\n"
    '                module_name, _, attr = name.rpartition(".")\n'
    "                module = _importlib.import_module(module_name)\n"
    "                self._saved.append((module, attr, getattr(module, attr)))\n"
    "                queue = list(values)\n"
    "                setattr(module, attr, lambda *a, _q=queue, **k: _q.pop(0))\n"
    "        except Exception:\n"
    "            self.__exit__(None, None, None)  # restore anything already patched\n"
    "            raise\n"
    "        return self\n"
    "\n"
    "    def __exit__(self, *exc):\n"
    "        for module, attr, original in reversed(self._saved):\n"
    "            setattr(module, attr, original)\n"
    "        return False\n"
)
