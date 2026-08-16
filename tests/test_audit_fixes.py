"""Regression tests for the whole-project adversarial audit findings.

Each guards a confirmed bug the audit reproduced (a generated test that failed on
unchanged code, or `check` disagreeing with the shipped test).
"""

import os
import subprocess
import sys

import dep_lib
import sample_lib

import witness
from witness import check, generate, store


def _run_generated(rec, filename):
    """Exec the generated file and run its test functions; they must not raise."""
    src = generate.generate(rec.capsules).files[filename]
    ns: dict = {}
    exec(compile(src, filename, "exec"), ns)  # noqa: S102
    ran = 0
    for key, value in ns.items():
        if key.startswith("test_") and callable(value):
            value()
            ran += 1
    return src, ran


def test_f1_nested_seam_draws(tmp_path):
    # Caller and callee both draw a seam: the outer test used to crash (IndexError)
    # and check used to false-fail. Now the outer capsule records both draws in order.
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, targets=["sample_lib"]):
        assert sample_lib.outer_clock(5) == 10
    rec = store.load(wdir)
    assert rec.refusals == []
    outer = next(c for c in rec.capsules if c.func == "outer_clock")
    assert len(outer.boundary["time.time"]) == 2  # its own draw + the callee's
    _, ran = _run_generated(rec, "test_witness_sample_lib.py")
    assert ran >= 1
    assert check.check(rec).changed == []


def test_f2_set_in_object_dep_key_is_process_stable():
    # A set nested in a custom object must produce the same dep key across processes.
    code = (
        "import witness.deps as d\n"
        "class Cfg:\n"
        "    def __init__(self, t): self.tags=set(t)\n"
        "print(d.dep_key((Cfg(['alpha','beta','gamma','delta','epsilon']),), {}))\n"
    )
    keys = set()
    for seed in ("0", "1", "42"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": os.pathsep.join(sys.path)}
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        keys.add(out.stdout.strip())
    assert len(keys) == 1


def test_f2_set_in_object_dep_certifies(tmp_path):
    dep_lib._calls["n"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, deps=["dep_lib._cfg_fetch"]):
        dep_lib.summarize_cfg(["b", "a", "c"])
    rec = store.load(wdir)
    assert rec.refusals == []
    assert len(rec.capsules) == 1


def test_f3_generated_uses_eq_not_is_for_singletons(tmp_path):
    # generate must use `==` (like check), not `is`, or the two disagree on True/1.
    sample_lib._partial_n["i"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        sample_lib.flagged(1)
    rec = store.load(wdir)
    src = generate.generate(rec.capsules).files["test_witness_sample_lib.py"]
    assert "== True" in src
    assert "is True" not in src


def test_f4_weird_kwargs_generate_valid_python(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, targets=["sample_lib"]):
        sample_lib.kw_echo(**{"weird-key": 3, "class": 4, "ok": 5})
    rec = store.load(wdir)
    src, ran = _run_generated(rec, "test_witness_sample_lib.py")
    assert "**{" in src  # non-identifier/keyword kwargs routed through a dict splat
    assert ran >= 1


def test_f5_locals_exception_is_refused(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, targets=["sample_lib"]):
        try:
            sample_lib.raise_local(5)
        except sample_lib.LocalError:
            pass
    rec = store.load(wdir)
    assert not any(c.func == "raise_local" for c in rec.capsules)
    assert any("local scope" in r.reason for r in rec.refusals)
