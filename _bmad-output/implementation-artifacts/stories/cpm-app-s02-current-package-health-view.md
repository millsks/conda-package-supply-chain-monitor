# CPM-APP-S02: The current package-health view

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a platform lead,
I want to browse, filter and sort current package health across the inventory,
so that I can see the whole estate and narrow to what matters.

## Acceptance Criteria

1. **Given** the rollup
   **When** the health view is rendered
   **Then** it carries every derived status with the observation timestamp behind each
   **And** it states when the underlying rollup was last recomputed

2. **Given** 10,000 packages
   **When** the view is requested
   **Then** results are paginated and no request returns the unbounded inventory

3. **Given** the view
   **When** filters are applied
   **Then** filtering by any derived status, confidence, priority bucket and work type is supported

4. **Given** a status of `unknown`, `not_found`, `not_applicable` or `error`
   **When** it is displayed
   **Then** it renders as itself and never as blank or as clean

5. **Given** the view at full inventory size with filters applied
   **When** its performance is measured
   **Then** it meets the configured p95 latency budget
   **And** a test bounds its query count, so a regression fails rather than merely slowing

## Tasks / Subtasks

- [x] `conda_sentinel.surface` — a new application for the read layer, adopted in
      `component.toml` and installed last in `LOCAL_APPS`.
- [x] `surface/health.py` — the projection: the rollup row joined to the evidence
      behind every status, in a bounded number of queries.
- [x] `surface/filters.py` — nine facets over rollup columns and derived tables.
- [x] `surface/tone.py` — how every status is drawn, and the audit that every one is.
- [x] `surface/views.py`, `surface/urls.py`, `surface/templatetags/health.py`.
- [x] `core/permissions.py` — `RoleRequiredMixin`, so an HTML view declares its role
      through the same check a DRF view does.
- [x] Templates `conda_sentinel/base.html` and `conda_sentinel/package_health.html`,
      and `static/css/conda-sentinel.css` lifted from the mockups.
- [x] `config/settings/base.py` — `CPM_HEALTH_VIEW_P95_BUDGET_MS`; `config/urls.py`.
- [x] `tests/unit/django_apps/test_tone.py`, `test_health_filters.py`,
      `test_app_layering_audit.py`.
- [x] `tests/integration/django_apps/test_package_health_view.py`,
      `test_health_projection.py`.
- [x] `docs/development.md`.

## Dev Notes

**Satisfies:** `CPM-FR-23`, `CPM-NFR-5`

**Governed by:**

- `CPM-AD-10` — Derived state is read-only to the application
- `CPM-AD-11` — Current health is a refreshed rollup table, one row per package
- `CPM-AD-12` — Pagination is structural  *(net-new: no pagination is configured today)*
- `CPM-AD-24` — Every read surface projects the same values

**Constrained:** the budget *value* is PRD Open Question 5. This story requires that a budget exists, is configured, and is enforced by a test; it does not choose the number.

**Test design.** Bound by the TEA system-level test design:

- Risks this story closes: `R-12`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S02]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-10]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-11]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-12]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-24]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-23]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-NFR-5]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**The story is a join, and the join is where the work is.** `CPM-AD-11` gives the
rollup four contributed statuses plus confidence and the run's stamps; the other five
the table shows -- vulnerability, KEV membership, licence, Python readiness, and the
priority score -- live in the per-domain derived tables `CPM-AD-21` keys on
`(package, policy_run)`. `surface/health.py` reads them at the health row's own run,
one query per table for the whole page, and returns a `Cell` carrying the status
verbatim, what observed it, and when.

**Files added:** the `conda_sentinel.surface` application (`health.py`, `filters.py`,
`tone.py`, `views.py`, `urls.py`, `apps.py`, `templatetags/health.py`), two templates,
one stylesheet, and five test modules.

**Files changed:** `core/permissions.py` (the mixin), `config/settings/base.py`,
`config/urls.py`, `component.toml`, `docs/development.md`, and four existing tests
whose rosters this story widened. **No migration and no model change** -- the read
surface adds no table, which is `CPM-AD-10` rather than a coincidence.

**Each acceptance criterion:**

- **AC 1 (every derived status, with the observation timestamp behind each).** Six
  status columns plus priority, work type, score and confidence. The dating is the
  half that needed its own module: `test_health_projection.py` builds derived rows
  whose evidence sits at *known, distinct* instants, because a cell dated by nothing
  and a cell dated wrongly look identical to an assertion that a timestamp exists.
  The readiness cell is the case that proves it -- `CPM-PY314-S03` made the kind of
  evidence part of the verdict, the row cites both relations, and a projection that
  always read `assessment` would date a proof by the metadata it superseded.
- **AC 2 (paginated, never the unbounded inventory).** `paginate_by` imports
  `DEFAULT_PAGE_SIZE` from `core/pagination.py` rather than repeating it -- Django's
  paginator and DRF's are separate mechanisms reading separate settings, which is
  exactly how a product ends up with a bounded API and an unbounded screen. Both
  orderings terminate on `package_id`, and a case walks every page of each: a
  non-deterministic ordering returns a row on two pages and another on none, which
  is invisible on page one.
- **AC 3 (filter by any derived status, confidence, bucket and work type).** Nine
  facets. Four are rollup columns and filter directly; four are derived tables and
  filter through an `Exists` correlated on both ids -- never a join, which would
  match a row from a different run and would multiply rows so the paginator reported
  a count that is not the number of packages. Each `Column` names the facet that
  narrows it, so a column shown but not filterable is a failing test rather than a
  checkbox nobody notices is missing.
- **AC 4 (the four sentinels render as themselves).** The integration module drives
  real policy runs with no collector evidence, so almost every status *is* a
  sentinel -- that is the point rather than a limitation. `tone.py` assigns every
  value of every rendered vocabulary a tone, each sentinel its own, and none of them
  the tone that means fine; a value with no entry gets the undecorated one, never
  the reassuring one.
- **AC 5 (the p95 budget, and a query bound).** `CPM_HEALTH_VIEW_P95_BUDGET_MS` is
  PROVISIONAL at 800ms with the reasoning beside it in `base.py` -- PRD Open
  Question 5 defers the value and this story is required to enforce a budget rather
  than choose the number. The query count is asserted **exactly** and at two very
  different page sizes: a `<=` would pass on an N+1 that stayed under a generous
  bound at fixture size and blew past it at `CPM-NFR-1`'s ten thousand packages. The
  stopwatch is deliberately the weaker of the two.

**Three things this story found.**

*`core` may not import a domain application's models, and nothing enforced it.* The
projection was written in `core` first, where it imported six derived models by name
and every test passed -- the registry inversion `core/policy_run.py` is built on
would have been gone, and the diff would have looked like six ordinary imports. Hence
`conda_sentinel.surface` and `test_app_layering_audit.py`. The rule turned out to be
narrower than first stated: `core/models.py` already imports `policies.outcomes`,
because `PackageHealth`'s columns take their `choices` from it. Vocabulary yes,
tables no.

*A status read out of a derived table bypasses `CPM-AD-4`.* The rollup's columns are
gated on the way in; a derived table holds what the pass wrote, ungated, because a
pass computes its verdict without knowing anything about identity. Reading them
straight onto the row put a confident `advisories_matched` for an unmapped package
beside five columns correctly saying `unknown` -- with every other cell looking
right. `test_an_unmapped_package_appears_rather_than_being_filtered_away` caught it.

*Tones cannot be spelled like statuses.* The mockups name their chip variants `ok`,
`warn`, `unknown`, `error` -- four of which are `OutcomeState` values -- so the first
tone table read, to `test_confidence_gate_audit.py` and to a human, as a mapping from
identity-confidence values to statuses. Every tone is now prefixed `tone-`.

**And one Django trap worth recording:** a multi-line `{# ... #}` is not a comment.
Django's lexer does not match across newlines, so the block renders as literal text
and any `{% %}` inside it is parsed -- which surfaced as `TemplateSyntaxError:
Unexpected end of expression in if tag` pointing at a tag that was inside a comment.

**Coverage:** the new modules at 100%.

**Gate:** `pixi run ci` cannot complete on this machine -- the `docker build` child in
`tests/integration/test_image_payload.py` zombies and pytest blocks, which reproduces
on unmodified `main`. Steps run individually instead; the GitHub gate runs that module.
