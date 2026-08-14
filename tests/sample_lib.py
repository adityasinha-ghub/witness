"""A small set of decorated functions used by the tests (and the demo).

Deliberately covers the interesting cases: a pure function, string handling, a
function that mutates its input in place, one that raises, one that is
nondeterministic, and a passthrough for un-reproducible inputs.
"""

import math

import witness


@witness.record
def add(a, b):
    return a + b


@witness.record
def normalize(name):
    return name.strip().lower()


@witness.record
def append_and_sum(values):
    # Mutates its argument in place, then returns — exercises entry-snapshotting.
    values.append(100)
    return sum(values)


@witness.record
def divide(a, b):
    return a / b  # raises ZeroDivisionError when b == 0


@witness.record
def identity(x):
    return x


_counter = {"n": 0}


@witness.record
def next_id():
    _counter["n"] += 1
    return _counter["n"]  # nondeterministic — must be refused, never asserted


@witness.record
def tags(text):
    # Returns a set of strings (pickle byte-order is hash-seed dependent, but == is
    # order-independent) — must certify, not be wrongly refused.
    return set(text.split()) - {"the", "a"}


@witness.record
def wrap_nan():
    return [math.nan]  # a non-reflexive value in a container — must be refused


_SINGLETON = object()  # identity-based __eq__


@witness.record
def get_singleton():
    return _SINGLETON  # equal to itself only by identity — must be refused
