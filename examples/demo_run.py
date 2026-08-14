"""Record a real run of the untouched `legacy` module.

Wraps the legacy functions with `witness.record` from the outside (no edits to
legacy.py), runs them on realistic inputs inside `witness.recording()`, and saves
a recording to `.witness/`. Then: `witness generate`.
"""

import witness

import legacy

for name in ["slugify", "parse_kv", "median", "word_count", "make_token"]:
    setattr(legacy, name, witness.record(getattr(legacy, name)))

with witness.recording():
    legacy.slugify("Hello, World!")
    legacy.slugify("  Rust & Python: 2026  ")
    legacy.parse_kv("a=1; b=2; c=hello")
    legacy.parse_kv("")
    legacy.median([3, 1, 2])
    legacy.median([10, 20, 30, 40])
    legacy.word_count("the quick brown fox")
    legacy.make_token("alice")  # uses random + clock — recorded and replayed
    try:
        legacy.median([])
    except ValueError:
        pass

print("done — recorded to .witness/")
