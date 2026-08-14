from witness import schema


def test_scalar_fingerprints():
    assert schema.fingerprint(5) == "int"
    assert schema.fingerprint(5.0) == "float"
    assert schema.fingerprint(True) == "bool"  # not int
    assert schema.fingerprint("x") == "str"
    assert schema.fingerprint(None) == "None"


def test_int_and_float_differ():
    assert schema.fingerprint(5) != schema.fingerprint(5.0)


def test_container_element_types():
    assert schema.fingerprint([1, 2, 3]) == "list[int]"
    assert schema.fingerprint([1, 2.0]) == "list[float|int]"
    assert schema.fingerprint((1, 2)) != schema.fingerprint([1, 2])  # tuple vs list


def test_dict_shape_includes_value_types():
    assert schema.fingerprint({"a": 1}) != schema.fingerprint({"a": 1.0})


def test_recursion_is_bounded():
    x: list = []
    x.append(x)  # self-referential — must not recurse forever
    assert isinstance(schema.fingerprint(x), str)
