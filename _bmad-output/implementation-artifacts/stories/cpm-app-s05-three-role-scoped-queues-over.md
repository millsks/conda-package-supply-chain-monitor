# CPM-APP-S05: Three role-scoped queues over one table

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a packaging engineer,
I want my own queue ranked by risk,
so that I work the highest-impact item first without seeing another role's work.

## Acceptance Criteria

1. **Given** the workflow table
   **When** the three queues are rendered
   **Then** they are filtered views over one table — identity review, remediation, compliance review

2. **Given** any queue
   **When** it is listed
   **Then** it is ranked by priority bucket then score, with usage breadth as the score input for identity items

3. **Given** a role
   **When** it opens a queue that is not its own
   **Then** access is refused, and the refusal is logged with the acting user identity
   (`APP.05-API-004`)

4. **Given** an item advanced by a reviewer
   **When** the action completes
   **Then** who acted, when, and the resulting state are recorded

5. **Given** the feedstock-gap surface
   **When** it is produced
   **Then** it excludes `unmapped` packages, which report `unknown` rather than absent
   (`APP.05-API-002`)

## Tasks / Subtasks

- [x] `core/after_run.py` — the seam `CPM-APP-S04` deferred, declared by `core`.
- [x] `workflow/opening.py` — the step that fills it; registered by `workflow/apps.py`.
- [x] `workflow/states.py` — `QUEUE_OWNERS`.
- [x] `core/permissions.py` — `roles_required()`, the seam a per-queue role needs.
- [x] `surface/queues.py` — the ranked, filtered read.
- [x] `surface/views.py` — `QueueView`; `surface/urls.py` — one route for three queues.
- [x] `surface/context_processors.py` — the nav, registered in `TEMPLATES`.
- [x] Template `conda_sentinel/queue.html`; the work history on package detail.
- [x] `tests/integration/django_apps/test_queue_views.py`.
- [x] `docs/development.md`.

## Dev Notes

**Satisfies:** the surface half of `CPM-FR-25`, and the surface half of `CPM-FR-4` (whose selection logic is `CPM-IDENTITY-S04`)

**Governed by:**

- `CPM-AD-13` — Authorization is declared per surface, enforced centrally
- `CPM-AD-22` — One workflow app owns every queue item, keyed on a finding key

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `APP.05-API-002`, `APP.05-API-004`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S05]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-13]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-22]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-25]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-4]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**This story wired what `CPM-APP-S04` deliberately left unwired.** `core/after_run.py`
declares a seam and `workflow/apps.py` fills it at `ready()`, exactly as
`policies/apps.py` adopts its passes — so the policy run opens queue items and
`core/policy_run.py` has still never heard of a queue. A failing step fails the run,
because a run that reports success with the queues it was meant to fill still empty
is nobody looking at work nobody knows exists.

**Files added:** `core/after_run.py`, `workflow/opening.py`, `surface/queues.py`,
`surface/context_processors.py`, `templates/conda_sentinel/queue.html`, and one test
module.

**Files changed:** `core/policy_run.py` (the hook and a summary field),
`core/permissions.py` (`roles_required()`), `workflow/states.py` (`QUEUE_OWNERS`),
`workflow/services.py` (`open_keyed_item`), `surface/views.py`, `surface/urls.py`,
`surface/detail.py`, two templates, `config/settings/base.py`, and three audits whose
rules this story sharpened. **No migration and no model change.**

**Each acceptance criterion:**

- **AC 1 (three filtered views over one table).** One function, one queue name, one
  route. The only thing that differs between the three is a string.
- **AC 2 (ranked bucket then score).** The priority pass's own order, reproduced
  rather than re-derived. The bucket is ranked by its *index* in `PRIORITY_BUCKETS`
  rather than by its value, because `p10` sorts before `p2` lexicographically. The
  ordering terminates on the finding key so a queue pages deterministically.
  Identity items rank on score alone, which is not a special case: an unmapped
  package has no bucket because `CPM-AD-4` blanked the verdicts one is derived from,
  so usage breadth is all there is — which is what the score already is.
- **AC 3 (a queue that is not yours is refused, and logged).** 403, not an empty
  page. The UX contract insists on the difference and it is the right insistence: an
  empty queue says *there is no work*, and somebody who reads that goes away
  satisfied.
- **AC 4 (who acted, when, resulting state).** Recorded by `CPM-APP-S04`'s
  `workflow_transitions` and made visible here, on the package detail screen — a
  record nobody can read from the page is one somebody has to be told exists.
- **AC 5 (the feedstock gap excludes unmapped).** True by construction: the
  confidence gate writes `unknown` rather than `absent`, so a filter for `absent`
  cannot return one. Worth a test *because* nothing had to be built — the behaviour
  rests entirely on the gate and a change there would take it away silently.

**Three things this story got wrong first and corrected.**

*The role check ordering was self-contradictory.* `QueueView` refused an unknown
queue before checking whether it existed, which made its own 404 unreachable — so a
reader who owns a queue and mistyped its URL was told a queue exists that does not,
which is exactly what the 404 was written to avoid. The name is now checked first.
There is nothing for the other ordering to protect: the nav lists all three queue
names to every role, so which queues exist is not a secret.

*The mixin's `required_roles` was a `ClassVar` being assigned per request.* Which two
requests could race on. `roles_required()` is the seam now, and it is the only place
in the product where the roles a surface wants depend on the request.

*Two audits were checking proxies rather than rules.* `test_policies_app` asserted
that nothing after `policies` declares a `ready()` — a proxy for "registers no pass",
which held only because `surface` had no `ready()` at all. `workflow` has one, for a
different registry, and the proxy failed while the rule was untouched. It now sweeps
for the call. `test_permission_audit` knew only about `permission_classes` and the
class attribute, and now recognises the method seam.

**Coverage:** the new modules at 100%.
