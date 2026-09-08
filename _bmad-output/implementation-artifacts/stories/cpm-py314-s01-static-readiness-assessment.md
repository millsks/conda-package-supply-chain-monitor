---
title: 'CPM-PY314-S01: Static readiness assessment'
type: 'feature'
created: '2026-09-07'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: true
baseline_revision: 'fd88744'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s03-licence-evidence-raw-normalized.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s06-whether-finding-can-actually-be.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s02-pypi-release-evidence.md
warnings:
  - oversized
deferred:
  - summary: >-
      A reader of this table cannot tell "identity has not resolved this package" from
      "it was never selected" or "it was selected and the run failed": all three leave no
      row. The residual of a spec contradiction amended in the Spec Change Log.
    evidence: |-
      **This entry records a residual, not work that was skipped.** The matrix row "Identity
      established nothing -> an `unknown` row saying identity has not resolved" asked for
      something unbuildable under the same story's Never list ("No change to `core/`"), which
      made it a HALT rather than a deferral; the 2026-09-09 Spec Change Log entry records the
      contradiction, amends the row and adds the Block If the spec should have carried. What
      remains after the amendment is the reader-facing residual below.
      **Which packages leave no row.** Six shapes, not the three the earlier wording named:
      a `release_ecosystem` mapping recorded `unknown`, `error` or `not_found`; **no mapping
      row at all**; an `established` mapping with a blank `primary_type`; and an `established`
      mapping naming another ecosystem. A seventh -- `established` for PyPI beside a blank or
      non-PyPI `primary_purl` -- used to fail a run every cadence for ever and now leaves no
      row either, because `selectable_packages` filters the purl as well as the type. A ledger
      sweep counting rows will under-count every one of them, which is why they are listed
      here rather than only in the Completion Notes.
      **Why no row is written.** `core/collection.py` writes evidence on four paths --
      `translate` (after a successful fetch), `not_found`, `error` and `not_applicable`. Two
      of them write with no outbound call: `_not_applicable`, which is the state this story
      forbids for an absence, and the rate-limiter refusal, which writes an `error` row
      claiming looking failed when nothing was looked at. Neither can carry "identity has not
      resolved", so an `unknown` row with no call made is not expressible against the shipped
      base. The three alternatives were all worse: a synthetic locator plus a collector-owned
      transport contradicts `CPM-AD-27`, which puts the transport boundary in the base
      precisely so a collector is a pure translation from a recorded payload (the audit list
      in `tests/unit/django_apps/test_collector_base_audit.py` is how that rule is enforced,
      not what states it); a locator guessed from `canonical_name` would send one wasted
      request per unresolved package per cadence to `pypi.org` and take a fact from a guess
      `CPM-FR-1` forbids; and an `error` row claims looking failed, which is a different wrong
      claim.
      **What is delivered instead.** `not_applicable` is **never** written for such a package;
      `inapplicability_of` answers nothing for every mapping outcome but `not_applicable`
      (swept over `MappingOutcome`'s members); the selection does not offer the package, so no
      ledger fills with failed runs; and a forced recollection is refused with
      `PythonReadinessIdentityError` whose message says the question is *unanswered rather
      than inapplicable*. Every read surface reports the package `unknown` for want of an
      observation -- `core/freshness.py`'s `UNOBSERVED_STATUS`, asserted end to end by
      `test_a_package_this_collector_has_not_observed_reads_as_unobserved`, which is the
      mechanism this whole argument rests on. Closing the residual needs a no-call `unknown`
      path in the base: a `core/` change, belonging with a story that owns that seam.
    location: >-
      src/django_apps/conda_sentinel/collectors/python_readiness.py -- PythonReadinessCollector.source_for
    severity: medium
  - summary: >-
      Six `Requires-Python` shapes need version ordering and are recorded `unknown` rather than
      answered; the gap is recorded rather than closed.
    evidence: |-
      `CPM-PY314-S01`'s Block If says a specifier shape the containment question cannot answer
      records `unknown` with the reason and records the gap. **Six shapes need the ordering
      rules `CPM-SECURITY-S06` established no architecture decision owns**: PEP 440's `===`
      arbitrary equality (a comparison of *strings*, so the answer depends on how the target is
      spelled), epochs, and pre-, post-, development- and local-version segments -- four
      separate segment kinds rather than one. The earlier wording said "five" and then listed
      six of them.
      **Two further shapes are `unknown` for reasons that are bounds rather than judgements**,
      and `docs/deployment.md` lists them to an operator beside the six: more than
      `MAX_CLAUSES` clauses, and a release of more than `MAX_RELEASE_SEGMENTS` segments. A
      ninth is `unknown` for a third reason -- a specifier wider than the column that records
      it, see the 2026-09-09 Spec Change Log entry. `_clause` additionally refuses four
      malformed shapes that need no ordering at all: an empty clause, a clause carrying no
      operator this product reads, a `.*` wildcard after an operator PEP 440 does not permit
      one on, and a `~=` that is not a compatible release. Those are not deferred work; they
      are a grammar refusing what is not a specifier.
      The reason is on the row and a `python_readiness.unreadable_specifier` event is emitted
      so a shape that turns out to be common is visible in a log rather than only in a column
      nobody aggregates. None of the six appears in a `Requires-Python` value in practice --
      the field is `>=3.x` or `>=3.x,<4` almost without exception -- so this is recorded rather
      than fixed, and closing it means deciding version ordering, which is a product decision
      rather than this story's.
    location: >-
      src/django_apps/conda_sentinel/collectors/specifiers.py -- _clause
    severity: low
  - summary: >-
      The static readiness cadence is a product decision made in code: `CPM-NFR-2` and PRD Open
      Question 7a have no row for this signal class, so weekly rests on nothing recorded.
    evidence: |-
      `CPM-NFR-2` fixes cadence per *signal class* and names only the **verification** half of
      `CPM-FR-14` ("on demand"); PRD Open Question 7a's table has rows for vulnerability/KEV,
      licence, version currency, inventory ingestion and "Python 3.14 verification", and **no
      row for the static pass at all**. So 7a's own premise -- "cadence is not open, CPM-NFR-2
      already fixes it per signal class" -- is false here, and `READINESS_CADENCE` is a
      judgement living in a `Final[timedelta]` with nothing upstream recording it.
      The judgement itself is argued at the constant and is defensible: what this collector
      reads is declared metadata, which changes when a project publishes a release and at no
      other time, and the daily collectors already watch for those releases. The arithmetic
      derived from it is correct -- `READINESS_FRESHNESS_TARGET` is `cadence x (1 +
      TOLERATED_MISSED_RUNS)` = 14 days, strictly greater than the 7-day cadence, which is
      7a's rule. What is owed is a signal-class row: a PRD or `CPM-NFR-2` amendment naming
      "Python 3.14 static readiness" with its cadence and tolerated missed runs, so a later
      reader finds the number where every other collector's number lives rather than only in
      this module.
    location: >-
      src/django_apps/conda_sentinel/collectors/python_readiness.py -- READINESS_CADENCE
    severity: low
---

# CPM-PY314-S01: Static readiness assessment

Epic: `CPM-EP-PY314` — Inferred and verified compatibility, kept apart

<intent-contract>

## Story

As a packaging engineer,
I want cheap metadata-based Python 3.14 assessment across the inventory,
so that I know where to spend expensive verification.

## Acceptance Criteria

1. **Given** a Python package
   **When** the assessment collector runs
   **Then** it performs a static metadata check and records the result as inferred evidence

2. **Given** a package where Python compatibility does not apply
   **When** the collector runs
   **Then** it records `not_applicable`

## Intent

**Problem:** `CPM-FR-14` splits Python 3.14 readiness into a cheap static pass and an expensive
verification pass, and the epic's whole purpose is that the two stay distinguishable. This story
is the cheap pass: it says where verification is worth spending, and it must never be mistaken
for verification.

**Approach:** A ninth collector, on the per-package path, writing its own evidence table. It
reads the package's declared Python metadata from the release ecosystem and records what that
metadata **claims** — never what it implies. The determinate values name inference explicitly,
so a reader cannot mistake a metadata claim for a build that ran.

## Boundaries & Constraints

**Always:**
- **A metadata silence is not a claim of incompatibility.** This is the single property the
  story turns on. Most projects have not yet declared 3.14 support, so:
  - metadata that **admits** 3.14 -> an inferred-compatible value
  - metadata that **excludes** 3.14 -> an inferred-incompatible value
  - metadata that **says nothing either way** -> `unknown`, never incompatible

  Reading the third case as the second would report most of the inventory as incompatible on
  no evidence, and would send verification effort exactly where it is least needed.
- **The determinate values name inference.** Not bare `ok` — the lesson `CPM-SECURITY-S01` was
  patched for and every security story since applied by construction — and not a bare
  `compatible` that `CPM-PY314-S02`'s verified result could be confused with. `CPM-FR-14`
  requires inferred and verified to be *distinct recorded states*, so the distinction lives in
  the values, not only in which table they sit in.
- **`not_applicable` only where identity established it.** The applicability signal is the
  release-ecosystem mapping outcome in `identity`, whose vocabulary is the four shared
  sentinels plus `established`. So:
  - the mapping is `established` -> the package has a release ecosystem, the question applies
  - the mapping is `not_applicable` -> identity established the question does not apply, and
    this collector records `not_applicable`
  - the mapping is `unknown`, `error` or `not_found` -> identity established **nothing**, so
    the compatibility question is *unanswered*, not *inapplicable*

  A package identity has simply not resolved yet is not a package without a Python ecosystem.
- Evidence is written by the base through its own table (`CPM-AD-7`). Time comes from the
  injected clock. A freshness target is declared and is strictly greater than the cadence
  (`CPM-AD-28`, and PRD Open Question 7a's rule).
- `pixi` is the only runner; `pixi run ci` exits 0.

**Block If:**
- Deciding whether a version specifier admits 3.14 requires version-ordering semantics this
  product has not decided. `CPM-SECURITY-S06` established that no architecture decision owns
  version ordering — do **not** cite one, and do not invent a general ordering rule. A
  specifier is a bounded, well-specified grammar and answering "does this admit 3.14" is a
  containment question, not a general comparison; if that turns out to be false for some
  specifier shape, record `unknown` for it with the reason and record the gap.
- **Added 2026-09-09.** Recording *which state* a package whose identity established nothing
  carries requires a write path this story's Never list forbids. `core/collection.py` writes
  an evidence row on four paths and only two of them write without an outbound call —
  `not_applicable`, which this story forbids for an absence, and the rate-limiter refusal,
  which writes `error`. If no path can write the state the matrix names, **stop and amend the
  matrix**; do not reach for `not_applicable`, do not guess a locator so that a row becomes
  writable, and do not add an exemption to the collector-base audit. The matrix row below is
  the amendment this Block If would have produced had it been written first — see the Spec
  Change Log.

**Never:**
- **No reading of another collector's evidence table.** `PyPIReleaseSnapshot` already stores a
  `requires_python` specifier, and reading it would be quicker. `CPM-AD-7` forbids it, the
  exemption list holds exactly one entry for a collector whose question is inherently about
  another's rows, and this collector's question is not. Read the source directly, as
  `CPM-SECURITY-S03`'s licence collector reads the channel it shares with the published-package
  collector.
- No verification, no build, no import, no subprocess. That is `CPM-PY314-S02`, on its own
  queue, on demand.
- No derived status or policy verdict — that is `CPM-PY314-S03` and `CPM-AD-8`.
- No change to `core/`, to any shipped collector, or to any policy pass.
- No `timezone.now()` anywhere.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Metadata admits 3.14 (AC 1) | a specifier or classifier that includes it | inferred-compatible, recording which signal said so | Never "verified" |
| Metadata excludes 3.14 | a specifier that cannot admit it | inferred-incompatible, recording the specifier verbatim | |
| Metadata says nothing (the common case) | no specifier and no version classifier | `unknown`, and the row says the project declared nothing | **Never** incompatible |
| Specifier and classifier disagree | the specifier admits, the classifiers do not list it | recorded as the disagreement it is, never silently resolved | A claim about somebody's package |
| Identity established no ecosystem (AC 2) | the release-ecosystem mapping is `not_applicable` | `not_applicable`, naming identity as the reason | The only path to it |
| Identity established nothing *(amended 2026-09-09)* | the mapping is `unknown`, `error` or `not_found`, or there is no mapping row | **no row at all**: the package is not selected, and a forced recollection is refused with `PythonReadinessIdentityError` saying the question is unanswered. Every read surface reports `unknown` for want of an observation (`UNOBSERVED_STATUS`) | **Never** `not_applicable`. The original row asked for an `unknown` *row*, which no base write path can produce without an outbound call — see the Spec Change Log |
| Identity established another ecosystem *(added 2026-09-09)* | the mapping is `established` with a non-PyPI `primary_type`, a blank one, or a `primary_purl` that is not a `pkg:pypi/…` | the same: not selected, and refused if forced | **Never** `not_applicable`, which diverges from `collectors/pypi_release.py` — see the Spec Change Log for what that divergence rests on |
| The source does not know the package | the release ecosystem returns nothing for it | `not_found` | Distinct from "declared nothing" |
| An unparseable specifier | a specifier this product cannot read | `unknown` with the raw value preserved and the reason | The Block If; never incompatible |
| A specifier shape that needs ordering | one the containment question cannot answer | `unknown`, the reason recorded, the gap recorded | Never guessed |
| Unreadable document | over the bound, not JSON, wrong shape, wrong field type | a document error; the base writes an `error` row and re-raises | Refused rather than partly read |
| Transport failure or spent allowance | the source fails or the limiter refuses | `error` row, ledger `failed` | Base path |
| A `Requires-Python` wider than its column *(amended 2026-09-09)* | the declared specifier exceeds `requires_python`'s width | `unknown`, with **no** specifier on the row and a `detail` saying why | Never truncated (a truncated specifier is a different specifier) and never `error` (the source answered) — see the Spec Change Log |
| A locator wider than its column | the purl builds a `source` value exceeding its column | refused before the window and the allowance | A row that cannot say where its observation came from |
| A value no database will hold | a NUL byte or a lone surrogate, in either signal | the document is refused; the base writes an `error` row | Refused where it enters: the driver refuses it several frames past the guard |
| A classifier wider than its column *(added 2026-09-09)* | any declared classifier exceeds `matching_classifier`'s width | read normally: only the classifier equal to the series marker is ever stored, and the series fixes its width | Measuring every declared classifier turned a readable document into an `error` row |
| Re-observation | the project declares 3.14 later | a new row; the old one stands | `CPM-AD-2` |
| Sentinel asked for a determinate value | `sentinel_evidence` asked for one | `CollectorConfigurationError` | Refused at the call |

</intent-contract>

## Code Map

- `src/django_apps/conda_sentinel/collectors/license.py` — the newest collector and the closest
  precedent. It reads a source a **sibling collector also reads**, independently, rather than
  reading that sibling's evidence table. Read it and `CPM-SECURITY-S03`'s Auto Run Result
  first; between them they carry the conventions this story needs and the defects not to
  repeat.
- `collectors/pypi_release.py` — reads the same host this collector must read, and already
  parses `info.requires_python`. **Do not import it and do not read `PyPIReleaseSnapshot`.**
  Read it to learn the document's shape, the field names and the bounds it enforces.
- `core/collection.py` — the base. The hooks this collector uses: `source_for`, `translate`,
  `inapplicability`, `sentinel_evidence`, `sentinel_evidence_rows`, `selectable_packages`,
  `cadence`. Note that its `not_found` branch bypasses `translate`.
- `collectors/models.py` — the eight evidence tables are the template. Add a ninth:
  `package` FK `PROTECT`, `source`, `state`, the declared specifier verbatim, the matching
  classifier if any, which signal decided it, `detail`, `trace_id`, a read index on
  `(package, -observed_at)`, `CheckConstraint`s, and **no unique constraint** (`CPM-AD-2`).
- `collectors/outcomes.py` — composed vocabularies live here, built by
  `core.outcomes.outcome_type`. The determinate members must name **inference**.
- `identity/models.py` — `MappingKind.RELEASE_ECOSYSTEM` and `MappingOutcome`, whose vocabulary
  is `core`'s four sentinels plus `established`. This is the applicability signal, and the only
  thing `CPM-AD-7` lets a collector read.
- `collectors/tasks.py`, `collectors/apps.py`, `src/config/settings/base.py` — the task, the
  roster (eight today, nine after), and the schedule entry reconciled against the declared
  cadence.
- `core/freshness.py` — the target must be strictly greater than the cadence (PRD Open
  Question 7a's rule, and the reason it exists).
- Roster and audit tests carrying a collector count: `tests/unit/test_model_registry.py`,
  `tests/unit/test_settings.py`, `tests/unit/django_apps/test_sweep.py`,
  `tests/unit/django_apps/test_collector_base_audit.py`,
  `tests/unit/startup/test_no_softening.py`,
  `tests/integration/startup/test_stage_two_collector_registry.py`. Update **every** one.
- `docs/deployment.md` — the collector sections are the template, and must say plainly that
  this collector infers and never verifies.

## Tasks & Acceptance

**Execution:**
- `collectors/outcomes.py` — the composed vocabulary, determinate members naming inference.
- `collectors/models.py` + a new migration — the table, its read index, its constraints.
- The collector module itself, plus whatever pure functions read the document and decide.
- `collectors/tasks.py`, `collectors/apps.py`, `config/settings/base.py`.
- Both test modules, covering every matrix row.
- Every roster and audit test carrying a count.
- `docs/deployment.md`.

**Acceptance Criteria:**
- Given metadata admitting 3.14, when the collector runs, then the row is inferred-compatible
  and names the signal that said so.
- Given metadata excluding 3.14, then the row is inferred-incompatible and stores the
  specifier verbatim.
- Given metadata saying nothing, then the row is `unknown` — never incompatible.
- Given a release-ecosystem mapping of `unknown`, `error` or `not_found`, then the row is
  `unknown` — never `not_applicable`.
- Given a mapping of `not_applicable`, then the row is `not_applicable`, naming identity.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

### 2026-09-08 — Recorded before implementation

**Why this collector re-reads a document a sibling already reads.**
`PyPIReleaseSnapshot.requires_python` already stores the specifier, and reading it would be
quicker. `CPM-AD-7` forbids it; the exemption list holds exactly one entry, for a collector
whose question is inherently about another's rows, and this one's is not. The precedent is
`CPM-SECURITY-S03`, which read the channel independently rather than reading
`CondaPackageSnapshot`.

It is also necessary rather than merely principled: the **classifiers** are the second static
signal and no collector stores them, so an independent read is required whatever the sharing
rule said.

**Where applicability comes from, and the trap in it.** `identity`'s release-ecosystem mapping
outcome is the signal, and its vocabulary already draws the distinction this story needs. A
package with no mapping row is **not** the same as a package identity determined has no release
ecosystem. Reading absence as inapplicability would record `not_applicable` for every package
identity has not resolved yet — a determinate claim from an absence, which is the defect class
found in every story of the preceding epic.

### 2026-09-09 — Recorded after review

**The spec was self-contradictory about the identity-unresolved row, and the correct response
was a HALT.** The matrix row "Identity established nothing → an `unknown` row saying identity
has not resolved" asked for something the architecture cannot deliver without the `core/` change
the same story's Never list forbids. Verified against the shipped base: `_write_evidence` is
reached from `collect()` at five call sites collapsing to four states — `not_found`, `error`,
`translate` (only after a successful fetch) and `_not_applicable`. Exactly two of them write
without an outbound call: `_not_applicable`, which this story forbids for an absence, and the
rate-limiter refusal, which reaches `_failed` and writes an `error` row. **No path writes an
`unknown` evidence row, and none writes any row carrying "identity has not resolved".**

The spec was wrong, not the implementation. This was not deferrable work — a `deferred` entry
records work left undone, and what happened here was an instruction that could not be followed —
so it is recorded here and the matrix row is **amended** to what is delivered: no row, the
package not selected, a forced recollection refused with a message saying the question is
unanswered rather than inapplicable, and every read surface reporting `unknown` for want of an
observation through `core/freshness.py`'s `UNOBSERVED_STATUS`. The Boundaries section gains the
**Block If** the spec should have carried for the applicability question: one was written for
the far less load-bearing specifier question and none for this. The reader-facing residual — that
"unresolved", "never selected" and "selected and failed" all look alike from the table — stays as
the first `deferred` entry, framed as a residual rather than as ordinary deferred work.

*(The earlier `deferred` wording contained a factual error: it said the `not_applicable` path was
the only one writing without an outbound call. The rate-limiter refusal does too. The conclusion
is unaffected — an `error` row is a different wrong claim, not a usable one.)*

**An `established` mapping naming another ecosystem had no matrix row, so the code decided it
unaided.** A row is added. This collector **refuses** such a package, where
`collectors/pypi_release.py`'s otherwise identical hook answers `not_applicable`. The divergence
follows from the matrix calling the mapping's own `not_applicable` "the only path to it" — but it
rests on an **unpinned identity convention**, and that is worth saying plainly: if resolution
records a non-Python conda artefact as `established` with `primary_type='conda'` rather than
recording the release-ecosystem mapping `not_applicable`, this collector writes **nothing** for
exactly the population AC 2 was written for. Nothing in `identity` currently forces one
convention over the other. A later story that fixes the convention should revisit this row.

**An over-long `Requires-Python` records `unknown`, not `error`.** The matrix carried two rows
pulling opposite ways: "a value wider than its column → refused where it enters" and "an
unparseable specifier → `unknown` with the raw value preserved". Decided for **`unknown`**: this
module has a purpose-built vocabulary for "a specifier this product will not read", and one too
wide to record is squarely that. Refusing the *document* recorded `error` — "looking failed" —
for a source that answered perfectly well, every run, for ever. The row carries **no** specifier,
because a truncated specifier is a different specifier and the row must not claim the project
declared what this product had to shorten; `OVERSIZE_SPECIFIER_DETAIL` says so, and
`docs/deployment.md` says it to an operator. The width rows in the matrix are split accordingly:
a locator is still refused before the window and the allowance, a value no database will hold at
all is still a document refusal, and a **classifier** wider than its column is now read normally
— the only classifier `matching_classifier` ever holds is the one equal to the series marker,
whose width the series fixes, so measuring every declared classifier against it turned one long
unrelated classifier into an `error` row for an otherwise readable document.

**`Programming Language :: Python :: 3` is not an enumeration.** The umbrella classifier is a
*superset* claim containing 3.14 rather than a list that omitted it. Counting it as an
enumeration made the commonest published shape there is — `>=3.9` beside `:: 3` and
`:: 3 :: Only` — a *disagreement*, which is `unknown`, which is exactly where `CPM-PY314-S02`
spends expensive verification: the defect ran in the direction this story exists to prevent.
Enumeration now requires a **dotted** version, since the series assessed is always a minor one.

## Design Notes

**Why a metadata silence is the whole story.** Most projects have not declared 3.14 support.
If "declares nothing" reads as "excludes it", the collector reports most of the inventory as
incompatible on no evidence, and `CPM-PY314-S02` spends expensive verification exactly where it
is least warranted — the opposite of what this story exists to do. The three-way split is not a
nicety; it is the product's usefulness.

**Why the determinate values name inference.** `CPM-FR-14` requires inferred and verified to be
*distinct recorded states*, and `CPM-AD-24` carries a state's value verbatim to every read
surface. A value called `compatible` on this table would appear on a queue beside
`CPM-PY314-S02`'s verified result and read identically. Naming inference in the value is what
makes the distinction survive the projection.

## Verification

**Commands:**
- `pixi run test`, `pixi run format && pixi run lint && pixi run typecheck`,
  `pixi run test-integration` — expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` — expected: "No changes detected".
- `pixi run ci` — expected: exit 0; coverage ≥ 90%, the new modules at 100%.
- `pixi run gate-postgres` — expected: the suite passes against `postgres:17`. The task can
  exit 3 on a coverage-combine artefact after every test passes; confirm `N passed, 0 failed`,
  the `no such table: context` signature and a zero-byte `.coverage.*` before treating it as
  real.

## Dev Notes

**Satisfies:** the static half of `CPM-FR-14`

**Governed by:**

- `CPM-AD-5` — One status type, fixed values, one precedence order
- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- Time comes from the injected clock in `core` (`CPM-AD-26`).
- Local gates are macOS only; the CI matrix adds ubuntu and windows. Compare paths with
  `Path.as_posix()`, never `str()`, and assert exception *types* rather than messages where an
  interpreter limit decides the refusal.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-PY314-S01]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-5]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-14]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 — `claude-opus-5`, via Claude Code.

### Debug Log References

- `pixi run test` — 6 450 passed after the review round (6 416 before it; 6 271 with the rosters
  updated and no new module).
- `pixi run test-integration` — 1 293 passed, 8 skipped after the review round (1 289 before).
- `pixi run typecheck` — `Success: no issues found in 161 source files`.
- `pixi run format` / `pixi run lint` — clean. Eleven autofixes taken (import order, `SIM300`),
  five fixed by hand: three `PLR0911` (`assess`, `_narrow`, `_clause` — one return per outcome,
  per operator and per refusal), one `PT012` in four constraint cases (the row is now built
  outside the `pytest.raises` block), and one `FBT001` (the parametrized `enumerated` flag is
  keyword-only; pytest passes fixtures by keyword).
- `pixi run makemigrations --check --dry-run` — "No changes detected".
- `pixi run ci` — **exit 0**. 7 749 passed, 2 skipped after the review round (7 718 before);
  total coverage **99.21 %** against a 90 % floor, with `collectors/python_readiness.py`,
  `collectors/specifiers.py`, `collectors/outcomes.py` and `collectors/models.py` all at
  **100 %**. The first gate run left
  four gaps — `_column_width`'s "declares no `max_length`" refusal, `_names_a_version`'s
  outside-the-namespace branch, `_covered`'s exclusion-merge loop, and the model's `__str__` —
  and a case was added for each; the merge case is parametrized over the four shapes the merge
  has to get right rather than the one that reached the line.
- `pixi run gate-postgres` — **exit 0**: 7 749 passed, 2 skipped against a throwaway
  `postgres:17`, so all three `python_readiness_assessments` constraints are enforced by a real
  backend and not only by SQLite.
- **Mutation checks run by hand for the two specifier gaps the review found.** Replacing
  `_covered`'s sort-and-merge block with a per-range `any(...)` now fails
  `test_several_exclusions_are_merged_before_the_coverage_question_is_asked[>=3.14,<3.14.2,…]`;
  flipping the inclusivity of any one of `>=`, `>`, `<=` or `<` now fails
  `test_a_bound_meeting_its_opposite_turns_on_which_end_is_inclusive`. All four mutants were
  green against the suite as first shipped.

**Note on task names:** this repository's pixi tasks are `format` and `typecheck`, not the
`fmt`/`check` some story text names, and the coverage task is `test-cov` rather than `cov`. The
Verification block's intent was run under the real names.

### Completion Notes List

**The determinate values are `inferred_compatible` and `inferred_incompatible`.**
`collectors/outcomes.py` composes `PythonReadinessOutcome` beside the three security
vocabularies and argues both halves where they argue theirs. Not `ok` — the lesson
`CPM-SECURITY-S01` was patched for — and not a bare `compatible`, because `CPM-FR-14` requires
inferred and verified compatibility to be *distinct recorded states* and `CPM-AD-24` carries a
state's value verbatim onto every read surface: a value called `compatible` would sit on a
queue beside `CPM-PY314-S02`'s verified result and read identically. No precedence is declared,
so `core.outcomes.aggregate` refuses both members outright until `CPM-PY314-S03` decides.

**There is deliberately no determinate member for a silence.** "The metadata said nothing" is
`unknown`, the sentinel `core` already has. A vocabulary with a third determinate value —
however carefully named — would put most of a real inventory into a claim nobody made.
`test_a_metadata_silence_is_unknown_and_never_incompatible` asserts the state *and* that it is
not `inferred_incompatible`, because a rename that made the two one string would satisfy the
first assertion alone.

**The containment question is data-shaped and lives in its own leaf module.**
`collectors/specifiers.py` reads a `Requires-Python` value as a bounded grammar over numeric
release segments and asks whether its clause set intersects the half-open interval
`[3.14, 3.15)`. Nothing there ranks two arbitrary versions or implements PEP 440's ordering; the
only comparison in the file is component-wise over integers with zero padding, which is what
PEP 440 says a release-segment comparison is. **No architecture decision is cited for version
ordering**, per `CPM-SECURITY-S06`. `DecidingSignal` lives there too, as a plain `TextChoices`
both `collectors/models.py` and the collector can import without closing a cycle — the shape
`collectors/spdx.py`'s `DetectionMethod` established.

**The series and not the point, which is a different answer rather than a nicety.** `>3.14`
excludes `3.14.0` and admits `3.14.1`; a reader asking "is this project ready for 3.14" means
the series. A point comparison would answer `excludes` and send verification somewhere it is
not needed. `!=` clauses are merged before the coverage question is asked, because
`>=3.9,!=3.14.*` admits nothing while its *bounds* admit everything.

**Two static signals, and the disagreement is recorded rather than resolved.** A classifier list
is positive-only, so its silence excludes nothing — but a project whose specifier admits 3.14
while its classifiers enumerate Pythons without naming it has said two different things, and
so has one whose specifier excludes 3.14 while a classifier names it. Both record `unknown` with
a `detail` naming the disagreement, and both transcribed columns survive on the row. Ranking one
signal above the other would be this collector deciding a claim about somebody else's package,
invisibly, in the one column a policy pass reads first.

**`not_applicable` has exactly one path to it, and this collector is stricter than its closest
sibling.** `inapplicability_of` answers a reason only for a `release_ecosystem` mapping recorded
`not_applicable`. `collectors/pypi_release.py`'s otherwise identical hook *also* answers for a
mapping established for another ecosystem; this one does not, because
`CPM-PY314-S01`'s matrix calls the mapping's own `not_applicable` "the only path to it". The
divergence is asserted in both directions, against the sibling's own function.
`test_no_other_mapping_outcome_makes_the_question_inapplicable` sweeps `MappingOutcome`'s own
members rather than a list written out in the test, so an outcome added later is **constrained**
by that case: it arrives as a new parametrization asserting the question stays applicable, rather
than quietly acquiring a determinate meaning nobody wrote a case about. The sweep does not *fail*
on a new member — `inapplicability_of` answers nothing for it by construction — and the earlier
wording claiming it did described a tripwire the file does not have.

**The absence trap is closed, and the row the matrix asked for was a spec contradiction.** A
mapping of `unknown`, `error` or `not_found`, an absent mapping row, an `established` mapping
with a blank type, one naming another ecosystem, and one naming PyPI beside a purl that is not a
PyPI purl all record **nothing** rather than `not_applicable`: the selection does not offer them,
and a forced recollection is refused with `PythonReadinessIdentityError` whose message says the
compatibility question is *unanswered rather than inapplicable*. The matrix asked for an
`unknown` **row** there and the base has no path that writes one without an outbound call, which
made the row unbuildable under the same story's Never list — a HALT rather than a deferral. The
2026-09-09 Spec Change Log entry records the contradiction and amends the row; the first
`deferred` entry now carries only the reader-facing residual and the full list of shapes that
leave no row. `test_a_package_this_collector_has_not_observed_reads_as_unobserved` asserts the
`UNOBSERVED_STATUS` mechanism the whole argument rests on, as all eight sibling suites do.

**No read of another collector's evidence table.** `PyPIReleaseSnapshot.requires_python` already
stores the specifier and reading it would have been quicker; `CPM-AD-7` forbids it and the
exemption list still holds exactly one entry. A source sweep asserts `PyPIReleaseSnapshot`,
`pypi_release_snapshots` and `pypi_release` appear nowhere in the module. It is also necessary
rather than merely principled: `test_a_classifier_alone_reaches_a_determinate_row_which_a_sibling_snapshot_could_not_have`
is a determinate row no sibling row could have produced, because nothing stores classifiers.
The host, the purl grammar, the document bound and two field names are **restated** here rather
than imported, and a unit case reconciles all six against `collectors/pypi_release.py` — because
restating them is right under `CPM-AD-7` and nothing else would have compared them.

**Three constraints, and the second is the opposite of the three security tables'.**
`readiness_signal_present_exactly_when_inferred` is the biconditional over the one column that
is a judgement rather than a transcription; `requires_python` and `matching_classifier` appear
in neither half, and a case asserts that *permission* as well as the two refusals, because a
constraint that tidied them away would delete the evidence an `unknown` row exists to leave
behind. `readiness_not_applicable_states_its_reason` **permits** `not_applicable` — which
`vulnerability_findings`, `kev_findings` and `license_findings` all refuse outright — and
requires a reason on it, because the only honest reason is one identity established and a silent
row would be indistinguishable from one written out of an absence.
`readiness_names_the_series_it_assessed` requires the assessed Python on every row including
sentinels, so `CPM-PY314-S02`'s verified result about a series and this one stay tellable apart.

**Cadence is weekly and the freshness target is a fortnight.** `CPM-NFR-2` fixes cadence per
signal class and names only the *verification* half of `CPM-FR-14` ("on demand"), so the static
pass takes the cadence its evidence justifies: declared metadata changes when a project
publishes a release and at no other time, and the daily collectors already watch for those.
`READINESS_FRESHNESS_TARGET` is `cadence x (1 + tolerated_missed_runs)` and is strictly greater
than the cadence (`CPM-AD-28`, PRD Open Question 7a). The response-cache TTL is thirty days,
deliberately longer than the cadence: a TTL inside it would make the cache inert.

**Schedule.** `cpm-sweep-python-readiness`, weekly, with a three-hour `countdown` — deliberately
neither the KEV entry's hour nor the licence entry's two, because entries sharing a phase fire
together and buy nothing. What it buys is that this sweep and `CPM-CURRENCY-S02`'s daily PyPI
sweep do not start at one instant on the one day in seven they share a tick, each spending its
own allowance against `pypi.org` (`CPM-AD-20`). `tests/unit/test_settings.py`'s phase case was
widened from "exactly these two" to "exactly these three, and the offsets are pairwise
distinct".

**Every roster and audit that carries a collector count was updated**, not only the ones that
failed: `tests/unit/test_model_registry.py`,
`tests/integration/startup/test_stage_two_collector_registry.py` (the roster and two prose
counts), `tests/unit/django_apps/test_sweep.py` (the per-package table and the task-name
parametrization), `tests/unit/django_apps/test_collector_base_audit.py` (`THE_NEW_MODULES` and
`THE_READINESS_COLLECTOR`), `tests/unit/startup/test_no_softening.py`,
`tests/unit/test_settings.py` (the sweep entries, the cadence map, the phase map),
`tests/unit/django_apps/test_inventory_ingestion.py`, `tests/unit/django_apps/test_transport.py`
and `tests/integration/django_apps/test_collection.py`. `src/django_apps/conda_sentinel/core/`'s
own "eight collectors" prose is deliberately **not** touched: this story's Never list forbids
changing `core/`, and those sentences are about a base written for collectors that were coming.

**Review round, 2026-09-09.** Eight defects and eleven smaller findings were fixed; the spec
contradictions among them are in the Spec Change Log rather than here.

- **The umbrella classifier is no longer read as an enumeration.**
  `Programming Language :: Python :: 3` is a superset claim containing 3.14, and counting it as
  a list that omitted 3.14 turned the commonest published shape into a `unknown` disagreement —
  inflating exactly the bucket `CPM-PY314-S02` spends expensive verification on. Enumeration now
  requires a dotted version. The old behaviour was *pinned* by a case, which is inverted.
- **The selection filters the purl, not only the type.** `identity` permits an `established`
  mapping to carry `primary_type='pypi'` beside a blank or non-PyPI `primary_purl`; such a
  package was offered, passed `asks_about`, and then raised from `project_locator`, which the
  base calls outside every `try` — a `failed` run with no evidence row, every cadence, for ever.
  `asks_about`'s docstring no longer claims the selection and the refusal agree exactly: the
  query is deliberately *narrower*, which is the safe direction.
- **The classifier width guard was removed and replaced by the property it was reaching for.**
  It measured every declared classifier against `matching_classifier`, a column only the series
  marker ever occupies, so one long unrelated classifier turned a readable document into an
  `error` row for ever. What remains is a NUL/encodability check on every classifier — those
  genuinely cannot round-trip — and a case asserting that `classifier_for(PYTHON_SERIES)` fits
  its column.
- **Two specifier tests that were line-covered and behaviour-covered by nothing.** The
  sort-and-merge block in `_covered` and the inclusivity of all four inequality operators
  survived mutation; five new cases kill them, and the mutants were run to confirm.
- **Guards that did not guard.** `assert "now" not in named or "timezone" not in named` is a
  disjunction satisfied by either half; it is two assertions now. And an integration case
  asserts `report.status == UNOBSERVED_STATUS`, which every one of the eight sibling suites has
  and which is the mechanism the first `deferred` entry's whole argument rests on.
- **Every operator-facing `*_DETAIL` constant is pinned to its words** rather than only to
  itself, so rewording `IDENTITY_UNRESOLVED_DETAIL` to say the question does not *apply* can no
  longer keep every case green while inverting the story's central distinction.
- **The `304` replay has a case.** `READINESS_CACHE_TTL` argues at length that a revalidated
  answer must write the row a `200` would have written, and nothing exercised it.
- **Six bounds gained an accepting-side case** — `MAX_CLAUSES`, `MAX_RELEASE_SEGMENTS`,
  `MAX_CLASSIFIERS`, `MAX_DOCUMENT_CHARACTERS`, the specifier width and the locator width — all
  of which were asserted only from the side that refuses.
- **Two loose citations corrected.** `CPM-AD-20` puts rate limiting in the shared base and says
  nothing about how an allowance is scoped; per-collector scoping is a property of
  `core/rate_limit.py`'s `window_key`, and the module says that instead. The first `deferred`
  entry cited a test list for what forbids a collector-owned transport; the owner is
  **`CPM-AD-27`**. (`CPM-AD-24` is cited for evidence-table `state` values and is scoped to
  *derived* status on API, export and governed views — a repo-wide pre-existing convention,
  noted rather than churned here.)
- **`DeclaredMetadata`'s words match its behaviour.** It said "exactly as stated" and
  "character for character" while `_classifiers_in` stripped; both now say what the strip does,
  and a case asserts a padded classifier still matches the series marker.

### File List

**New:**

- `src/django_apps/conda_sentinel/collectors/specifiers.py`
- `src/django_apps/conda_sentinel/collectors/python_readiness.py`
- `src/django_apps/conda_sentinel/collectors/migrations/0010_python_readiness_assessments.py`
- `tests/unit/django_apps/test_python_readiness.py`
- `tests/integration/django_apps/test_python_readiness.py`

**Changed:**

- `src/django_apps/conda_sentinel/collectors/outcomes.py` — `PythonReadinessOutcome` and its
  members.
- `src/django_apps/conda_sentinel/collectors/models.py` — `PythonReadinessAssessment`, its four
  column widths, its three constraint names and its read index; the module docstring's counts.
- `src/django_apps/conda_sentinel/collectors/tasks.py` — `COLLECT_PYTHON_READINESS_TASK_NAME`
  and `collect_python_readiness`.
- `src/django_apps/conda_sentinel/collectors/apps.py` — the ninth registration.
- `src/config/settings/base.py` — the `cpm-sweep-python-readiness` beat entry.
- `docs/deployment.md` — the collector's own section, the sweep counts, the cadence table, the
  offsets paragraph and the selection table; after the review round, the `unknown` row (four
  paths to five), the unreadable-specifier list, a paragraph on the umbrella classifier, and the
  selection table's purl requirement.
- `tests/unit/test_model_registry.py`, `tests/unit/test_settings.py`,
  `tests/unit/django_apps/test_sweep.py`,
  `tests/unit/django_apps/test_collector_base_audit.py`,
  `tests/unit/django_apps/test_inventory_ingestion.py`,
  `tests/unit/django_apps/test_transport.py`, `tests/unit/startup/test_no_softening.py`,
  `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/integration/django_apps/test_collection.py` — the rosters, audits and counts a ninth
  collector reaches.
- `_bmad-output/implementation-artifacts/stories/cpm-py314-s01-static-readiness-assessment.md` —
  this record and the two `deferred` entries.

## Auto Run Result

**Outcome:** done, with a follow-up review recommended. The headline finding is a defect in
**this spec**, not in the code.

**Review loop:** one iteration, four parallel layers. Eight must-fix, eleven should-fix.

**The spec demanded something the architecture cannot build.** The matrix required a row
carrying `unknown` for a package whose identity established nothing, while the same story's
Never list forbade changing `core/`. Verified independently: `_write_evidence` is reached from
`collect()` at five call sites collapsing to four states, no path writes an `unknown` evidence
row, and no path writes any row without an outbound call except the `not_applicable` one and
the allowance refusal. The requirement was unbuildable as written.

The correct response was a **HALT and a spec amendment**, not a `deferred` entry — a deferral
records work left undone, and this recorded an instruction that could not be followed. The
implementation's own note said as much, filed under the wrong mechanism. The matrix row is
amended to what is delivered, the Block If this story should have carried for the applicability
question is added, and the residual is recorded honestly: a reader cannot distinguish "identity
unresolved" from "never selected" from "selected and failed", because all three leave no row.
That residual is now asserted rather than asserted-about, by a case matching all eight sibling
suites.

**The defect that would have hurt most in production**, found independently by two layers. A
classifier naming only the major series was read as the project enumerating its Pythons and
omitting 3.14. It is a *superset* claim containing 3.14. So the commonest published shape —
`requires-python = ">=3.9"` with the umbrella classifier — was demoted from
`inferred_compatible` to `unknown`, carrying a detail asserting the classifiers do not name it,
which is false about a project that never enumerated minors at all. The harm ran in this
story's own direction, inflating exactly the bucket `CPM-PY314-S02` spends expensive
verification on.

**Two guards proved hollow by mutation, and one correction to the triage.** The specifier
merge logic was fully line-covered and entirely behaviour-uncovered: replacing the whole
sort/merge block with a naive per-range check left the suite green, because every existing case
was satisfiable by a single clause. And flipping one bound from inclusive to exclusive also
passed everything, while turning a project pinned to the target series into the one determinate
negative this collector may reach.

The triage claimed two added cases would kill all four inclusivity mutants. The fix pass
**applied the mutant, found the suite still green**, and added two more — the `>` branch is
never reached by the cases the triage named. All four now die where all four passed before.
That correction is the difference between an asserted fix and a measured one.

**A guard that could not fire, and a guard that fired too often.** The selection offered
packages whose identity names Python but carries a blank or foreign package URL, and
`source_for` then refused them outside any `try` — a `failed` run with no evidence row, every
cadence, forever, which is the exact shape the selection exists to prevent. And every classifier
was width-checked against a column only one of them can occupy, so one long unrelated classifier
turned a readable document into a permanent `error`. Restricting the check to the stored
classifier made it provably dead — the stored width is fixed by the series, not the document —
so it was removed and replaced by the property it was reaching for.

**Recorded rather than fixed.** Three `deferred` entries: the reader-facing residual above; six
`Requires-Python` shapes that need version-ordering semantics this product has not decided; and
a new one recording that the weekly cadence is a product judgement with no signal class in
`CPM-NFR-2` or PRD Open Question 7a to hang it on — the story's reading of `CPM-NFR-2` is
correct, which is precisely why 7a's premise is false for the static pass.

**Why a follow-up review is recommended.** The classifier defect turned on what a piece of
published metadata *means*, not on what the code does, and two reviewers had to reason about
packaging convention to catch it. The recognised-shape set will grow, and a later sweep should
re-read it against real published metadata rather than against this story's fixtures.

**Verification (run directly, not only reported):** `pixi run ci` — 7749 passed, 2 skipped,
coverage 99.21%; `python_readiness.py` 295/295, `specifiers.py` 142/142, `outcomes.py` 41/41,
all 100%. `makemigrations --check --dry-run` reports no changes. Against `postgres:17` the suite
passed 7749. Two `pixi run ci` invocations exited 3 on the known coverage-combine artefact,
confirmed each time by the three recorded checks; a run with random ordering disabled — which
is what the recorded diagnosis predicts — exited 0 and produced the figures above.
