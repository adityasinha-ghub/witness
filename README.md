# witness

**Run your program once. Get real tests.**

`witness` watches your code from the inside as it runs, records the **actual
inputs and outputs** of your functions, and writes **committable pytest tests**
from what it saw — a safety net for untested code you can generate in one run and
then refactor behind.

It is not a fuzzer, and it is not an AI test-writer. Its one rule:

> **Observe freely; only the observed is asserted.**
> Every test witness emits is one it already *proved* passes — it reconstructed
> the recorded inputs, re-ran the function, and confirmed the recorded output
> reproduces. Anything it can't reproduce, it **refuses** and tells you why. It
> never guesses what your code *should* do.

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
- content-addressed recording under `.witness/`;
- `witness generate` (pytest files) and `witness status`.

It does **not** yet do (see [`docs/frontier/witness_wildground.md`](docs/frontier/witness_wildground.md)
for the full vision and build order):

- **Side effects.** Certification re-invokes the function, so a function with side
  effects runs **twice** during recording, and anything that reads the clock,
  network, DB, or globals will (correctly) be refused. (That re-invocation can also
  perturb shared module/global state, which may affect what a *later* call in the
  same run records — record pure/deterministic functions until the ledger lands.)
  The **hermetic boundary ledger** — recording those dependencies and replaying
  them as auto-mocks — is the next major piece; it's what makes side-effecting code
  recordable and removes the double-execution.
- **Auto-capture** of whole modules via `sys.monitoring` (today you name targets
  with the decorator).
- **Methods, nested functions, lambdas** (top-level functions only for now — others
  are reported as skipped, not mis-emitted).
- Volatility triage, cross-version replay-diff, property mining, production capture,
  languages other than Python.

## Roadmap

- [x] **The floor** — proof-carrying capture: capture → reconstruct → re-invoke → certify-or-refuse
- [ ] **Volatility triage** — measure per-field determinism; quarantine incidental values behind matchers
- [ ] **Hermetic boundary ledger** — record DB/network/clock/RNG; replay them as auto-mocks (kills the double-run)
- [ ] **Cross-version replay-diff** — re-feed recordings into new code; "approve these 3 behavior changes" in PR review
- [ ] **`sys.monitoring` auto-capture** — net a whole module without decorators
- [ ] Corpus distillation, negative-space coverage map, observed-invariant mining

## Development

```console
pip install -e .          # or just use PYTHONPATH=src
python -m pytest -q       # 30 tests
```

## License

MIT
