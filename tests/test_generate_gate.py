"""The emission gate: witness must never write a test file that doesn't parse."""

import ast

import sample_lib

import witness
from witness import generate, store


def test_gate_drops_unparseable_capsule_and_ships_the_rest(tmp_path, monkeypatch):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        sample_lib.add(2, 3)
        sample_lib.normalize("Hi")
    rec = store.load(wdir)

    # Poison the rendering of just the `add` test so it becomes invalid Python.
    real = generate._render_test

    def poisoned(name, withs, call, ref, asserts):
        src = real(name, withs, call, ref, asserts)
        return src.replace("result =", "result = = =") if "add" in name else src

    monkeypatch.setattr(generate, "_render_test", poisoned)

    result = generate.generate(rec.capsules)
    src = result.files["test_witness_sample_lib.py"]

    ast.parse(src)  # the shipped file parses...
    assert "def test_normalize_0" in src  # ...the good capsule survived...
    assert "def test_add_0" not in src  # ...and the poisoned one was dropped...
    assert any("add" in s and "not valid Python" in s for s in result.skipped)  # with a reason
