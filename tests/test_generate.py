import sample_lib

import witness
from witness import generate, store


def _record(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        sample_lib.add(2, 3)
        sample_lib.normalize("  Hello  ")
        sample_lib.append_and_sum([1, 2, 3])
        try:
            sample_lib.divide(1, 0)
        except ZeroDivisionError:
            pass
    return store.load(wdir)


def test_generate_valid_passing_source(tmp_path):
    rec = _record(tmp_path)
    result = generate.generate(rec.capsules)

    fname = "test_witness_sample_lib.py"
    assert fname in result.files
    src = result.files[fname]

    assert "import sample_lib as _mod" in src
    assert "import pytest" in src
    assert "with pytest.raises(ZeroDivisionError):" in src
    assert "result = _mod.add(2, 3)" in src
    assert "assert result == 5" in src
    assert "assert result == 'hello'" in src
    # entry-snapshot input, not the mutated list
    assert "_mod.append_and_sum([1, 2, 3])" in src
    assert "assert result == 106" in src

    compile(src, fname, "exec")  # must be syntactically valid Python


def test_dedup_collapses_identical_calls(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        for _ in range(5):
            sample_lib.add(1, 1)
    rec = store.load(wdir)
    assert len(rec.capsules) == 5  # every call is recorded
    result = generate.generate(rec.capsules)
    assert result.test_count == 1  # but identical ones collapse to one test


def test_seam_replay_harness_emitted(tmp_path):
    import sample_lib

    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        sample_lib.jittered(100)
    rec = store.load(wdir)
    result = generate.generate(rec.capsules)
    src = result.files["test_witness_sample_lib.py"]
    assert "class _Replay:" in src
    assert "with _Replay({'random.randint': [" in src
    assert "result = _mod.jittered(100)" in src
    compile(src, "test_witness_sample_lib.py", "exec")


def test_reserved_name_collision_is_safe(tmp_path):
    import collide_lib

    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        collide_lib._wv(1)
        collide_lib.pytest(3)
    rec = store.load(wdir)
    result = generate.generate(rec.capsules)
    src = result.files["test_witness_collide_lib.py"]
    # functions are namespaced under _mod, so no collision with helper/import names
    assert "import collide_lib as _mod" in src
    assert "_mod._wv(1)" in src
    assert "_mod.pytest(3)" in src
    compile(src, "test_witness_collide_lib.py", "exec")


def test_skips_non_top_level(tmp_path):
    def local_fn(x):
        return x

    wrapped = witness.record(local_fn)
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir):
        wrapped(5)
    rec = store.load(wdir)
    result = generate.generate(rec.capsules)
    # qualname contains '.<locals>.' → not emitted, reported as skipped
    assert result.files == {}
    assert any("local_fn" in s for s in result.skipped)
