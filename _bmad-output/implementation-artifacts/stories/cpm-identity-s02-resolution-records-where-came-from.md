# CPM-IDENTITY-S02: Resolution that records where it came from

Status: ready-for-dev

Epic: `CPM-EP-IDENTITY` — Every package resolved, or visibly not

## Story

As a packaging engineer,
I want each package resolved to its mappings with the provenance and confidence recorded,
so that I can tell a verified mapping from an inferred one.

## Acceptance Criteria

1. **Given** an inventory package
   **When** resolution runs
   **Then** it records canonical name, source repository, release ecosystem identity and zero or more feedstocks
   **And** every resolution records an identity source, an associator key and a confidence

2. **Given** a mapping cannot be established
   **When** resolution completes
   **Then** it records `unmapped`, never a guess

3. **Given** a package type to which a mapping does not apply
   **When** resolution completes
   **Then** it records `not_applicable`, distinct from `unmapped` and from a successful empty result

4. **Given** an existing `verified` confidence
   **When** a lower-confidence resolution runs
   **Then** it does not overwrite it

5. **Given** a package the inventory created and resolution has since renamed
   **When** the next ingestion sweep runs over the same source record
   **Then** it finds the same package row, and no second shell is created
   **And** the package goes on receiving snapshots on the row it already had

## Tasks / Subtasks

- [ ] Planned by `bmad-build` against the codebase at implementation time.
      Not pre-filled here: a task breakdown written now, before the epics ahead of
      this one have shipped, would be stale by the time the story is picked up.

## Dev Notes

**Satisfies:** `CPM-FR-1`, `CPM-FR-2`, `CPM-FR-6`

**Governed by:**

- `CPM-AD-1` — The package row is package identity and nothing else
- `CPM-AD-4` — Confidence gates every outward claim, by writing a value
- `CPM-AD-3` — Surrogate key, correctable canonical name
- `CPM-AD-14` — Governed reference data has exactly one write path

### The correction trap this story has to close

`CPM-IDENTITY-S06` writes the inventory's source package key straight into `canonical_name`,
because ingestion may never assert a mapping — it is a placeholder held at `unmapped` confidence.
Replacing that placeholder is this story's whole job. But `resolve_package_shell` currently *finds*
an existing shell by `canonical_name`, so the moment this story corrects one, the next sweep looks
up the old key, finds nothing, and creates a second shell. The corrected, verified package then
silently stops receiving inventory evidence while a duplicate `unmapped` row accumulates it, the
review queue shows the duplicate, and usage breadth is split across two rows.

**This is not an edge case — it is the normal lifecycle**, because correction is the expected
outcome for every package this story resolves. Five things close it:

1. **Join on the stable key, not the correctable one.** `CPM-AD-3` makes `canonical_name`
   correctable *by design*; using it as the inventory's join key is the defect.
   `CPM-IDENTITY-S06` already stores the stable key in `Package.associator_key` and in every
   `InventorySnapshot.source_package_key`, so the data is there. Resolution looks a package up on
   `(identity_source, associator_key)`.
2. **Make that pair a real key.** `CPM-FR-2` says every package row carries an identity source, an
   associator key and a confidence — which is to say the pair *is* the natural key from one
   source's point of view. `Package` is not evidence, so a `UniqueConstraint` on it is permitted
   (unlike on an evidence table). Without one, nothing stops a second shell appearing anyway.
3. **Resolution must not touch `identity_source` or `associator_key` while correcting a name.**
   `CPM-FR-2` already forbids overwriting a `verified` confidence with a lower one; this is the
   same class of invariant one layer down, and breaking it re-opens the trap invisibly.
4. **`CPM-IDENTITY-S05`'s audited human override is held to the same invariant.** `CPM-FR-3` lets
   a platform lead correct an identity on the record; that path must not orphan a package from its
   source either.
5. **The regression test spans both stories.** Ingest, resolve, ingest again — then assert exactly
   one `Package` exists and its snapshots continued on the same row. Nothing short of the full
   cycle proves the trap is closed.

Recorded here rather than discovered later: `CPM-IDENTITY-S06`'s review surfaced it, and S06 could
not close it, because the lookup is resolution's shape and correction is this story's.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-IDENTITY-S02]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-1]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-4]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-1]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-2]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-6]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
