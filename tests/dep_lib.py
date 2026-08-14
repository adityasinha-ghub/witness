"""A module with a nondeterministic 'dependency' (_fetch) and a function using it.

Without recording _fetch as a dependency, load_title is nondeterministic (each
_fetch call returns something new) and would be refused. Declared as a dep, the
response is recorded per-URL and replayed, so it certifies.
"""

import witness

_calls = {"n": 0}


def _fetch(url):
    # Stand-in for a network call: the response varies every call.
    _calls["n"] += 1
    return f"{url}#resp{_calls['n']}"


@witness.record
def load_title(url):
    return _fetch(url).upper()


def _lookup(keys):
    # A dependency whose argument is a SET (hash-seed-dependent iteration order).
    _calls["n"] += 1
    return f"{len(keys)}#{_calls['n']}"


@witness.record
def summarize(words):
    return _lookup(set(words))
