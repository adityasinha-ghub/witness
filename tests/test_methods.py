import ast

import sample_lib

import witness
from witness import check, generate, store


def _record_cart(tmp_path):
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, targets=["sample_lib"]):
        cart = sample_lib.Cart(0.1)
        cart.add(100)
        cart.add(50)
        cart.total()
    return store.load(wdir)


def test_methods_are_captured(tmp_path):
    rec = _record_cart(tmp_path)
    funcs = {c.func for c in rec.capsules}
    assert "Cart.add" in funcs
    assert "Cart.total" in funcs
    # dunders (__init__) are not wrapped
    assert not any(c.func == "Cart.__init__" for c in rec.capsules)


def test_method_records_self_as_first_arg(tmp_path):
    rec = _record_cart(tmp_path)
    total = next(c for c in rec.capsules if c.func == "Cart.total")
    assert len(total.args) == 1  # self only
    # total() over items [100, 50] with 10% off = 135.0
    assert total.outcome.value.literal == "135.0"


def test_generated_method_test_is_valid(tmp_path):
    rec = _record_cart(tmp_path)
    src = generate.generate(rec.capsules).files["test_witness_sample_lib.py"]
    assert "def test_Cart_total_0():" in src
    assert "_mod.Cart.total(" in src
    assert "assert result == 135.0" in src
    compile(src, "t.py", "exec")


def test_check_replays_methods(tmp_path):
    rec = _record_cart(tmp_path)
    result = check.check(rec)
    assert result.changed == []
    assert result.unchanged == len(rec.capsules)


def test_method_and_function_test_names_do_not_collide(tmp_path):
    # Cart.total sanitizes to test_Cart_total_0; so does the function Cart_total.
    # Both must be emitted with distinct names, not silently dropped.
    wdir = str(tmp_path / ".witness")
    with witness.recording(wdir, targets=["sample_lib"]):
        cart = sample_lib.Cart(0.0)
        cart.add(10)
        cart.total()
        sample_lib.Cart_total(5)
    rec = store.load(wdir)
    src = generate.generate(rec.capsules).files["test_witness_sample_lib.py"]
    names = [
        n.name
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    ]
    assert len(names) == len(set(names))  # no collisions → nothing dropped
    assert len(names) == 3  # Cart.add, Cart.total, Cart_total
    compile(src, "t.py", "exec")


def test_check_detects_method_change(tmp_path, monkeypatch):
    rec = _record_cart(tmp_path)
    # Change the discount math: total now ignores the discount.
    monkeypatch.setattr(sample_lib.Cart, "total", lambda self: sum(self.items))
    result = check.check(rec)
    assert any("Cart.total" in d.call or d.after != d.before for d in result.changed)
    assert len(result.changed) >= 1
