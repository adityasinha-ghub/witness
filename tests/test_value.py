import math

import pytest

from witness import value
from witness.value import EncodeError


@pytest.mark.parametrize(
    "val, expected_literal",
    [
        (5, "5"),
        (-3, "-3"),
        (True, "True"),
        (False, "False"),
        (None, "None"),
        (1.5, "1.5"),
        ("hi", "'hi'"),
        (b"by", "b'by'"),
        ([1, 2, 3], "[1, 2, 3]"),
        ((1, 2), "(1, 2)"),
        ((7,), "(7,)"),
        ({"a": 1, "b": [2, 3]}, "{'a': 1, 'b': [2, 3]}"),
    ],
)
def test_literal_round_trips(val, expected_literal):
    enc = value.encode(val)
    assert enc.literal == expected_literal
    assert value.reconstruct(enc) == val


def test_empty_containers():
    assert value.encode(set()).literal == "set()"
    assert value.encode(frozenset()).literal == "frozenset()"
    assert value.encode([]).literal == "[]"
    assert value.encode({}).literal == "{}"


def test_set_literal_reconstructs():
    enc = value.encode({1, 2, 3})
    assert value.reconstruct(enc) == {1, 2, 3}
    # rendered literal must eval back to the same set
    assert eval(enc.literal) == {1, 2, 3}


def test_nonfinite_float_has_no_literal_but_still_encodes():
    enc = value.encode(float("nan"))
    assert enc.literal is None  # 'nan' would not eval back
    assert math.isnan(value.reconstruct(enc))

    enc_inf = value.encode(float("inf"))
    assert enc_inf.literal is None
    assert value.reconstruct(enc_inf) == float("inf")


def test_unpicklable_raises_encode_error():
    with pytest.raises(EncodeError):
        value.encode(lambda x: x)


def test_values_equal_handles_nonbool_eq():
    class Weird:
        def __eq__(self, other):
            return "not a bool"

    assert value.values_equal(Weird(), Weird()) is False
    assert value.values_equal(1, 1) is True
    assert value.values_equal(1, 2) is False
