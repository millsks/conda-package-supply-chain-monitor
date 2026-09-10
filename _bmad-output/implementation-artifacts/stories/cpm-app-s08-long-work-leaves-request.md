# CPM-APP-S08: Long work leaves the request

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a security reviewer,
I want a recollection or a large export to run in the background,
so that the page returns instead of hanging on a rate-limited third party.

## Acceptance Criteria

1. **Given** a request
   **When** it needs an outbound call, a collector, a policy pass, or an export beyond the configured row cap
   **Then** the work is enqueued and the request returns an in-progress state

2. **Given** the export row cap
   **When** it is read
   **Then** it comes from one settings constant used by every export path

3. **Given** a request that needs none of those
   **When** it is handled
   **Then** it reads derived state and evidence, and may write workflow state or an override, synchronously

## Tasks / Subtasks

- [x] `core/jobs.py` — the boundary, as a registry plus a row a request can point at.
- [x] `core/models.py` + migration `0010_background_jobs` — `BackgroundJob`.
- [x] `core/queues.py` — the `export` workload class; `pixi.toml` drains it.
- [x] `core/tasks.py` — the generic job runner, routed to `export`.
- [x] `surface/exports.py` — the one comparison against the cap; the runner.
- [x] `surface/views.py`, `urls.py`, `apps.py`, two templates — the request half.
- [x] `tests/unit/django_apps/test_request_boundary_audit.py` — AC 1 and AC 2.
- [x] `tests/unit/django_apps/test_job_registry.py`, `tests/integration/django_apps/test_background_exports.py`.
- [x] `docs/development.md`.

## Dev Notes

**Satisfies:** `CPM-NFR-6`

**Governed by:**

- `CPM-AD-9` — The request/task boundary

**Constrained:** the row cap value and the p95 latency budget (`CPM-NFR-5`) are PRD Open Question 5. This story enforces that a single constant exists and is honoured everywhere; it does not choose the number.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S08]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-9]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-6]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**Three of AC 1's four triggers have no request path at all**, and that is the
interesting part. Nothing in `surface/` calls a collector, runs a policy pass or
makes an outbound call — so for those three the deliverable is not code, it is
`tests/unit/django_apps/test_request_boundary_audit.py`. The fourth, an export beyond
the row cap, exists and previously truncated.

**Files added:** `core/jobs.py`, `surface/exports.py`, migration
`0010_background_jobs.py`, `templates/conda_sentinel/export_job.html`, and three test
modules.

**Files changed:** `core/models.py` (`BackgroundJob`), `core/queues.py`,
`core/tasks.py`, `surface/views.py`, `surface/urls.py`, `surface/apps.py`,
`templates/conda_sentinel/report.html`, `base.html`, `pixi.toml`,
`tests/unit/django_apps/test_queues.py`, `tests/integration/django_apps/test_reports.py`.

**Each acceptance criterion:**

- **AC 1 (the work is enqueued, the request returns an in-progress state).** The
  audit walks the *import closure* of every registered view, not the view modules: a
  view importing the HTTP client would be obvious in review, and the one that arrives
  is a view importing a helper importing a service importing the client, three files
  apart with each edit reasonable on its own. The in-progress state is a redirect to
  the job's own page — a 202 with a body would leave a reader on a page that never
  changes, which is work handed off and, as far as they can tell, dropped.
- **AC 2 (one settings constant, every export path).** `over_the_cap()` is the only
  thing that compares anything against `CPM_SYNC_EXPORT_MAX_ROWS`, and the audit
  counts who reads the setting at all — the answer has to be small enough to name.
  The failure it prevents is invisible: two paths comparing the same number slightly
  differently produce a download that is simply short, and nothing says so.
- **AC 3 (everything else stays synchronous).** A case asserts an ordinary read
  enqueues nothing, and a report that fits is still produced in the request. A
  product where the small case also took a round trip through a worker would have
  paid the cost of the boundary everywhere to get its benefit somewhere.

**Four decisions worth recording.**

*`export` is a fourth workload class, not a share of `policy`.* An export is
database-heavy, makes no outbound call and tolerates minutes of latency; a report of
ten thousand rows queued behind the nightly sweep would delay it for somebody's
download. `tests/unit/django_apps/test_queues.py` caught the addition before
`pixi.toml`'s `-Q` had been touched, which is that gate doing exactly what it says it
is for.

*The work is published by name, never by importing the task.* `core/tasks.py` imports
the policy-run orchestrator and, through it, the collectors — so `run_job.delay`
would pull every one of them into the web process's import graph. The audit found
this: the chain was `workflow/api/views` → … → `core/jobs` → `core/tasks` →
`core/policy_run`. `EXPORT_JOB_TASK_NAME` moved to `core/queues.py`, which is
import-safe at settings time, and `send_task` needs nothing else.

*The artifact lives in the row.* Production's `STORAGES` names `FileSystemStorage`:
a worker writing to its own container's disk produces a file the web replica serving
the download cannot see, and the failure is a 404 that reproduces on some requests
and not others. Object storage would fix it and is not configured. `CPM-NFR-1` puts
the worst case at a couple of megabytes of text.

*The synchronous export refuses rather than truncates.* `CPM-APP-S06` shipped a
truncated file with a header saying so, which was the best available before the work
could leave. It is still the wrong artifact — a CSV in somebody's downloads folder
outlives the header that qualified it.

**Two things found by running it, and two by the audits.**

1. **An unreachable broker 500'd the request and left a phantom `queued` job.** The
   row is committed by the time `on_commit` fires, so the exception propagated past
   the redirect: a 500 that told the reader nothing, and a page that would have said
   "in progress" for ever. The publish now records the refusal on the job the reader
   is already being sent to. Verified against a real Redis that refused
   authentication.
2. **The celery *result backend* broke the hand-off.** Under `task_always_eager` with
   no Redis, `send_task` failed storing a result nothing reads. `ignore_result=True`
   — the job row is the result, and a second record of the same thing in a store with
   its own expiry is one more thing that can fail.
3. **The import-closure audit found `core.policy_run` reachable from a request** (see
   above), and **`core.transport` reachable through `surface/coverage.py` →
   `core/registry.py` → `core/collection.py`**. The second is pre-existing and real:
   the registry needs the `Collector` class at runtime for its `issubclass` refusal.
   It is recorded as a licensed **edge** rather than an exempted module, so every
   other path to the client still fails — and a case asserts the module is reachable
   *only* through that edge, which is what would notice if somebody widened the
   exemption later.
4. **A `# pragma: no cover` on a Protocol body** was refused by
   `test_coverage_policy.py`. Removed; the docstring is the body.

**Coverage:** every new module at 100%.
