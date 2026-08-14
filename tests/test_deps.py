import os
import subprocess
import sys

import dep_lib

import witness
from witness import check, generate, store


def test_dependency_recorded_and_certified(tmp_path):
    dep_lib._calls["n"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, deps=["dep_lib._fetch"]):
        assert dep_lib.load_title("http://a") == "HTTP://A#RESP1"
    rec = store.load(wdir)
    assert rec.refusals == []
    assert len(rec.capsules) == 1
    assert "dep_lib._fetch" in rec.capsules[0].deps


def test_without_dep_recording_the_call_is_refused(tmp_path):
    dep_lib._calls["n"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):  # _fetch not recorded → nondeterministic → refused
        dep_lib.load_title("http://a")
    rec = store.load(wdir)
    assert rec.capsules == []
    assert len(rec.refusals) == 1


def test_deps_matched_by_argument(tmp_path):
    dep_lib._calls["n"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, deps=["dep_lib._fetch"]):
        a = dep_lib.load_title("http://a")
        b = dep_lib.load_title("http://b")
    assert a == "HTTP://A#RESP1"
    assert b == "HTTP://B#RESP2"  # different URL → its own recorded response
    rec = store.load(wdir)
    assert len(rec.capsules) == 2


def test_check_replays_deps(tmp_path):
    dep_lib._calls["n"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, deps=["dep_lib._fetch"]):
        dep_lib.load_title("http://a")
    # Re-checking must replay the recorded response (not call _fetch fresh), so the
    # dependency-using function reads as unchanged.
    result = check.check(store.load(wdir))
    assert result.changed == []
    assert result.unchanged == 1


def test_dep_key_is_stable_across_hash_seeds():
    # The generated test recomputes the key in a fresh process; a set argument must
    # hash identically regardless of PYTHONHASHSEED, or the test would miss and fail.
    args_repr = "((set(['alpha', 'beta', 'gamma', 'delta', 'epsilon']),), {})"
    code = f"import witness.deps as d\na, k = {args_repr}\nprint(d.dep_key(a, k))\n"
    keys = set()
    for seed in ("0", "1", "42"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": os.pathsep.join(sys.path)}
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        keys.add(out.stdout.strip())
    assert len(keys) == 1  # identical across all seeds


def test_set_argument_to_dependency_certifies(tmp_path):
    # A set passed directly as a dep argument must certify (canonical key is stable
    # across the pickle round-trip too), not be falsely refused.
    dep_lib._calls["n"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, deps=["dep_lib._lookup"]):
        dep_lib.summarize(["a", "b", "c", "a"])
    rec = store.load(wdir)
    assert rec.refusals == []
    assert len(rec.capsules) == 1


def test_unresolvable_dep_name_raises_clearly(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="could not resolve dependency"):
        with witness.recording(str(tmp_path / ".witness"), deps=["dep_lib.does_not_exist"]):
            pass
    # and state is not corrupted — a subsequent recording works
    with witness.recording(str(tmp_path / ".witness2")):
        dep_lib.load_title  # no-op; just proves recording() enters cleanly


def test_generated_dep_test_is_valid(tmp_path):
    dep_lib._calls["n"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, deps=["dep_lib._fetch"]):
        dep_lib.load_title("http://a")
    rec = store.load(wdir)
    result = generate.generate(rec.capsules)
    src = result.files["test_witness_dep_lib.py"]
    assert "_Deps(" in src
    assert "class _Deps:" in src
    compile(src, "test_witness_dep_lib.py", "exec")
