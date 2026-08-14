import time as _time

import pytest
import target_lib

import witness
from witness import store


def test_auto_capture_records_undecorated_functions(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, targets=["target_lib"]):
        assert target_lib.double(21) == 42
        assert target_lib.greet("ada") == "hi ada"
    rec = store.load(wdir)
    funcs = {c.func for c in rec.capsules}
    assert "double" in funcs
    assert "greet" in funcs


def test_auto_capture_records_nested_target_calls(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, targets=["target_lib"]):
        assert target_lib.compute(10) == 21
    rec = store.load(wdir)
    funcs = {c.func for c in rec.capsules}
    assert "compute" in funcs
    assert "double" in funcs  # called by compute, also captured


def test_reexported_imports_not_wrapped(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, targets=["target_lib"]):
        target_lib.sqrt(16)  # imported from math — must not be captured
    rec = store.load(wdir)
    funcs = {c.func for c in rec.capsules}
    assert "sqrt" not in funcs


def test_bad_target_does_not_corrupt_state(tmp_path):
    # A target that fails to import must restore everything: seams, already-wrapped
    # functions, and _active (so the next recording still works).
    orig_time = _time.time
    orig_double = target_lib.double
    with pytest.raises(ModuleNotFoundError):
        with witness.recording(
            str(tmp_path / ".w"), targets=["target_lib", "definitely_not_a_module_xyz"]
        ):
            pass
    assert _time.time is orig_time  # seams restored
    assert target_lib.double is orig_double  # partial wrapping unwound

    # _active was reset, so a fresh recording works.
    with witness.recording(str(tmp_path / ".w2"), targets=["target_lib"]):
        target_lib.double(3)
    rec = store.load(str(tmp_path / ".w2"))
    assert any(c.func == "double" for c in rec.capsules)


def test_functions_restored_after_recording(tmp_path):
    original = target_lib.double
    with witness.recording(str(tmp_path / ".witness"), targets=["target_lib"]):
        pass
    assert target_lib.double is original
    assert not hasattr(target_lib.double, "__witness_wrapped__")
