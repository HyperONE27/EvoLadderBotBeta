# Testing Philosophy

## Why these tests exist

Most of this project is tested by hand — a human queuing, confirming, reporting,
and watching the bot respond.  That end-to-end loop covers the Discord UI, the
HTTP layer, the WebSocket broadcasts, and the database writes.  Writing automated
tests for that stack would mean mocking Discord, FastAPI, Supabase, and the event
loop, producing tests that are expensive to maintain and don't catch real bugs.

What *does* benefit from automated tests are the **pure, stateless functions** at
the core of the system — algorithms that take data in and return data out with no
I/O, no singletons, and no side effects.  These functions have complex branching
logic that is genuinely hard to exercise manually, and subtle regressions in them
can silently corrupt ratings, produce invalid matches, or break fairness
guarantees.

## What the tests check

Tests in this project are **invariant checks**, not **outcome encodings**.

An outcome encoding says: "given MMR 1500 vs 1400 with result=1, the new ratings
are 1518 and 1382."  This test breaks the moment you change the K-factor, the
divisor, or the rounding strategy — even if the system is still correct.

An invariant check says: "for any valid inputs, the winner's MMR goes up and the
loser's goes down, and the total MMR in the system is conserved (±1 for
rounding)."  This test survives tuning changes because it encodes the *property*
the system must satisfy, not a specific numerical outcome.

The distinction matters because these algorithms *will* be tuned.  MMR windows,
wait coefficients, K-factors, balance thresholds — these are all knobs that get
adjusted based on observed queue times and match quality.  Tests that break on
every tuning change are a tax, not a safety net.

### Invariant categories

**Structural invariants** — properties of the output shape:
- Conservation: no players created or destroyed (remaining + matched = input)
- Uniqueness: no player appears in two matches or in both a match and the remaining queue
- Completeness: all required fields populated (e.g. every race field in a MatchCandidate is non-None)

**Relational invariants** — properties that relate inputs to outputs:
- Directionality: winners gain MMR, losers lose it
- Symmetry: the system doesn't privilege the player_1 slot
- Zero-sum: total MMR is conserved across a rating update

**Algorithmic invariants** — properties of the algorithm's correctness:
- Optimality: the Hungarian assignment has minimum total cost among all valid assignments
- Permutation: the assignment maps each row to a unique column
- Monotonic convergence: two compatible players will eventually match given enough wait cycles

**Boundary invariants** — degenerate and edge-case inputs:
- Empty queue produces no matches
- Single entry produces no matches
- Two incompatible entries both remain
- Two compatible entries within window always match

## What is NOT tested

- Discord UI behaviour (embeds, views, buttons, modals)
- HTTP endpoint request/response shapes
- WebSocket broadcast content
- Database read/write operations
- Anything that requires mocking external services

These are covered by manual testing and, if they break, produce immediately
visible symptoms (a button doesn't work, a DM doesn't arrive, an embed looks
wrong).

## Test organisation

```
tests/
    test_ratings.py          — ELO rating invariants
    test_matchmaker_1v1.py   — 1v1 queue categorisation, equalisation, candidate building, full wave
    test_matchmaker_2v2.py   — 2v2 compatibility, cost matrix, composition resolution, full wave
    test_hungarian.py        — Hungarian algorithm correctness (brute-force verified)
```

Each file targets one module.  The Hungarian algorithm gets its own file because
both matchmakers use the same implementation and the brute-force verification is
a standalone piece of test infrastructure.

## Running

```bash
python -m pytest tests/ -v
```
