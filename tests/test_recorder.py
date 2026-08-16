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


def test_random_seam_recorded_and_certified(tmp_path):
    # A function reading the RNG used to be refused; now the drawn value is
    # recorded and replayed, so it certifies.
    with witness.recording(str(tmp_path / ".witness")):
        result = sample_lib.jittered(100)
    assert 101 <= result <= 200
    rec = _load(tmp_path)
    assert rec.refusals == []
    assert len(rec.capsules) == 1
    capsule = rec.capsules[0]
    assert "random.randint" in capsule.boundary
    assert len(capsule.boundary["random.randint"]) == 1


def test_clock_seam_recorded_and_certified(tmp_path):
    with witness.recording(str(tmp_path / ".witness")):
        sample_lib.stamped("build")
    rec = _load(tmp_path)
    assert rec.refusals == []
    assert len(rec.capsules) == 1
    assert "time.time" in rec.capsules[0].boundary


def test_nested_record_with_seams_certifies(tmp_path):
    # A deterministic function that calls a seam-using @record function must not be
    # wrongly refused (the inner call's draws must not consume the outer's queue).
    with witness.recording(str(tmp_path / ".witness")):
        assert sample_lib.outer_calls_inner() == 8
    rec = _load(tmp_path)
    certified = {c.func for c in rec.capsules}
    assert "outer_calls_inner" in certified
    assert "inner_seam" in certified
    # The outer capsule records the inner call's seam draw transitively, so the
    # emitted test / check (which run the whole outer call) replay it in order.
    outer = next(c for c in rec.capsules if c.func == "outer_calls_inner")
    assert "random.random" in outer.boundary


def test_certification_uses_multiple_samples(tmp_path):
    sample_lib._invocations["n"] = 0
    with witness.recording(str(tmp_path / ".witness"), samples=5):
        sample_lib.const_but_counts()
    rec = _load(tmp_path)
    assert len(rec.capsules) == 1
    # 1 original call + 5 certification re-invocations
    assert sample_lib._invocations["n"] == 6


def test_seams_restored_after_recording(tmp_path):
    import time as _t

    original = _t.time
    with witness.recording(str(tmp_path / ".witness")):
        pass
    assert _t.time is original  # patches are cleanly removed on exit


def test_passthrough_without_active_session():
    # No recording() active — the decorator must not alter behavior.
    assert sample_lib.add(10, 20) == 30
