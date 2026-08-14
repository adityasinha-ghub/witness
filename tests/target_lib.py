"""A plain module with NO witness decorators — instrumented via targets=[...]."""

from math import sqrt  # noqa: F401 - re-exported; must NOT be auto-wrapped


def double(x):
    return x * 2


def greet(name):
    return f"hi {name}"


def compute(x):
    return double(x) + 1  # calls another target function → nested capture
