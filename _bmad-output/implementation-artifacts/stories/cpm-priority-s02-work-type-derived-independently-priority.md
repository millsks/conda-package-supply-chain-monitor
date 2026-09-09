# CPM-PRIORITY-S02: Work type, derived independently of priority

Status: done

Epic: `CPM-EP-PRIORITY` — A ranked, explainable queue of work

## Story

As a packaging engineer,
I want the recommended action computed separately from the priority bucket,
so that low-priority work still tells me what to do.

## Acceptance Criteria

1. **Given** a package in any priority bucket
   **When** the work-type policy runs
   **Then** a work type is computable, and the two are not coupled

2. **Given** a derived work type
   **When** it is stored
   **Then** it comes from the closed set of eight values, and a value outside that set is rejected

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-21`

**Governed by:**

- `CPM-AD-8` — Policy is a separate versioned pass

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-PRIORITY-S02]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-21]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**What ships.** The eighth policy pass, the fourth domain column on the rollup, and a
**working** derivation -- unlike `CPM-PRIORITY-S01`, whose rule set the PRD leaves
open, this story's closed set is fixed by PRD Appendix A.1 and what each of the eight
words means fixes when it applies.

**Files added:** `policies/work_type.py`,
`core/migrations/0009_package_health_work_type_status.py`,
`policies/migrations/0008_package_work_type.py`, and both test modules.

**Files changed:** `policies/outcomes.py` (the closed set as a composed vocabulary),
`core/models.py` (the rollup column), `policies/models.py` (the derived table),
`policies/apps.py` (registered **before** the priority pass), `docs/deployment.md`,
and six test modules carrying a roster, a module list, a migration list, the
rollup's contributable column set, its gated-column sweep or its version map.

**AC 1 (independent of priority)** is made structural three ways: the derivation's
signature is not offered a bucket, the module is swept for any mention of the
priority table, and the pass is registered *first* so no priority row exists for the
run when it executes. The integration tier asserts the two columns disagree on one
real rollup row -- which is the case that matters, because the shipped priority rule
set is empty and a coupled derivation would recommend nothing for anything.

**AC 2 (the closed set)** is a database check constraint rather than `choices`, which
Django enforces on neither `save()` nor a migration. The vocabulary is reconciled
against PRD Appendix A.1's own eight phrases rather than against itself.

**Two defects the tests found, and both changed the design for the better:**

1. `tests/unit/django_apps/test_confidence_gate_audit.py` caught the pass testing an
   identity confidence to derive `resolve_identity`. That is a second implementation
   of `CPM-AD-4`'s gate -- and it would have claimed something the product then
   erases, since the gate replaces every contributed value for an unmapped package.
   The confidence read is gone and `resolve_identity` is recorded as unreachable.
2. An integration case caught `validate_python_314` being recommended for a package
   nobody had collected anything about. The rule read "every readiness but
   `verified_ready`", which is true of `unknown`. It now fires on an *inference*,
   which is what `CPM-FR-14` says the static pass exists to point verification at.

**Coverage:** the new pass, table and vocabulary are at 100%.
