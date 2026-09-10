# CPM-DOCS-S01: Two trees, and every reference still resolves

Status: ready-for-dev

Epic: `CPM-EP-DOCS` — Documentation that says which product it is about

> **Acceptance criteria invented.** No functional requirement commissions
> documentation. They were drafted by the implementing agent and confirmed with the
> product owner, on the terms `CPM-APP-S09` established. See the epic entry.

## Story

As a maintainer,
I want the platform's documentation and this product's kept apart,
so that a reader asking how Conda-Sentinel works is not handed a chapter on
15-factor process models.

## Acceptance Criteria

1. **Given** the documentation tree
   **When** it is listed
   **Then** every page lives under `docs/accelerator/` or `docs/conda-sentinel/`, and
   the navigation reflects the same split

2. **Given** a section of a page that describes the other side
   **When** the split is performed
   **Then** it moves rather than being duplicated, and no content is lost

3. **Given** any reference to a documentation path in source, tests or planning
   artifacts
   **When** the move is complete
   **Then** it names a file that exists

4. **Given** a later change that moves or renames a documentation page
   **When** the suite runs
   **Then** a reference naming a file that no longer exists fails a test

## Tasks / Subtasks

- [ ] `docs/accelerator/` and `docs/conda-sentinel/`; every page assigned.
- [ ] `development.md` — thirteen sections platform, three product; split them.
- [ ] `deployment.md` — twenty-nine sections; split on the same reading.
- [ ] `mkdocs.yml` — the nav in two sections.
- [ ] The 237 inbound references, swept.
- [ ] `tests/unit/test_documentation_references.py` — AC 4.

## Dev Notes

### This is not a file move

`docs/development.md` has eighteen `##` sections. Thirteen are the platform's —
Environment, Supply chain, Running with no external services, Database, Tasks, The
gate, Logging and tracing, Tests, Serving the application, Writing an API surface,
Protocols below the URL resolver, Coverage, Pre-commit. Three are this product's:
The request boundary, The API, Reports and exports. `Local personas` is genuinely
both — it is the accelerator's local sign-in mechanism carrying this product's three
roles — and goes to the product tree, because the reason somebody reads it is to
reach a role-scoped screen.

`docs/deployment.md` is 3,584 lines across twenty-nine sections and wants the same
reading.

### The expensive half

**237 references** cite `docs/development.md` or `docs/deployment.md` by path, from
module docstrings, tests and planning artifacts. `src/config/settings/base.py` alone
cites `deployment.md` four times.

They are not optional to fix. A stale pointer in a docstring is worse than the
mixture it replaced: a reader who follows one concludes the documentation was
deleted rather than moved, and stops looking. AC 4's audit is what stops the count
growing back — the same shape as every other sweep in this suite, and for the same
reason, which is that a rule nobody checks is a rule that decays.

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
