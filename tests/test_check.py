import sample_lib

import witness
from witness import check, store


def _record_add(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        sample_lib.add(2, 3)
    return store.load(wdir)


def test_unchanged_code_reports_no_changes(tmp_path):
    rec = _record_add(tmp_path)
    result = check.check(rec)
    assert result.unchanged == 1
    assert result.changed == []


def test_changed_return_value_is_detected(tmp_path, monkeypatch):
    rec = _record_add(tmp_path)
    # Simulate a code change: add now multiplies.
    monkeypatch.setattr(sample_lib, "add", lambda a, b: a * b)
    result = check.check(rec)
    assert result.unchanged == 0
    assert len(result.changed) == 1
    div = result.changed[0]
    assert div.call == "add(2, 3)"
    assert div.before == "5"
    assert div.after == "6"


def test_return_to_raise_is_detected(tmp_path, monkeypatch):
    rec = _record_add(tmp_path)

    def boom(a, b):
        raise ValueError("changed")

    monkeypatch.setattr(sample_lib, "add", boom)
    result = check.check(rec)
    assert len(result.changed) == 1
    assert result.changed[0].after == "raises ValueError"


def test_raise_to_return_is_detected(tmp_path, monkeypatch):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        try:
            sample_lib.divide(1, 0)
        except ZeroDivisionError:
            pass
    monkeypatch.setattr(sample_lib, "divide", lambda a, b: 0)
    result = check.check(store.load(wdir))
    assert len(result.changed) == 1
    assert result.changed[0].before == "raises ZeroDivisionError"
    assert result.changed[0].after == "0"


def test_exception_subclass_counts_as_unchanged(tmp_path, monkeypatch):
    # pytest.raises(ZeroDivisionError) catches a subclass, so check must too.
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        try:
            sample_lib.divide(1, 0)
        except ZeroDivisionError:
            pass

    class MyZDE(ZeroDivisionError):
        pass

    def raise_sub(a, b):
        raise MyZDE("still a ZeroDivisionError")

    monkeypatch.setattr(sample_lib, "divide", raise_sub)
    result = check.check(store.load(wdir))
    assert result.changed == []
    assert result.unchanged == 1


def test_unrelated_exception_is_changed(tmp_path, monkeypatch):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        try:
            sample_lib.divide(1, 0)
        except ZeroDivisionError:
            pass

    def raise_key(a, b):
        raise KeyError("different")

    monkeypatch.setattr(sample_lib, "divide", raise_key)
    result = check.check(store.load(wdir))
    assert len(result.changed) == 1
    assert result.changed[0].after == "raises KeyError"


def test_check_tolerates_unloadable_capsule(tmp_path, monkeypatch):
    # A recorded value that no longer reconstructs must not crash the whole run.
    rec = _record_add(tmp_path)

    def boom(_enc):
        raise RuntimeError("class went away")

    monkeypatch.setattr(check.value, "reconstruct", boom)
    result = check.check(rec)  # must not raise
    assert result.unchanged == 0
    assert result.changed == []
    assert len(result.uncheckable) == 1


def test_short_survives_broken_repr():
    class Bad:
        def __repr__(self):
            raise RuntimeError("no repr for you")

    assert check._short(Bad()) == "<unrepresentable>"


def test_type_drift_is_reported_separately_not_as_changed(tmp_path, monkeypatch):
    # 5 -> 5.0 is == equal, so it's not "changed" (the test would still pass), but
    # it IS a type drift worth surfacing.
    rec = _record_add(tmp_path)  # add(2, 3) == 5 (int)
    monkeypatch.setattr(sample_lib, "add", lambda a, b: float(a + b))
    result = check.check(rec)
    assert result.unchanged == 0
    assert result.changed == []
    assert len(result.drifted) == 1
    assert "int" in result.drifted[0].before
    assert "float" in result.drifted[0].after


def test_no_drift_reported_for_unchanged_code(tmp_path):
    rec = _record_add(tmp_path)
    result = check.check(rec)
    assert result.drifted == []
    assert result.unchanged == 1


def test_bool_vs_int_is_drift(tmp_path, monkeypatch):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        assert sample_lib.identity(True) is True  # records a bool
    # current returns 1, which == True but is a different type
    monkeypatch.setattr(sample_lib, "identity", lambda x: 1)
    result = check.check(store.load(wdir))
    assert result.changed == []
    assert len(result.drifted) == 1
    assert result.drifted[0].before == "bool"
    assert result.drifted[0].after == "int"


def test_seams_replayed_so_clock_code_is_stable(tmp_path):
    # A clock-reading function must compare as UNCHANGED when re-checked, because
    # the recorded time is replayed rather than read fresh.
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        sample_lib.stamped("build")
    result = check.check(store.load(wdir))
    assert result.changed == []
    assert result.unchanged == 1
