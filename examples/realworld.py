"""witness against a real library — no toy code, no edits. Try:

    witness run --target textwrap examples/realworld.py
    witness generate && python -m pytest tests/

It records the real stdlib `textwrap` (its functions *and* `TextWrapper` methods)
and writes passing tests for what it actually did.
"""

import textwrap

para = "the quick brown fox jumps over the lazy dog " * 3
print(textwrap.fill(para, width=30))
print(textwrap.shorten(para, width=40))
print(textwrap.wrap("witness records what really happened", width=12))
print(textwrap.indent("line one\nline two\n", "  | "))
