# CPM-DOCS-S03: What Conda-Sentinel does, and how it was built

Status: ready-for-dev

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

- [ ] `docs/conda-sentinel/what-it-does.md` — the product, the roles, the states.
- [ ] `docs/conda-sentinel/architecture.md` — the spine distilled; the domain model.
- [ ] `docs/conda-sentinel/the-policy-run.md` — collector to rollup to screen.
- [ ] Diagrams where a table would be worse.

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
