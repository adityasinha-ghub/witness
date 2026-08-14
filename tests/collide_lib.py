"""Functions whose names collide with witness's own emitted identifiers."""

import witness


@witness.record
def _wv(x):  # collides with the fixture-loader helper name
    return x + 1


@witness.record
def pytest(x):  # collides with the pytest import
    return x * 2
