"""witness — generate committable, proof-carrying tests from a real run.

Public API::

    import witness

    @witness.record
    def parse(...): ...

    with witness.recording():   # records every @record call, saves to .witness/
        run_your_program()

Then ``witness generate`` emits pytest files. The guarantee: witness asserts only
behavior it observed *and* reproduced — anything it cannot reproduce is refused,
never guessed.
"""

from .recorder import record, recording

__all__ = ["record", "recording"]
__version__ = "0.1.0"
