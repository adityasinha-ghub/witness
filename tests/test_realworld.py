"""Dogfood witness against a real stdlib module (not toy code).

Records `textwrap`, generates tests, then *executes* the generated assertions
against the real library — a continuous guard that witness produces passing tests
on genuine, non-trivial code (including auto-captured `TextWrapper` methods).
"""

import textwrap

import witness
from witness import check, generate, store


def test_witness_produces_passing_tests_for_stdlib_textwrap(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, targets=["textwrap"]):
        textwrap.fill("the quick brown fox jumps over", width=12)
        textwrap.wrap("hello world foo bar baz", width=8)
        textwrap.shorten("a b c d e f g h i", width=10)
        textwrap.indent("line one\nline two\n", "> ")

    rec = store.load(wdir)
    funcs = {c.func for c in rec.capsules}
    assert {"fill", "wrap", "shorten", "indent"} <= funcs

    # Generate and actually run the emitted assertions against real textwrap.
    src = generate.generate(rec.capsules).files["test_witness_textwrap.py"]
    namespace: dict = {}
    exec(compile(src, "test_witness_textwrap.py", "exec"), namespace)  # noqa: S102
    ran = 0
    for key, value in namespace.items():
        if key.startswith("test_") and callable(value):
            value()  # real assertions vs real textwrap — must not raise
            ran += 1
    assert ran >= 4

    # And the regression oracle agrees the (unchanged) library is unchanged.
    assert check.check(rec).changed == []
