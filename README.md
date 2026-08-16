# witness

> **Status: early and experimental (v0.1).** The core is well-tested and its
> guarantees are honestly bounded (see [What certification does and doesn't
> guarantee](#what-certification-does-and-doesnt-guarantee)), but expect rough edges
> and API changes. Python 3.10+.

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

Validated on real (non-toy) code: pointed at stdlib `textwrap`, `statistics`,
`urllib.parse`, and `base64`, it records their functions *and* class methods and
emits tests that pass — and a CI guard keeps dogfooding `textwrap` on every run. See
[`examples/realworld.py`](examples/).

## Quick start

```python
import witness


@witness.record
def slugify(title):
    return title.lower().replace(" ", "-")


with witness.recording():  # records every @record call, saves to .witness/
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
    result = slugify("Hello World")
    assert result == "hello-world"
```

You didn't have to invent a single input or expected value — they're the ones your
program really used.

### Recording code you don't want to edit

No decorators required. Point witness at whole modules and it instruments every
top-level function **and class method** in them for the duration (a method's `self`
is captured as its first argument, so the generated test rebuilds the object and
calls the method on it):

```python
import witness

with witness.recording(targets=["mypackage.orders", "mypackage.pricing"]):
    run_your_normal_workload()
```

Or capture a script with **zero edits at all** — no witness import anywhere:

```console
$ witness run --target mypackage.orders --dep mypackage.http.get app.py
$ witness generate
```

`witness run` runs your script normally, instruments the named modules (`--target`)
and dependency functions (`--dep`, see below), and saves a recording — the fastest
way to throw a net over a legacy codebase that does I/O. See
[`examples/app.py`](examples/) for a full undecorated run.

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

The diff uses the same `==` your generated tests use, so it agrees with them. A
change `==` can't see — a return type flipping `float` → `int`, `[1, 2]` gaining a
float, a dict value changing type — is reported separately as **drift** (same value,
different shape):

```console
$ witness check
  ✓ 8 unchanged
  ⧗ 1 drifted — same value, different type/shape (tests still pass; use --strict to fail on these):
      median([3, 1, 2]):  float  →  int
```

Drift doesn't fail the gate by default (the `==` tests still pass, so calling it a
failure would contradict them); pass `--strict` to treat drift as a failure too.

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
    with _Replay({"random.randint": [3623], "time.time": [1786679730.88]}):
        result = _mod.make_token("alice")
    assert result == "alice-3623-1786679730"
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
  over `datetime.now()` for now; broader seam coverage is on the roadmap.

## Recording dependencies (network, DB, …)

Code that calls out to the world — an HTTP client, a DB helper — is nondeterministic
and would be refused. Declare those functions as **dependencies** and witness records
each response *keyed by the call's arguments*, then replays it:

```python
with witness.recording(deps=["myapp.http.get", "myapp.db.query"]):
    run_your_workload()
```

…or, with zero edits, `witness run --dep myapp.http.get --dep myapp.db.query app.py`.

Now a function that calls `get("http://a")` certifies, and its generated test
replays the recorded response for that exact URL — offline, deterministic, no server:

```python
def test_load_title_0():
    with _Deps({"myapp.http.get": {"<arg-hash>": ["<recorded response>"]}}):
        result = _mod.load_title("http://a")
    assert result == "HELLO"
```

Matching is **by argument content, not call order** — `get("http://a")` and
`get("http://b")` each get their own recorded response — and a call whose arguments
were never recorded **fails loud** rather than serving the wrong answer. Same
module-patch caveat as seams (call the dependency through its module); the arguments
and the response must be picklable, or the call is refused.

## Partly-nondeterministic returns

Sometimes only *part* of a return varies — an API-response dict with a stable
payload and a volatile `request_id`, say. Rather than refuse the whole call, witness
certifies the **stable structure**: fields that held across every sample are
asserted exactly, fields that varied but kept their type are asserted by type, and
the key set is pinned.

```python
def make_response(name):
    return {"name": name, "status": "ok", "request_id": next_id()}  # id varies
```

```python
def test_make_response_0():
    result = _mod.make_response("alice")
    assert set(result.keys()) == {"name", "request_id", "status"}
    assert result["name"] == "alice"
    assert result["status"] == "ok"
    assert type(result["request_id"]).__name__ == "int"
```

Every assertion held in *every* sample, so none of it is fiction — and the test
passes even though `request_id` is different each run. It works **recursively** —
nested dicts and lists are triaged the same way (`result['user']['name'] == 'alice'`,
`type(result['user']['session']).__name__ == 'int'`). If nothing concrete can be
pinned (no stable value anywhere), the call is still refused.

## What certification does and doesn't guarantee

witness certifies that a call **reproduced across several immediate re-invocations**
(`samples`, default 5) with the recorded seams replayed. That reliably rejects
ordinary nondeterminism. It is honest about two things it can't fully catch yet:

- **Uncovered low-cardinality randomness.** A source witness doesn't record (e.g.
  `secrets.randbelow(2)`) can, rarely, re-roll the same value on every sample and be
  wrongly certified — as a whole return, or as a single "stable" field in volatility
  triage. More `samples` shrinks this fast (a coin flip drops from ~44% at 1 sample
  to ~1% at 5); covering the source as a seam eliminates it.
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
- **auto-capture** of whole modules (`recording(targets=...)`) and `witness run` — no decorators;
- entry-snapshot capture, proof-carrying certification, refusal with reasons;
- clock/RNG/uuid **seam** recording & replay → hermetic tests (see above);
- content-addressed recording under `.witness/`;
- `witness generate`, `witness status`, and `witness check`.

It does **not** yet do (see [`docs/frontier/witness_wildground.md`](docs/frontier/witness_wildground.md)
for the full vision and build order):

- **Side effects.** Certification re-invokes the function, so a function with side
  effects runs **twice** during recording. Clock/RNG/uuid are now recorded and
  replayed (see above), but anything that reads the **network, DB, filesystem, or
  unpatched globals** will still (correctly) be refused. (Re-invocation can also
  perturb shared module/global state, affecting what a *later* call records — record
  pure/deterministic-ish functions for now.) Extending the boundary ledger to those
  dependencies (replayed as auto-mocks) is what will remove the double-execution.
- **Auto-capture** covers a module's own top-level functions and instance/static
  methods (called through the module). `classmethod`s, nested functions, and functions
  reached only via a bound-early reference aren't captured yet (the last would need a
  `sys.monitoring` tracer).
- **Nested functions and lambdas** are reported as skipped, not mis-emitted.
- Property mining, production capture, languages other than Python.

## Roadmap

- [x] **The floor** — proof-carrying capture: capture → reconstruct → re-invoke → certify-or-refuse
- [x] **Boundary ledger (seams)** — record & replay `time`/`random`/`uuid`; hermetic tests for clock/RNG code
- [x] **Cross-version replay-diff** — `witness check` diffs a recording against the current code (CI gate)
- [x] **Auto-capture** — instrument whole modules without decorators (`recording(targets=...)`, `witness run`)
- [x] **Schema fingerprinting** — `witness check` flags type/shape drift (`float` → `int`) the `==` diff can't see
- [x] **Dependency ledger** — record & replay declared dependency functions by argument (`recording(deps=...)`)
- [x] **Volatility triage** — certify the stable structure of a partly-volatile return (recursive: nested dicts + lists)
- [x] **Method capture** — auto-instrument instance methods (`self` recorded as the first arg) and static methods
- [ ] Filesystem deps, classmethods, a `sys.monitoring` tracer for locally-bound calls
- [ ] **Cross-version replay-diff** — re-feed recordings into new code; "approve these 3 behavior changes" in PR review
- [ ] **`sys.monitoring` auto-capture** — net a whole module without decorators
- [ ] Corpus distillation, negative-space coverage map, observed-invariant mining

## Development

```console
pip install -e .          # or just use PYTHONPATH=src
python -m pytest -q       # 84 tests
```

## License

MIT
