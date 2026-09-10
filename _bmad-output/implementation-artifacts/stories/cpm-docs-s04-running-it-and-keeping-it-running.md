# CPM-DOCS-S04: Running it, and keeping it running

Status: done

Epic: `CPM-EP-DOCS` — Documentation that says which product it is about

> **Acceptance criteria invented.** No functional requirement commissions
> documentation. They were drafted by the implementing agent and confirmed with the
> product owner, on the terms `CPM-APP-S09` established. See the epic entry.

## Story

As a maintainer,
I want to be able to start the product, put data in it, and change it safely,
so that my first day does not depend on somebody being available to explain it.

## Acceptance Criteria

1. **Given** a fresh checkout
   **When** the documentation is followed
   **Then** the application can be started and signed into with no external service
   running

2. **Given** the demo seeder
   **When** it is documented
   **Then** it is explained what it writes and, more importantly, what it does not

3. **Given** a change to the product
   **When** the documentation describes how to ship it
   **Then** it names the gate, the audits a change has to satisfy, and why each exists

4. **Given** the audits the suite enforces
   **When** they are listed
   **Then** each names the failure it prevents rather than only the rule it applies

## Tasks / Subtasks

- [x] `docs/conda-sentinel/running-it.md` — start, sign in, seed, run a pass.
- [x] `docs/conda-sentinel/maintaining-it.md` — the gate, the audits, shipping a change.
- [x] The audit roster, each with the failure it prevents.
- [x] `mkdocs.yml` — both pages in reading order.
- [x] `tests/unit/test_documentation_commands.py`.

## Dev Notes

### The seeder's honesty is the point

`pixi run -e dev seed-demo` writes **evidence only**. It never writes a derived status
or a rollup row, because `CPM-AD-10` gives the application layer no path to either and
a seeder that took one would produce a database the product could not have produced.
A maintainer who does not know that will wonder why the screens are empty until they
run a policy pass — so the documentation says it before they wonder.

### The gate cannot complete on macOS

The `docker build` child in `tests/integration/test_image_payload.py` zombies, and it
reproduces on unmodified `main`. The substitute procedure — the five steps run
individually — is documented rather than hidden, because a maintainer who does not
know concludes their own change broke the suite.

### The audits are the interesting half

This suite carries a dozen sweeps that no requirement asked for: pagination, role
declarations, app layering, the confidence gate, derived-status writability, the
request boundary, the API contract. Each exists because a rule that is only written
down decays. Listing them with the *failure each prevents* is what makes them
learnable rather than a list of obstacles.

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- `pixi run docs` (`mkdocs build --strict`) must succeed: a broken internal link is a
  build failure rather than a page a reader finds later.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a
  90% floor.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**Files added:** `docs/conda-sentinel/running-it.md`,
`docs/conda-sentinel/maintaining-it.md`, `tests/unit/test_documentation_commands.py`.
**Files changed:** `mkdocs.yml`.

### Three wrong commands, caught by running them

This is the story's own lesson and it happened while writing it. A first draft told a
new maintainer to run:

- `python manage.py run_policy_now` — **does not exist.** There is no management
  command for a first run; the schedule owns it in production and the seeder does it
  locally.
- `pixi run cov` and `pixi run fmt` — the real names are **`test-cov`** and
  **`format`**.

None of the three would have failed anything in the suite. They would have failed *a
person*, on their first day, on the two pages written to help them. `test_documentation_commands.py`
now checks every `pixi run` in both pages against the parsed manifest, and every audit
the roster names against the files that exist.

### And one wrong claim about the seeder

The draft said the seeder "writes evidence only" and that a separate policy run was
needed. **It runs the pass itself** — through `execute_policy_run`, at the shipped
policy version, producing ten rollup rows. Verified by running it and counting.

The true and more interesting statement is the one now on the page: it writes no
derived status *directly*, because `CPM-AD-10` gives the application layer no path to
one, so it produces evidence and lets the passes that own each domain conclude from
it. Its own comment says it best — *"every status they show is concluded here, by the
passes that own it"* — and it goes through the real ledger, so the coverage screen
reads the shape it would read in production.

### `-e dev` is not optional on the seeder, and the refusal explains itself

`pixi run seed-demo` refuses:

> seed_demo_inventory writes inventory and evidence and must never run outside a local
> run. Evidence is append-only (`CPM-AD-2`): a fictional observation cannot be
> deleted, and every replayed policy run would read it.

Only the dev environment declares `COMPONENT_RUNTIME=local`. That refusal is worth
quoting in the documentation rather than paraphrasing: it is the product protecting an
append-only log from a fixture, and a reader who meets it understands `CPM-AD-2`
faster than any paragraph would manage.

### The audit roster names failures, not rules

AC 4, and it is what makes a dozen sweeps learnable rather than a list of obstacles.
"prevents `core` importing a domain app's tables, inverting the registry" tells you
what the audit is *for*; "enforces the layering rule" does not.

The page also says what to do when one blocks you: read the message first — they are
written to name the failure, so the message usually contains the argument for doing it
the other way — and if it is genuinely wrong, add a **recorded exemption** with a
companion case asserting it is still needed.

### Two things a new maintainer otherwise learns the hard way

Both are documented rather than left to be discovered:

- **`pixi run ci` cannot complete on macOS.** The `docker build` child in
  `tests/integration/test_image_payload.py` zombies, and it reproduces on unmodified
  `main` — so somebody's first run of the gate looks like their change broke the
  suite. The substitute procedure is on the page.
- **The local gate cannot see the CI matrix.** With the path-separator example, which
  is the defect this project makes most often and is invisible on macOS.
