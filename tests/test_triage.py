import sample_lib

import witness
from witness import check, generate, store
from witness.capsule import PartialOutcome
from witness.matcher import DictMatch, Exact, OfType, SeqMatch


def _record(tmp_path, call):
    sample_lib._partial_n["i"] = 0
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        call()
    return store.load(wdir)


def _src(rec):
    return generate.generate(rec.capsules).files["test_witness_sample_lib.py"]


def test_partly_volatile_dict_certifies_partially(tmp_path):
    rec = _record(tmp_path, lambda: sample_lib.make_response("alice"))
    assert rec.refusals == []
    outcome = rec.capsules[0].outcome
    assert isinstance(outcome, PartialOutcome)
    m = outcome.matcher
    assert isinstance(m, DictMatch)
    assert set(m.keys) == {"name", "status", "request_id"}
    fields = dict(m.fields)
    assert isinstance(fields["name"], Exact)
    assert isinstance(fields["status"], Exact)
    assert isinstance(fields["request_id"], OfType) and fields["request_id"].type_name == "int"

    src = _src(rec)
    assert "assert set(result.keys()) == {'name', 'request_id', 'status'}" in src
    assert "assert result['status'] == 'ok'" in src
    assert "assert type(result['request_id']).__name__ == 'int'" in src
    compile(src, "t.py", "exec")


def test_nonreflexive_value_is_not_asserted_exact(tmp_path):
    # [nan] is stable but != a fresh copy of itself, so it must never become an
    # exact assertion. Nested triage descends into the list and asserts its shape +
    # the element type instead.
    rec = _record(tmp_path, lambda: sample_lib.response_with_nan("z"))
    fields = dict(rec.capsules[0].outcome.matcher.fields)
    assert isinstance(fields["payload"], SeqMatch)  # recursed into [nan]
    assert isinstance(fields["payload"].items[0], OfType)  # the nan → type, not exact
    assert isinstance(fields["name"], Exact)
    src = _src(rec)
    assert "assert type(result['payload'][0]).__name__ == 'float'" in src
    assert "result['payload'] ==" not in src  # nan never asserted by value
    compile(src, "t.py", "exec")


def test_nested_dict_triage(tmp_path):
    rec = _record(tmp_path, lambda: sample_lib.nested_response("alice"))
    assert rec.refusals == []
    m = rec.capsules[0].outcome.matcher
    user = dict(m.fields)["user"]
    assert isinstance(user, DictMatch)
    assert isinstance(dict(user.fields)["name"], Exact)
    assert isinstance(dict(user.fields)["session"], OfType)

    src = _src(rec)
    assert "assert set(result['user'].keys()) == {'name', 'session'}" in src
    assert "assert result['user']['name'] == 'alice'" in src
    assert "assert type(result['user']['session']).__name__ == 'int'" in src
    compile(src, "t.py", "exec")


def test_list_triage(tmp_path):
    rec = _record(tmp_path, lambda: sample_lib.pair("alice"))
    m = rec.capsules[0].outcome.matcher
    assert isinstance(m, SeqMatch) and m.kind == "list"
    assert isinstance(m.items[0], Exact)
    assert isinstance(m.items[1], OfType)
    src = _src(rec)
    assert "assert isinstance(result, list)" in src
    assert "assert len(result) == 2" in src
    assert "assert result[0] == 'alice'" in src
    assert "assert type(result[1]).__name__ == 'int'" in src
    compile(src, "t.py", "exec")


def test_check_partial_unchanged_despite_volatile_field(tmp_path):
    rec = _record(tmp_path, lambda: sample_lib.make_response("x"))
    result = check.check(rec)
    assert result.changed == []
    assert result.unchanged == 1


def test_check_partial_detects_a_real_change(tmp_path, monkeypatch):
    rec = _record(tmp_path, lambda: sample_lib.make_response("x"))
    monkeypatch.setattr(
        sample_lib,
        "make_response",
        lambda name: {"name": name, "status": "FAIL", "request_id": 9},
    )
    result = check.check(rec)
    assert len(result.changed) == 1


def test_fully_volatile_return_still_refused(tmp_path):
    rec = _record(tmp_path, lambda: sample_lib.next_id())  # bare varying int, not a dict
    assert rec.capsules == []
    assert len(rec.refusals) == 1


def test_cyclic_return_does_not_recurse_forever(tmp_path):
    # A self-referential dict must terminate (depth cap), certify, and emit valid code.
    rec = _record(tmp_path, lambda: sample_lib.cyclic("alice"))
    assert rec.refusals == []
    assert len(rec.capsules) == 1
    compile(_src(rec), "t.py", "exec")


def test_partial_survives_store_round_trip(tmp_path):
    # A nested matcher persists and reloads, and still evaluates correctly.
    _record(tmp_path, lambda: sample_lib.nested_response("alice"))
    reloaded = store.load(str(tmp_path / ".witness"))
    result = check.check(reloaded)
    assert result.changed == []
    assert result.unchanged == 1
