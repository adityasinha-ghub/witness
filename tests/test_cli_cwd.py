"""`witness check` must import the project's own modules from the current directory.

Reproduces the installed-console-script condition (cwd not on sys.path) and confirms
`_check` re-adds it, so the module gets imported and checked rather than reported
uncheckable.
"""

import importlib
import sys

import witness
from witness import cli


def test_check_imports_modules_from_the_current_directory(tmp_path, monkeypatch):
    (tmp_path / "wproj.py").write_text("def bump(x):\n    return x + 1\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))  # to record
    wproj = importlib.import_module("wproj")
    with witness.recording(".witness", targets=["wproj"]):
        assert wproj.bump(1) == 2

    # Simulate the installed CLI: cwd not on sys.path, module not cached.
    monkeypatch.setattr(
        sys, "path", [p for p in sys.path if p not in ("", str(tmp_path), str(tmp_path.resolve()))]
    )
    sys.modules.pop("wproj", None)

    rc = cli._check(".witness")
    assert rc == 0
    assert "wproj" in sys.modules  # _check re-added cwd and imported the project module
