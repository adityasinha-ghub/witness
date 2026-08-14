import sample_lib

import witness
from witness import check, generate, store
from witness.capsule import PartialOutcome


def _record_response(tmp_path):
    sample_lib._partial_n["i"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        sample_lib.make_response("alice")
    return store.load(wdir)


def test_partly_volatile_dict_certifies_partially(tmp_path):
    rec = _record_response(tmp_path)
    assert rec.refusals == []
    assert len(rec.capsules) == 1
    outcome = rec.capsules[0].outcome
    assert isinstance(outcome, PartialOutcome)
    assert set(outcome.keys) == {"name", "status", "request_id"}
    exact_keys = {k for k, _ in outcome.exact}
    assert {"name", "status"} <= exact_keys
    type_keys = {k for k, _ in outcome.types}
    assert "request_id" in type_keys  # volatile but stably int


def test_partial_generates_structural_asserts(tmp_path):
    rec = _record_response(tmp_path)
    src = generate.generate(rec.capsules).files["test_witness_sample_lib.py"]
    assert "assert set(result.keys()) == {'name', 'request_id', 'status'}" in src
    assert "assert result['name'] == 'alice'" in src
    assert "assert result['status'] == 'ok'" in src
    assert "assert type(result['request_id']).__name__ == 'int'" in src
    compile(src, "test_witness_sample_lib.py", "exec")


def test_check_partial_unchanged_despite_volatile_field(tmp_path):
    rec = _record_response(tmp_path)
    # request_id differs on the fresh run, but the matcher only checks its type.
    result = check.check(rec)
    assert result.changed == []
    assert result.unchanged == 1


def test_check_partial_detects_a_real_change(tmp_path, monkeypatch):
    rec = _record_response(tmp_path)
    monkeypatch.setattr(
        sample_lib,
        "make_response",
        lambda name: {"name": name, "status": "FAIL", "request_id": 9},
    )
    result = check.check(rec)
    assert len(result.changed) == 1


def test_nonreflexive_stable_field_is_typed_not_asserted_exact(tmp_path):
    # [nan] is stable across samples but != a fresh copy of itself, so it must not
    # become `assert result['payload'] == ...` (which would fail on unchanged code).
    sample_lib._partial_n["i"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        sample_lib.response_with_nan("z")
    rec = store.load(wdir)
    assert rec.refusals == []
    outcome = rec.capsules[0].outcome
    assert isinstance(outcome, PartialOutcome)
    assert "payload" not in {k for k, _ in outcome.exact}
    assert "payload" in {k for k, _ in outcome.types}  # asserted by type instead
    assert "name" in {k for k, _ in outcome.exact}
    # the generated test compiles and asserts the type, not equality
    src = generate.generate(rec.capsules).files["test_witness_sample_lib.py"]
    assert "assert type(result['payload']).__name__ == 'list'" in src
    assert "result['payload'] ==" not in src
    compile(src, "t.py", "exec")


def test_fully_volatile_return_still_refused(tmp_path):
    # No stable field to pin → still refused (not a weak/near-useless test).
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        sample_lib.next_id()  # returns a bare incrementing int, not a dict
    rec = store.load(wdir)
    assert rec.capsules == []
    assert len(rec.refusals) == 1
