# witness

**Run your program once. Get real tests.**

`witness` watches your code from the inside as it runs, records the **actual
inputs and outputs** of your functions, and writes **committable pytest tests**
from what it saw — a safety net for untested code you can generate in one run and
then refactor behind.

It is not a fuzzer, and it is not an AI test-writer. Its one rule:

> **Observe freely; only the observed is asserted.**
> Every test witness emits is one it re-ran and confirmed reproduces — it
> reconstructs the recorded inputs, re-invokes the function several times (replaying
> the recorded clock/RNG/uuid), and checks the recorded output comes back every
> time. Anything it can't reproduce, it **refuses** and tells you why. It never
> guesses what your code *should* do.

That's the difference from the neighbors: EvoSuite/Randoop (randomized), Hypothesis
(you write the strategies), and "AI writes your tests" (nondeterministic, and it
hallucinates). witness only ever writes down what really happened.

## Quick start

```python
import witness

@witness.record
def slugify(title):
    return title.lower().replace(" ", "-")

with witness.recording():        # records every @record call, saves to .witness/
    slugify("Hello World")
    slugify("Rust and Python")
```

```console
$ witness status
Recording: 2 certified capsule(s), 0 refusal(s).
Certified:
     2  slugify

$ witness generate
  wrote tests/test_witness_yourmodule.py
witness: generated 2 test(s) in 1 file(s).
```

The generated file is standalone and passes as-is:

```python
def test_slugify_0():
    result = slugify('Hello World')
    assert result == 'hello-world'
```

You didn't have to invent a single input or expected value — they're the ones your
program really used.

### Recording code you don't want to edit

You don't have to add decorators to the source. Wrap functions from the outside:

```python
import witness, legacy

legacy.parse = witness.record(legacy.parse)   # no edit to legacy.py
with witness.recording():
    run_your_normal_workload()
```

See [`examples/`](examples/) for a full run against an untouched `legacy` module.

## Catch behavior changes: `witness check`

A recording isn't just a source of tests — it's a **regression oracle**. `witness
check` re-feeds every recorded call into your *current* code (replaying the recorded
clock/RNG so the comparison is fair) and reports which behaviors changed:

```console
$ witness check
Checking 9 recorded behavior(s) in '.witness' against the current code:
  ✓ 7 unchanged
  ✗ 2 changed:
      slugify('Hello, World!'):  'hello-world'  →  'hello_world_'
      slugify('  Rust & Python: 2026  '):  'rust-python-2026'  →  '_rust_python_2026_'
```

Neither side is labelled "correct" — it shows you *what moved* so you can bless it
(re-record) or fix it. It **exits non-zero when anything changed**, so it drops
straight into CI as a behavioral guard, no generated files required. This is the
same reframing behind "approve these 3 behavior changes" in review.

The diff uses the same `==` your generated tests use, so it agrees with them: a
change that `==` can't see (e.g. a return type flipping `2.0` → `2`) reads as
*unchanged*, because the test wouldn't break either. Type-level drift detection is a
roadmap item (schema fingerprinting).

## What "refused" means (and why it's the point)

witness would rather write nothing than write a lie. If a function is
nondeterministic or depends on outside state, its output won't reproduce on
replay, so witness refuses it instead of emitting a test that would flake:

```console
$ witness status
Recording: 0 certified capsule(s), 4 refusal(s).
Refused (witness won't assert what it can't reproduce):
  roll:  not reproducible: replay output differs (nondeterministic or state-dependent output)
  stamp: not reproducible: replay output differs (nondeterministic or state-dependent output)
```

A refusal is a signal, not a failure: it's telling you exactly which behavior isn't
pinnable yet (and, on the roadmap, often points at a real nondeterminism bug).

## Recording the clock and randomness

Code that reads `time.time()`, `random.*`, or `uuid.*` used to be refused as
nondeterministic. witness now records the values those **seams** produce during the
real run and *replays* them — so the call certifies, and the generated test is
**hermetic** (it replays the recorded values instead of drawing fresh ones):

```python
def make_token(user):
    return f"{user}-{random.randint(1000, 9999)}-{int(time.time())}"
```

becomes a test that passes deterministically, every run, with no seed and no clock:

```python
def test_make_token_0():
    with _Replay({'random.randint': [3623], 'time.time': [1786679730.88]}):
        result = _mod.make_token('alice')
    assert result == 'alice-3623-1786679730'
```

Covered seams are in `witness.seams.DEFAULT_SEAMS` (`time.*`, `random.*`, `uuid.*`);
pass `seams=[...]` to `recording()` to override, or `seams=[]` to disable.

**Honest limits of this v0 slice:**
- witness patches **module attributes**, so it only sees `time.time()` /
  `random.random()` called *through the module* — not a reference bound earlier via
  `from time import time`.
- **Not covered:** `datetime.datetime.now()` (a method on a C type that can't be
  monkeypatched), `secrets`, `os.urandom`, `numpy.random`, and network/DB/file I/O.
  A high-entropy uncovered source will make the call diverge on replay and be
  **refused** (safe). But a *low-resolution* uncovered source — e.g. `date.today()`
  — can read identically during the immediate re-invoke yet change later, so it can
  slip through and freeze into a test that breaks another day. Prefer `time.time()`
  over `datetime.now()` for now; broader coverage + volatility triage are on the
  roadmap.

## What certification does and doesn't guarantee

witness certifies that a call **reproduced across several immediate re-invocations**
(`samples`, default 5) with the recorded seams replayed. That reliably rejects
ordinary nondeterminism. It is honest about two things it can't fully catch yet:

- **Uncovered low-cardinality randomness.** A source witness doesn't record (e.g.
  `secrets.randbelow(2)`) can, rarely, re-roll the same value on every sample and be
  wrongly certified. More `samples` shrinks this fast (a coin flip drops from ~44%
  at 1 sample to ~1% at 5); covering the source as a seam eliminates it.
- **Per-process cached values.** A value computed once at import (e.g. a module-level
  `uuid4()`) always "reproduces" in-process, so a test can freeze it and then fail
  in a fresh process. Catching this needs subprocess isolation (roadmap).

So witness errs toward refusing, and its guarantee is "reproduced under these
checks" — strong in practice, not a proof against every hidden input. Running the
generated tests once in CI is the final ground truth.

## How it works

1. **Snapshot at entry.** When a recorded function is called, witness deep-copies
   its arguments *before* the call — so a function that mutates its inputs in place
   is recorded with what it actually received, not the mutated leftovers.
2. **Certify.** witness serializes the inputs and outcome, reconstructs the inputs
   from that serialized form, **re-invokes the function**, and checks the outcome
   reproduces. Only then does a capsule exist.
3. **Generate.** Certified capsules become pytest tests — as readable Python
   literals where values round-trip cleanly, and as self-contained inline fixtures
   otherwise (no runtime dependency on witness).

## Scope (v0 — honest limits)

This is an early, deliberately narrow v0. It does today:

- a `@witness.record` decorator + a `with witness.recording():` context (Python ≥ 3.10);
- entry-snapshot capture, proof-carrying certification, refusal with reasons;
- clock/RNG/uuid **seam** recording & replay → hermetic tests (see above);
- content-addressed recording under `.witness/`;
- `witness generate` (pytest files) and `witness status`.

It does **not** yet do (see [`docs/frontier/witness_wildground.md`](docs/frontier/witness_wildground.md)
for the full vision and build order):

- **Side effects.** Certification re-invokes the function, so a function with side
  effects runs **twice** during recording. Clock/RNG/uuid are now recorded and
  replayed (see above), but anything that reads the **network, DB, filesystem, or
  unpatched globals** will still (correctly) be refused. (Re-invocation can also
  perturb shared module/global state, affecting what a *later* call records — record
  pure/deterministic-ish functions for now.) Extending the boundary ledger to those
  dependencies (replayed as auto-mocks) is what will remove the double-execution.
- **Auto-capture** of whole modules via `sys.monitoring` (today you name targets
  with the decorator).
- **Methods, nested functions, lambdas** (top-level functions only for now — others
  are reported as skipped, not mis-emitted).
- Volatility triage, cross-version replay-diff, property mining, production capture,
  languages other than Python.

## Roadmap

- [x] **The floor** — proof-carrying capture: capture → reconstruct → re-invoke → certify-or-refuse
- [x] **Boundary ledger (seams)** — record & replay `time`/`random`/`uuid`; hermetic tests for clock/RNG code
- [x] **Cross-version replay-diff** — `witness check` diffs a recording against the current code (CI gate)
- [ ] **Boundary ledger (dependencies)** — network/DB/filesystem as auto-mocks (kills the double-run)
- [ ] **Schema fingerprinting** — flag type-level drift (`2.0` → `2`) the `==` diff can't see
- [ ] **Volatility triage** — measure per-field determinism; quarantine incidental values behind matchers
- [ ] **Cross-version replay-diff** — re-feed recordings into new code; "approve these 3 behavior changes" in PR review
- [ ] **`sys.monitoring` auto-capture** — net a whole module without decorators
- [ ] Corpus distillation, negative-space coverage map, observed-invariant mining

## Development

```console
pip install -e .          # or just use PYTHONPATH=src
python -m pytest -q       # 41 tests
```

## License

MIT
