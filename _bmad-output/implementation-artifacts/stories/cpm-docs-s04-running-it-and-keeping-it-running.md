# CPM-DOCS-S04: Running it, and keeping it running

Status: ready-for-dev

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

- [ ] `docs/conda-sentinel/running-it.md` — start, sign in, seed, run a pass.
- [ ] `docs/conda-sentinel/maintaining-it.md` — the gate, the audits, shipping a change.
- [ ] The audit roster, each with the failure it prevents.

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
