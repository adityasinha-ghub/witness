import sample_lib

import witness
from witness import store
from witness.capsule import RaiseOutcome, ReturnOutcome


def _load(tmp_path):
    return store.load(str(tmp_path / ".witness"))


def test_certifies_pure_call(tmp_path):
    with witness.recording(str(tmp_path / ".witness")):
        assert sample_lib.add(2, 3) == 5
    rec = _load(tmp_path)
    assert rec.refusals == []
    assert len(rec.capsules) == 1
    capsule = rec.capsules[0]
    assert capsule.func == "add"
    assert [a.literal for a in capsule.args] == ["2", "3"]
    assert isinstance(capsule.outcome, ReturnOutcome)
    assert capsule.outcome.value.literal == "5"


def test_records_entry_snapshot_not_post_mutation(tmp_path):
    data = [1, 2, 3]
    with witness.recording(str(tmp_path / ".witness")):
        assert sample_lib.append_and_sum(data) == 106
    # The real call still mutated the caller's list — behavior is unchanged.
    assert data == [1, 2, 3, 100]
    rec = _load(tmp_path)
    capsule = rec.capsules[0]
    # But the recorded INPUT is the entry snapshot, not the mutated list.
    assert capsule.args[0].literal == "[1, 2, 3]"
    assert capsule.outcome.value.literal == "106"


def test_nondeterministic_call_refused(tmp_path):
    with witness.recording(str(tmp_path / ".witness")):
        sample_lib.next_id()
    rec = _load(tmp_path)
    assert rec.capsules == []
    assert len(rec.refusals) == 1
    assert "not reproducible" in rec.refusals[0].reason


def test_exception_is_certified(tmp_path):
    with witness.recording(str(tmp_path / ".witness")):
        try:
            sample_lib.divide(1, 0)
        except ZeroDivisionError:
            pass
    rec = _load(tmp_path)
    assert len(rec.capsules) == 1
    outcome = rec.capsules[0].outcome
    assert isinstance(outcome, RaiseOutcome)
    assert outcome.exc_type == "ZeroDivisionError"
    assert outcome.exc_module == "builtins"


def test_container_with_nonreflexive_value_refused(tmp_path):
    # [nan] == [nan] is True on the live objects (identity short-circuit) but the
    # emitted test compares against a fresh copy, where nan != nan — must refuse.
    with witness.recording(str(tmp_path / ".witness")):
        sample_lib.wrap_nan()
    rec = _load(tmp_path)
    assert rec.capsules == []
    assert len(rec.refusals) == 1
    assert "not assertable" in rec.refusals[0].reason


def test_identity_equal_singleton_refused(tmp_path):
    with witness.recording(str(tmp_path / ".witness")):
        sample_lib.get_singleton()
    rec = _load(tmp_path)
    assert rec.capsules == []
    assert "not assertable" in rec.refusals[0].reason


def test_string_set_return_is_certified(tmp_path):
    # Order-independent == reproduces fine even though pickle byte-order may not.
    with witness.recording(str(tmp_path / ".witness")):
        sample_lib.tags("the fox and a dog and the cat")
    rec = _load(tmp_path)
    assert rec.refusals == []
    assert len(rec.capsules) == 1


def test_unpicklable_input_refused(tmp_path):
    with witness.recording(str(tmp_path / ".witness")):
        sample_lib.identity(lambda x: x)
    rec = _load(tmp_path)
    assert rec.capsules == []
    assert len(rec.refusals) == 1
    assert "not picklable" in rec.refusals[0].reason


def test_passthrough_without_active_session():
    # No recording() active — the decorator must not alter behavior.
    assert sample_lib.add(10, 20) == 30
