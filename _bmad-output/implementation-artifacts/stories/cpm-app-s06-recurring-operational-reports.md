# CPM-APP-S06: The recurring operational reports

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a platform lead,
I want the recurring reports produced from the same evidence the views use,
so that a report and the application never disagree.

## Acceptance Criteria

1. **Given** the rollup and evidence
   **When** the reports are produced
   **Then** daily KEV, weekly feedstock lag, Python 3.14 readiness, licence exceptions, unmapped identities, and stale-evidence-and-collector-failure reports are available

2. **Given** any report
   **When** it is rendered
   **Then** it states the evidence cut-off and policy version it was produced from

3. **Given** a report export
   **When** it is generated
   **Then** it carries the same freshness and confidence columns the application shows
   **And** a status value is emitted verbatim, with blank reserved for a field that has no value

## Tasks / Subtasks

- [x] `surface/reports.py` — the roster, the common columns, the projection.
- [x] `surface/views.py` — `ReportView` and `ReportExportView`; two routes.
- [x] Template `conda_sentinel/report.html`; the Reports nav entry.
- [x] `config/settings/base.py` — `CPM_SYNC_EXPORT_MAX_ROWS`, PROVISIONAL.
- [x] `tests/integration/django_apps/test_reports.py`.
- [x] `docs/development.md`.

## Dev Notes

**Satisfies:** `CPM-FR-26`

**Governed by:**

- `CPM-AD-11` — Current health is a refreshed rollup table, one row per package
- `CPM-AD-24` — Every read surface projects the same values

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `APP.06-INT-001`
- Risks this story closes: `R-01`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S06]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-11]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-24]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-26]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**Six reports, one mechanism, and the mechanism is the deliverable.** The three
criteria are really two rules applied six times: every report states the cut-off and
policy version it came from, and every status is emitted verbatim. A rule six views
each have to remember is a rule five of them keep — so a report here is a filter and
a column list, the provenance comes from the projection, and the freshness and
confidence columns are *composed onto* every report rather than written into each.

**Files added:** `surface/reports.py`, `templates/conda_sentinel/report.html`, and
one test module.

**Files changed:** `surface/views.py`, `surface/urls.py`,
`surface/context_processors.py`, the base template's nav,
`config/settings/base.py`. **No migration and no model change.**

**Each acceptance criterion:**

- **AC 1 (the six reports).** Checked against the requirement rather than against the
  roster's length: the six slugs are written out in the test, so a report dropped in
  a refactor fails a case naming what was asked for rather than one that counts
  entries and still passes at five.
- **AC 2 (states its cut-off and policy version).** Read off the rows by the
  projection rather than passed in by the view — a report that took its provenance
  from its caller could be handed the wrong one. It names **every** version the rows
  carry, because `CPM-AD-11` stamps a map per row and a replay leaves rows from two
  runs; claiming one version over rows produced at two would be false about its own
  provenance, and the reader most likely to check is the compliance reviewer.
- **AC 3 (the export carries the same columns, statuses verbatim).** The same rows as
  the page, from the same projection with a different bound — not a second query,
  which is how an export comes to disagree with the screen it came from. `CPM-AD-24`
  names this artifact when it says what the rule prevents, so a case walks every
  status column of every report and asserts none is ever blank.

**Two decisions worth recording.**

*The export's provenance travels in a header, not a row.* A row is data a spreadsheet
sorts into the middle of the report. A CSV in somebody's downloads folder next week
still has to be datable.

*`CPM_SYNC_EXPORT_MAX_ROWS` is PROVISIONAL at 5,000*, and is Open Question 5's second
number. It is deliberately **below** `CPM-NFR-1`'s ten thousand packages, so the cap
genuinely bites and the asynchronous path `CPM-AD-9` requires is a path this product
actually takes rather than one that ships untested until the day it matters.
`CPM-APP-S08` moves the work beyond it out of the request; until then an export at
the cap is truncated and *says so* in a response header, because silently handing
somebody a partial file is the worst of the three available behaviours.

**One thing found by running it.** Two of the six reports were written with guessed
reverse-accessor names — `packagelicense` and `packagepythonreadiness` rather than
the declared `license_policy_findings` and `python_readiness_policy_findings` — and
raised `FieldError` at request time, not at import. A roster is only as good as the
paths in it, so every report is now rendered against real rows by a parameterized
case.

**Coverage:** the new module at 100%.
