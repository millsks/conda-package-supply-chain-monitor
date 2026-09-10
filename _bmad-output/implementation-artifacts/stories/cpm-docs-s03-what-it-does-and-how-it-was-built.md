# CPM-DOCS-S03: What Conda-Sentinel does, and how it was built

Status: done

Epic: `CPM-EP-DOCS` — Documentation that says which product it is about

> **Acceptance criteria invented.** No functional requirement commissions
> documentation. They were drafted by the implementing agent and confirmed with the
> product owner, on the terms `CPM-APP-S09` established. See the epic entry.

## Story

As a new maintainer,
I want the product explained on the documentation site,
so that I do not have to read the planning artifacts to understand the system.

## Acceptance Criteria

1. **Given** the product documentation
   **When** it is read start to finish
   **Then** it explains what the product concludes about a package and from what
   evidence

2. **Given** the five outcome states
   **When** they are documented
   **Then** each is named, and it is explained why `unknown` is a finding rather than
   an absence

3. **Given** the architecture spine
   **When** it is presented on the site
   **Then** the decisions a maintainer has to know are explained in prose, with the
   identifiers preserved so the spine remains findable

4. **Given** the flow from a collector to a screen
   **When** it is documented
   **Then** each stage names the table it writes and the rule that governs it

## Tasks / Subtasks

- [x] `docs/conda-sentinel/index.md` — the product, the roles, the states.
- [x] `docs/conda-sentinel/architecture.md` — the spine distilled; the domain model.
- [x] `docs/conda-sentinel/the-policy-run.md` — collector to rollup to screen.
- [x] `mkdocs.yml` — the product section, in reading order.
- [x] `tests/unit/django_apps/test_documentation_accuracy.py`.

## Dev Notes

### A distillation, never a copy

`_bmad-output/planning-artifacts/` stays the record. A second full copy of the
architecture spine on the site would be a second thing to keep true, and the one that
drifts is always the copy. What goes on the site is what a maintainer needs to hold
in their head, with `CPM-AD-n` preserved so the full text stays findable.

### The load-bearing idea

`unknown` is a state this product **asserts**, not a gap. It is what the confidence
gate (`CPM-AD-4`) writes when nothing was established, and every surface emits it
verbatim (`CPM-AD-24`) precisely so nobody reads it as clean. Documentation that
explained the happy path and left the sentinels as an appendix would have missed the
product.

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

**Files added:** `docs/conda-sentinel/architecture.md`,
`docs/conda-sentinel/the-policy-run.md`,
`tests/unit/django_apps/test_documentation_accuracy.py`.
**Files changed:** `docs/conda-sentinel/index.md` (was a stub from `CPM-DOCS-S01`),
`mkdocs.yml`.

### The overview leads with the idea, not the feature list

Most monitoring tools have two answers — a problem, or silence — and silence is the
dangerous one, because it looks like health and is usually absence. This product has
five and says which it means.

Everything else in the documentation follows from that, so it is the first thing on
the page, and the five are shown as chips rather than described. The **gap versus
verdict** split is given more room than the list itself: `not_found` is an answer and
`unknown` is the absence of one, and a page that listed five states without saying
which two are gaps would have taught a reader the names and not the idea.

### A distillation, and the identifiers are what make that work

`_bmad-output/planning-artifacts/` stays the record. A second complete copy on the
site would be a second thing to keep true, and the one that drifts is always the copy.
So the architecture page explains the decisions a maintainer has to hold in their head
and keeps every `CPM-AD-n` so the full text stays findable.

That is also what the audit is built on: a decision renumbered, split or withdrawn
leaves a page pointing at nothing, and a reader who follows it concludes the record
was deleted rather than moved.

### Every factual claim was checked against the code

Not read off the spine and trusted — the spine describes intent, and the question is
what shipped:

| Claim | Verified |
|---|---|
| eight passes, in that order | `registered_passes()` → currency, feedstock-presence, vulnerability, licence, remediation, py314-readiness, work-type, priority |
| precedence, worst first | `PRECEDENCE` → error, unknown, not_found, not_applicable, ok |
| `surface` declares no model | 0 |
| ten evidence tables | 10 |
| eight derived tables | 8 |

### The audit checks decay, not wording

Two kinds, both quiet: a citation that no longer resolves, and a vocabulary that grew
without the documentation noticing. A sixth `OutcomeState` fails the overview case,
which is the moment to write the sentence rather than six months later when somebody
asks what it means.

**It deliberately does not assert wording.** A test that pinned a sentence would be
edited whenever the sentence improved, and would teach people to edit the test rather
than improve the sentence. What is pinned is the set of things that must be
*mentioned*.

One correction on that theme: the precedence case first matched a literal
`error → unknown → …` and failed on the wider arrow spacing the page actually uses.
It matches the **order** now — a literal would have failed on somebody widening the
arrows for legibility, which is an improvement, and would have taught the next author
to narrow them again rather than keep the order right.
