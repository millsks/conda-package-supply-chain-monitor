# CPM-APP-S03: Package detail traced to its evidence

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a security reviewer,
I want every status on a package traced to the evidence that produced it,
so that I can check the reasoning rather than trusting the conclusion.

## Acceptance Criteria

1. **Given** a package
   **When** its detail view is opened
   **Then** each status links to the evidence rows behind it with source, observation timestamp and confidence

2. **Given** a package identity
   **When** it is displayed
   **Then** its provenance and confidence are shown, including any override and the reason recorded with it

3. **Given** superseded evidence
   **When** the detail view is rendered
   **Then** it remains reachable, and current values are shown without deleting history

## Tasks / Subtasks

- [x] `surface/detail.py` — the trace roster, the evidence projection, the identity
      panel's data and the run ledger's.
- [x] `surface/views.py` — `PackageDetailView`; `surface/urls.py` — the route, keyed
      on the canonical name.
- [x] Template `conda_sentinel/package_detail.html`; the health table now links to it.
- [x] `tests/unit/django_apps/test_detail_traces.py`.
- [x] `tests/integration/django_apps/test_package_detail_view.py`.
- [x] `docs/development.md`.

## Dev Notes

**Satisfies:** `CPM-FR-24`

**Governed by:**

- `CPM-AD-10` — Derived state is read-only to the application
- `CPM-AD-24` — Every read surface projects the same values

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S03]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-10]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-24]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-24]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**The screen answers *why*, and the whole design follows from refusing to re-derive
the answer.** Every pass cites the evidence it used, by foreign key, on the derived
row. So "which observation produced this status" is a fact the policy engine already
recorded, and reading it is the only answer that cannot drift from the verdict beside
it. Working it out again here -- newest row at or before the cut-off -- would be the
application deciding what a pass decided (`CPM-AD-10`), and would disagree silently
the moment a pass's selection rule changed.
`test_the_evidence_shown_is_the_row_the_run_cited_rather_than_the_newest` is the case
that would catch that, and it is deliberately set up so the two answers differ.

**Files added:** `surface/detail.py`, `templates/conda_sentinel/package_detail.html`,
`tests/unit/django_apps/test_detail_traces.py`,
`tests/integration/django_apps/test_package_detail_view.py`.

**Files changed:** `surface/views.py`, `surface/urls.py`, the health template (the
package name is now a link), `docs/development.md`. **No migration and no model
change.**

**Each acceptance criterion:**

- **AC 1 (each status links to its evidence, with source, timestamp and confidence).**
  Eight traces, each carrying the observations behind it. The confidence is
  `match_confidence` and is labelled as such: the UX contract requires that identity
  confidence and match confidence "are labelled differently everywhere they appear",
  and this is the screen where both are on display.
- **AC 2 (provenance, confidence, and any override with its reason).** The identity
  panel carries `identity_source`, `associator_key` and `resolved_at` beside the
  confidence. A human correction gets a panel of its own, headed as such, with the
  actor, both prior values, both new values and the reason -- and a package nobody
  corrected gets no panel at all, because a "Corrected by a human" heading over blank
  fields reads as a correction whose details were lost.
- **AC 3 (superseded evidence stays reachable; current shown without deleting
  history).** Two claims that pull against each other, so every case asserts both.
  Append-only (`CPM-AD-2`) is what keeps the history; marking the cited row is what
  keeps the current value unambiguous. A case asserts the render mutates nothing,
  over the rows themselves rather than a count -- the plausible mutation is an
  *update*, which a count does not catch.

**Two things worth recording.**

*Rendering the screen found a bug the tests had not.* Currency and Python readiness
choose their evidence relation per row, and a row that chose none fell into the same
branch as a status genuinely derived from other verdicts -- so the screen said
"derived from other verdicts, not from an observation" about currency, which is
false. Currency *is* observed from a version surface; that row simply cited nothing.
`NO_OBSERVATION_CITED` is now a third state, `Trace.observed` tells them apart, and
`test_a_status_that_cited_no_observation_does_not_claim_to_be_derived` holds it. On a
screen built to be checked, a false statement about how the product works is the
worst defect available.

*The route takes `<str:>` and not `<slug:>`.* A canonical name may carry a dot or an
underscore -- `ruamel.yaml`, `backports.zoneinfo` -- and `slug` matches neither, so
exactly the packages with awkward names would 404 while the health view linked
straight at them. Keyed on the name rather than the primary key because a URL pasted
into a ticket should say which package it is about; `CPM-FR-42` makes the name unique
and correctable, and the key stays the surrogate integer so a correction changes the
URL and breaks no foreign key.

**Coverage:** the new module at 100%.

**Gate:** `pixi run ci` cannot complete on this machine -- `test_image_payload.py`'s
`docker build` child zombies and pytest blocks, which reproduces on unmodified
`main`. Steps run individually; the GitHub gate runs that module.
