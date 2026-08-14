"""Emit pytest files from certified capsules.

Every emitted test replays the exact inputs witness recorded and asserts the
outcome witness observed *and reproduced* at capture time — so a freshly generated
file passes by construction against unchanged code. Values render as readable
Python literals whenever they round-trip; anything else is carried inline as a
self-contained base64 pickle, so the generated file has no runtime dependency on
witness or on the ``.witness/`` directory.

The target module is imported *aliased* (``import mod as _mod``) and functions are
called as ``_mod.func(...)`` — so a recorded function named ``pytest`` or ``_wv``
can never collide with witness's own helper/import names. Capsules that can't be
emitted honestly (defined in ``__main__``, methods/nested/lambdas, or raising an
exception type that isn't importable) are reported as skipped rather than emitted
as a file that would fail to import.
"""

from __future__ import annotations

import base64
from collections import Counter, defaultdict
from dataclasses import dataclass

from .capsule import Capsule, RaiseOutcome, ReturnOutcome
from .seams import REPLAY_HARNESS
from .value import Encoded

_HELPER = (
    "import base64 as _b64\n"
    "import pickle as _pickle\n"
    "\n"
    "\n"
    "def _wv(data):\n"
    '    """Load a witness fixture that has no readable literal form."""\n'
    "    return _pickle.loads(_b64.b64decode(data))\n"
)


@dataclass
class GenerateResult:
    files: dict[str, str]  # filename -> source
    skipped: list[str]  # qualnames witness could not emit honestly
    test_count: int


def generate(capsules: list[Capsule]) -> GenerateResult:
    """Render deduplicated capsules into pytest source files."""
    by_module: dict[str, list[Capsule]] = defaultdict(list)
    skipped: list[str] = []
    for capsule in _dedup(capsules):
        if capsule.module == "__main__":
            skipped.append(
                f"{capsule.func} (defined in __main__ — import it as a module to generate tests)"
            )
            continue
        if "." in capsule.func:
            skipped.append(f"{capsule.module}.{capsule.func} (method/nested/lambda)")
            continue
        by_module[capsule.module].append(capsule)

    files: dict[str, str] = {}
    total = 0
    for module, caps in sorted(by_module.items()):
        source, count, mod_skipped = _render_module(module, caps)
        skipped.extend(mod_skipped)
        if count:
            files[_filename(module)] = source
            total += count
    return GenerateResult(files=files, skipped=skipped, test_count=total)


def _dedup(capsules: list[Capsule]) -> list[Capsule]:
    """Drop exact duplicate calls (same function, inputs, and outcome)."""
    seen: set = set()
    out: list[Capsule] = []
    for c in capsules:
        outcome_key = (
            ("return", c.outcome.value.hash)
            if isinstance(c.outcome, ReturnOutcome)
            else ("raise", c.outcome.exc_type)
        )
        key = (
            c.module,
            c.func,
            tuple(e.hash for e in c.args),
            tuple(sorted((k, e.hash) for k, e in c.kwargs.items())),
            outcome_key,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _render_value(enc: Encoded) -> tuple[str, bool]:
    """Return (source, needs_helper) for one value."""
    if enc.literal is not None:
        return enc.literal, False
    b64 = base64.b64encode(enc.blob).decode("ascii")
    return f'_wv("{b64}")', True


def _render_boundary(boundary: dict[str, list[Encoded]]) -> tuple[str, bool]:
    """Render the recorded seam queues as a dict literal for the _Replay harness."""
    needs_helper = False
    parts = []
    for name, encs in boundary.items():
        rendered = []
        for enc in encs:
            src, helper = _render_value(enc)
            needs_helper |= helper
            rendered.append(src)
        parts.append(f"{name!r}: [{', '.join(rendered)}]")
    return "{" + ", ".join(parts) + "}", needs_helper


def _exc_ref(outcome: RaiseOutcome, module: str, alias_for) -> str | None:
    """A source reference to the exception class, or None if not importable."""
    if outcome.exc_module == "builtins":
        return outcome.exc_type  # builtins are always in scope
    if outcome.exc_module == "__main__":
        return None  # can't be re-imported when the test later runs
    if outcome.exc_module == module:
        return f"_mod.{outcome.exc_type}"  # dotted qualname resolves nested classes
    return f"{alias_for(outcome.exc_module)}.{outcome.exc_type}"


def _render_module(module: str, caps: list[Capsule]) -> tuple[str, int, list[str]]:
    body: list[str] = []
    counters: Counter = Counter()
    needs_pytest = False
    needs_helper = False
    needs_replay = False
    skipped: list[str] = []
    exc_aliases: dict[str, str] = {}

    def alias_for(exc_module: str) -> str:
        if exc_module not in exc_aliases:
            exc_aliases[exc_module] = f"_exc{len(exc_aliases)}"
        return exc_aliases[exc_module]

    for capsule in caps:
        call_parts: list[str] = []
        for enc in capsule.args:
            src, helper = _render_value(enc)
            needs_helper |= helper
            call_parts.append(src)
        for key, enc in capsule.kwargs.items():
            src, helper = _render_value(enc)
            needs_helper |= helper
            call_parts.append(f"{key}={src}")
        call = f"_mod.{capsule.func}({', '.join(call_parts)})"

        # If the call read the clock/RNG/uuid, wrap it so those are replayed.
        replay_prefix, base_indent = "", "    "
        if capsule.boundary:
            queues_src, helper = _render_boundary(capsule.boundary)
            needs_helper |= helper
            needs_replay = True
            replay_prefix = f"    with _Replay({queues_src}):\n"
            base_indent = "        "

        if isinstance(capsule.outcome, RaiseOutcome):
            ref = _exc_ref(capsule.outcome, module, alias_for)
            if ref is None:
                skipped.append(
                    f"{module}.{capsule.func} (raises {capsule.outcome.exc_type} "
                    f"from {capsule.outcome.exc_module}, not importable)"
                )
                continue
            needs_pytest = True
            name = f"test_{capsule.func}_{counters[capsule.func]}"
            counters[capsule.func] += 1
            body.append(
                f"def {name}():\n"
                f"{replay_prefix}"
                f"{base_indent}with pytest.raises({ref}):\n"
                f"{base_indent}    {call}\n"
            )
        else:
            expected, helper = _render_value(capsule.outcome.value)
            needs_helper |= helper
            name = f"test_{capsule.func}_{counters[capsule.func]}"
            counters[capsule.func] += 1
            body.append(
                f"def {name}():\n"
                f"{replay_prefix}"
                f"{base_indent}result = {call}\n"
                f"    assert result == {expected}\n"
            )

    if not body:
        return "", 0, skipped

    imports = [f"import {module} as _mod"]
    if needs_pytest:
        imports.append("import pytest")
    for exc_module, alias in exc_aliases.items():
        imports.append(f"import {exc_module} as {alias}")

    header = (
        '"""Generated by witness — do not edit by hand.\n'
        "\n"
        f"Each test replays inputs witness recorded from a real run of `{module}` and\n"
        "asserts the output witness observed and reproduced at capture time.\n"
        '"""'
    )
    blocks = [header, "\n".join(imports)]
    if needs_helper:
        blocks.append(_HELPER.rstrip())
    if needs_replay:
        blocks.append(REPLAY_HARNESS.rstrip())
    blocks.extend(b.rstrip() for b in body)
    source = "\n\n\n".join(blocks).rstrip() + "\n"
    return source, len(body), skipped


def _filename(module: str) -> str:
    return "test_witness_" + module.replace(".", "_") + ".py"
