"""A small set of decorated functions used by the tests (and the demo).

Deliberately covers the interesting cases: a pure function, string handling, a
function that mutates its input in place, one that raises, one that is
nondeterministic, and a passthrough for un-reproducible inputs.
"""

import math
import random
import time

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


@witness.record
def jittered(base):
    # Reads the RNG through the module — a seam witness records and replays.
    return base + random.randint(1, 100)


@witness.record
def stamped(label):
    # Reads the clock through the module — recorded and replayed.
    return f"{label}@{int(time.time())}"


@witness.record
def inner_seam():
    random.random()  # draws a seam, but the return doesn't depend on it
    return 7


@witness.record
def outer_calls_inner():
    # Deterministic, but calls a seam-using @record function — must still certify.
    return inner_seam() + 1


_invocations = {"n": 0}


@witness.record
def const_but_counts():
    _invocations["n"] += 1  # lets a test observe how many times certify re-invoked
    return 42


_partial_n = {"i": 0}


@witness.record
def make_response(name):
    # A dict with stable fields (name, status) and a volatile one (request_id, from
    # a non-seam counter) — the case volatility triage certifies partially.
    _partial_n["i"] += 1
    return {"name": name, "status": "ok", "request_id": _partial_n["i"]}


@witness.record
def response_with_nan(name):
    # A stable field whose value is non-reflexive ([nan]) — must NOT be asserted
    # exactly (it wouldn't equal a fresh copy), only by type.
    _partial_n["i"] += 1
    return {"name": name, "payload": [math.nan], "req": _partial_n["i"]}


@witness.record
def nested_response(name):
    # A nested dict with a volatile field deep inside — exercises recursive triage.
    _partial_n["i"] += 1
    return {"user": {"name": name, "session": _partial_n["i"]}, "ok": True}


@witness.record
def pair(name):
    # A list with a stable element and a volatile one.
    _partial_n["i"] += 1
    return [name, _partial_n["i"]]


@witness.record
def inner_clock(x):
    time.time()  # a seam draw inside a callee
    return x * 2


@witness.record
def outer_clock(x):
    time.time()  # …and the caller draws one too (audit finding #1)
    return inner_clock(x)


@witness.record
def kw_echo(**kw):
    return sorted(kw.items())  # exercises weird kwarg names (audit finding #4)


@witness.record
def flagged(x):
    _partial_n["i"] += 1
    return {"ok": True, "seq": _partial_n["i"]}  # stable True + volatile (finding #3)


def _make_local_error():
    class LocalError(Exception):
        pass

    return LocalError


LocalError = _make_local_error()  # a class whose __qualname__ has '<locals>'


@witness.record
def raise_local(x):
    raise LocalError("nope")  # audit finding #5


@witness.record
def cyclic(name):
    # A self-referential return — triage must not recurse forever.
    _partial_n["i"] += 1
    d = {"name": name, "n": _partial_n["i"]}
    d["self"] = d
    return d


@witness.record
def Cart_total(x):
    # Deliberately named so its test collides with Cart.total's sanitized name.
    return x + 1


class Cart:
    """A small stateful class — its methods are captured via targets=[...]."""

    def __init__(self, discount):
        self.discount = discount
        self.items = []

    def add(self, price):
        self.items.append(price)
        return len(self.items)

    def total(self):
        return sum(self.items) * (1 - self.discount)

    @staticmethod
    def apply_tax(amount, rate):
        return round(amount * (1 + rate), 2)
