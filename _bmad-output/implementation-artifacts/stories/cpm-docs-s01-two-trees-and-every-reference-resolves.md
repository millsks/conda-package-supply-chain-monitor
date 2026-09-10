# CPM-DOCS-S01: Two trees, and every reference still resolves

Status: done

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

- [x] `docs/accelerator/` and `docs/conda-sentinel/`; every page assigned.
- [x] `development.md` — 18 sections split 13 platform / 5 product.
- [x] `deployment.md` — 29 sections split 8 platform / 21 product.
- [x] `mkdocs.yml` — the nav in two sections; `--strict` green.
- [x] Every inbound reference in `src/`, `tests/`, `docs/` and `README.md`.
- [x] `tests/unit/test_documentation_references.py` — AC 4.

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

## Dev Agent Record

### Completion Notes

**Section counts are the proof nothing was lost.** `development.md` had 18 `##`
sections and the halves have 13 + 5; `deployment.md` had 29 and the halves have
8 + 21. Asserted before anything else was touched, because a split that quietly
dropped a section would have been invisible in a diff of that size.

**Files added:** `docs/accelerator/` (index, development, deployment, plus the three
pages moved whole) and `docs/conda-sentinel/` (index, development, operations), and
`tests/unit/test_documentation_references.py`.

**Files removed:** `docs/development.md` and `docs/deployment.md`, whose content is
in the four halves.

### The split, and the one section that was genuinely both

`development.md`'s product sections are Themes, The request boundary, The API and
Reports and exports — all written into it over the last four stories. **Local
personas** was the judgement call: it is the accelerator's local sign-in mechanism
carrying this product's three roles. It went to the product tree, because the reason
somebody reads it is to reach a role-scoped screen.

`deployment.md` was the lopsided one. Eight sections are the platform's deployment
mechanics; **twenty-one are this product's collectors and policies** — 2,852 lines of
operations manual living in a file named for the platform. That is now
`conda-sentinel/operations.md`, and it opens with the thing a new operator most needs
to know: every collector ships inert, so a fresh deployment sees nothing until
somebody declares where to look.

### The sweep, and what it deliberately did not touch

`mkdocs build --strict` did half the work: it refuses a broken link between pages, so
every cross-link that needed repointing was a build failure rather than something to
find.

The other half was source. **`_bmad-output/` is excluded on purpose**, and that is a
judgement rather than a gap: a completed story record is dated. `CPM-RENAME-S02`
records verifying eight import lines at `docs/deployment.md` lines 1201–1202, against
a file that existed when it ran. Rewriting that path would make the record claim work
it did not do, at line numbers that never matched. A record of the past may name a
file that no longer exists; a pointer somebody is meant to follow may not.

### Three things found by running it

1. **The bulk of the citations were in the planning artifacts**, which the first
   count found and the first *sweep* did not — I swept `src/` and `tests/` and the
   audit immediately reported a hundred more. That is the audit doing its job before
   the story shipped rather than after.
2. **Four modules build the path a segment at a time** — `REPO_ROOT / "docs" /
   "deployment.md"` — so a sweep for the string `docs/deployment.md` matched nothing
   in them. They failed at `FileNotFoundError` when the suite ran. The audit now
   recognises both spellings, and the constructed one is the spelling that matters
   most: it is how a test *opens* a page.
3. **A test asserted the deployment page was in the nav by its bare name.** After the
   split that name would match a page in *either* tree, so it now names the path —
   the substring problem this repository keeps meeting, and here it would have let
   the product's operations page satisfy a case about the platform's.

### A limit, stated

The audit checks that cited paths resolve. It does not check anchors — `pixi run docs`
does, and it is a better tool for that than a regex. What `--strict` cannot see is a
path in a Python comment. Between the two, both directions are closed.
