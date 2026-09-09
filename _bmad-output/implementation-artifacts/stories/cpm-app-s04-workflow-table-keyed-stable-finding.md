# CPM-APP-S04: One workflow table keyed on a stable finding key

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a security reviewer,
I want a finding I have accepted to stay accepted after the next collection,
so that my decisions are not silently undone by re-observation.

## Acceptance Criteria

1. **Given** an evidence-backed finding
   **When** a workflow item is created for it
   **Then** it is keyed on a re-observation-stable finding key declared alongside that evidence table, never on an evidence row id

2. **Given** an accepted finding
   **When** the collector re-observes it and inserts a new evidence row
   **Then** the item does not reappear as new unactioned work

3. **Given** a state transition
   **When** it is applied
   **Then** it comes from the declared `(from_state, to_state, required_role)` data
   **And** the service locks the row, checks the expected prior state, refuses on mismatch, and appends the audit row in the same transaction

4. **Given** an item routed from one queue to another
   **When** the routing happens
   **Then** the item's queue field changes and no second item is created

## Tasks / Subtasks

- [x] `core/finding_keys.py` — the key mechanism, and the mixin a table declares with.
- [x] `collectors/models.py` — the declarations on `VulnerabilityFinding` and
      `LicenseFinding`.
- [x] `conda_sentinel.workflow` — a new application, adopted and installed.
- [x] `workflow/states.py` — the machine, as data.
- [x] `workflow/models.py` — `WorkflowItem`, `WorkflowTransition`, one migration.
- [x] `workflow/services.py` — `open_item` and `apply_transition`.
- [x] `tests/unit/django_apps/test_finding_keys.py`,
      `tests/integration/django_apps/test_workflow_transitions.py`.
- [x] The layering audit extended to cover the new application.

## Dev Notes

**Satisfies:** the model half of `CPM-FR-25`

**Governed by:**

- `CPM-AD-22` — One workflow app owns every queue item, keyed on a finding key
- `CPM-AD-23` — Transaction boundaries are per package, and audits are atomic with their write

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `APP.04-INT-001`
- Risks this story closes: `R-04`

### Project Structure Notes

- Domain applications live under `src/django_apps/`, the second import root declared
  in `pyproject.toml` by `CPM-PLATFORM-S01`. App adoption is explicit and two-line —
  a `pixi.toml` dependency plus an `adopted_apps` entry in `component.toml`, in that
  order. Entry-point discovery is forbidden (inherited `AD-8`).
- A domain app contributes only to `DATABASES`, `DATABASE_ROUTERS`, `INSTALLED_APPS`,
  `NAVIGATION_REGISTRY`, `CELERY_BEAT_SCHEDULE`, `CELERY_IMPORTS`, `CELERY_TASK_ROUTES` —
  never `AUTHENTICATION_BACKENDS`, `DEFAULT_AUTHENTICATION_CLASSES`,
  `DEFAULT_PERMISSION_CLASSES` or `MIDDLEWARE`.
- Every refusal raises `ImproperlyConfigured` — never a warning, never log-and-continue
  (inherited `CG-3`).

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- Time comes from the injected clock in `core` (`CPM-AD-26`); no module calls
  `timezone.now()` directly.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S04]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-22]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-23]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-25]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**The finding key is the story.** `CPM-AD-22` names the failure it prevents and it is
silent: an accepted finding resurrecting as new work tomorrow. Evidence is
append-only, so tonight's run inserts a *new row* for the advisory it saw yesterday;
an item keyed on an evidence row id would find no item for that row, open a second
one, and put a finding somebody accepted last week back at the top of a queue — with
the original still sitting there resolved and nothing failing anywhere.

**Files added:** `core/finding_keys.py`, the `conda_sentinel.workflow` application
(`states.py`, `models.py`, `services.py`, `apps.py`, one migration), and two test
modules.

**Files changed:** `collectors/models.py` (two declarations, no schema change),
`component.toml`, `config/settings/base.py`, and five existing tests whose rosters
this story widened.

**Each acceptance criterion:**

- **AC 1 (keyed on a declared natural key, never an evidence row id).** The key is
  `<table>:<package>:<digest>` — a readable prefix so a reviewer reading a queue
  knows what they are looking at, and a digest so the natural key can be as long as a
  version range needs without a column width to argue about. The digest is over a
  *length-prefixed* encoding rather than a joined string: any separator can appear
  inside an advisory identifier, and joining makes `("ab", "c")` and `("a", "bc")` the
  same key.
- **AC 2 (re-observation does not reappear as new work).** Three cases, because the
  obvious one is not enough: the same key across a week, and the *state* surviving —
  a service that reset an item to `open` on re-observation would create no duplicate
  row and would still put an accepted finding back in the queue. The uniqueness is a
  schema constraint rather than a rule the opening service keeps, because a rule
  enforced in one writer holds only until somebody writes a second one.
- **AC 3 (declared transitions; lock, check, refuse, audit in one transaction).**
  Four clauses, four separate failures, and a case each. The one worth reading is the
  stale move: the lock alone does not catch it, because by the time the lock is held
  the item is simply in a different state. What catches it is the caller saying what
  it *believed*.
- **AC 4 (routing changes the queue, creates nothing).** One row cannot diverge from
  itself; two can, which is the failure `CPM-AD-22` names.

**What the key deliberately excludes, and why each is a trap.** `matched_version` —
a package upgraded from 3.9.1 to 3.9.2 while an advisory is open would otherwise
produce a second item, punishing the person who did the work. `severity` — a source
that re-scores an advisory has changed how urgent one finding is, not created
another. `raw_license` — `Apache 2.0` and `Apache-2.0` are one compliance question,
and keying on the raw form opens a second review the day a source tidies its metadata.

**Two defects found while building it.**

*Declaring both `unique=True` and a named `UniqueConstraint`* creates two indexes for
one rule, and the field-level one is what the database names when it refuses — so the
case asserting the refusal could never match the constraint the table meant to
declare. Only the named constraint remains.

*A test that declared a Django model in its body* registered it in the app registry
for the rest of the session, and two unrelated audits then failed in the full suite
and passed when run alone. The case patches the declaration instead.

**What this story deliberately does not do: nothing opens items yet.**
`open_item` exists, is tested, and is called by no production code. Wiring it means
the policy run opening items, and `core/policy_run.py` importing `workflow.services`
would invert the orchestration exactly as `CPM-APP-S02`'s health projection nearly
did — `core` reaches its passes through a registry it declares, and a domain
application fills it. Whether the hook is a registered post-run step, a task beat
fires after the run, or a pass, is a real decision about `core`'s orchestration and
belongs with `CPM-APP-S05`, where the queues make it observable. The layering audit
now covers `workflow`, so the shortcut fails rather than passing quietly.

**Coverage:** the new modules at 100%. **One migration**, hand-named and depending on
the migration that creates `identity.Package` rather than on the latest one the
autodetector happened to see.
