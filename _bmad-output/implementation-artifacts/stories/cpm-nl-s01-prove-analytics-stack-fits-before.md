# CPM-NL-S01: Prove the analytics stack fits before adopting it

Status: ready-for-dev

Epic: `CPM-EP-NL` — Governed natural-language investigation

## Story

As a platform lead,
I want the analytics dependencies proven against this project's real constraints,
so that we discover an incompatibility in a spike rather than in an epic.

## Acceptance Criteria

1. **Given** the repository's conda-forge-only supply-chain rule, enforced by `tests/unit/test_dependency_policy.py`
   **When** the spike runs
   **Then** it reports whether LangChain and its transitive dependencies are available on conda-forge

2. **Given** the repository pins `python = "3.14.*"` with no alternative
   **When** the spike resolves LangChain
   **Then** it reports whether the dependency set resolves on 3.14, naming any package that does not — `langgraph` and `langchain-community` lag on 3.14 classifiers and `langchain-classic` caps at 3.13

3. **Given** the spike pattern already in the repository
   **When** the spike is added
   **Then** it follows `[feature.spike-storage]`: its own environment, a `spike_*.py` module excluded from the gate by name rather than by marker

4. **Given** the spike completes
   **When** its findings are recorded
   **Then** they state adopt, adopt-with-constraints, or reject, with the evidence for the verdict

5. **Given** a reject or adopt-with-constraints verdict
   **When** planning resumes
   **Then** the remaining `CPM-EP-NL` stories are authored against the verdict, not before it

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** the adoption gate on `CPM-FR-33` – `CPM-FR-35`

**Governed by:**

- `CPM-AD-17` — Two analytics components, one in-process and one a deployment unit

**Note:** `CPM-AD-16` — the second `DATABASES` alias, the router and the governed views — is architecturally settled and independent of the spike's outcome. It is authored once the spike reports, since its consumer shape depends on the verdict. ---

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `NL.01-INT-001`
- Risks this story closes: `R-01`, `R-09`, `R-10`, `R-13`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-NL-S01]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-17]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-33]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-35]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
