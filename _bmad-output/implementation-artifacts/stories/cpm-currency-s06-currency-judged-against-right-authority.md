---
title: 'CPM-CURRENCY-S06: Currency judged against the right authority'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: 'b5ce254d6f9056b197f8abbec811399ce45d51b1'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s01-upstream-release-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s02-pypi-release-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s03-feedstock-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s04-published-conda-package-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s07-policy-run-writer-rollup.md
warnings:
  - oversized
deferred:
  - summary: >-
      Nothing in the product writes `Package.version_authority_order`, so every package is judged
      on the documented default and an operator has no supported way to record an authority.
    evidence: >-
      `CPM-AD-6` makes the order data on the package and AC 1 says the applied order is the one
      recorded there; the column, its validator and its default all exist, and the only route to a
      non-default value is a hand-written `UPDATE`. Unlike `CPM-IDENTITY-S05`'s audited identity
      override, a change to this column changes derived verdicts and leaves no audit row. The write
      path is an application concern that no story currently claims.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/models.py --
      Package.version_authority_order
    severity: medium
  - summary: >-
      A currency run issues four evidence queries per package and nothing batches them.
    evidence: >-
      The orchestration loops packages one at a time and this pass reads each of its four surfaces
      separately inside that loop, so a run over `CPM-NFR-1`'s ten thousand packages is forty
      thousand round trips for this pass alone, multiplying as the remaining passes land.
      `collectors/selection.py` already established the set-based read for exactly this shape. The
      query count is now pinned by a case so a regression is visible, but the optimisation belongs
      with the story that first runs a policy pass at inventory scale.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/policies/currency.py --
      CurrencyPass.evaluate
    severity: medium
  - summary: >-
      `core` now imports `policies` at module scope, so the machinery application cannot be
      imported without the domain application, and the same edge lands once per policy epic.
    evidence: >-
      The rollup's status column must declare choices drawn from a vocabulary the domain owns, and
      the leaf module dodges the import cycle rather than the dependency direction.
      `policies/apps.py` argues that `core` holds the machinery and must not grow a domain policy --
      that rule now holds in the source tree and fails in the import graph. Alternatives, such as
      the vocabulary reaching the column through the pass's declaration or a registered choices
      provider, were not weighed, and no import-direction audit would notice the next seven.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/models.py --
      PackageHealth.currency_status
    severity: medium
---

# CPM-CURRENCY-S06: Currency judged against the right authority

Epic: `CPM-EP-CURRENCY` — Where a package sits across every surface

<intent-contract>

## Story

As a packaging engineer,
I want each package compared against the ecosystem that is actually authoritative for it,
so that a package is never called stale against a registry it never published to.

## Acceptance Criteria

1. **Given** a package
   **When** the currency policy runs
   **Then** it compares source, PyPI, recipe and published conda versions using the authority
   order recorded on that package
   **And** the chosen authority and its supporting evidence are stored with the result

2. **Given** no authority is explicitly set
   **When** the policy runs
   **Then** it applies the documented default order

3. **Given** a package current at source but behind on the feedstock
   **When** currency is computed
   **Then** the two are expressible separately, per surface

## Intent

**Problem:** Four collectors write four surfaces of evidence and nothing reads them. Nothing
compares a package's versions, nothing records which ecosystem was authoritative for it, and
the rollup carries no derived status at all -- `contributable_columns()` is empty and says in
its own docstring that it is waiting for this epic's column. `CPM-AD-6` fixes that the
authority order is data on the package with a documented default; nothing stores one.

**Approach:** The first real policy pass, in the `policies` application the architecture's
source tree names and this story creates. `CurrencyPass` reads the four snapshot tables at the
run's cut-off, computes a per-surface currency verdict and an overall verdict against the
authority order recorded on the package, writes its own derived table keyed
`(package, policy_run)`, and contributes one rollup column. It reads evidence and writes no
evidence (`CPM-AD-8`), and it never writes the rollup (`CPM-AD-21`).

## Boundaries & Constraints

**Always:**
- A pass reads evidence at the run's stated cut-off and never reads the current time to
  decide anything. Re-running the same version at the same cut-off reproduces identical
  output (`CPM-AD-8`).
- The pass writes only its own derived table, keyed `(package, policy_run)`, and contributes
  rollup columns by returning them -- never by writing the rollup itself (`CPM-AD-21`).
- Currency is computed **per surface** and stored per surface, so "current at source, behind
  on the feedstock" is a fact the table holds rather than one a reader infers (AC 3).
- The chosen authority and the evidence rows supporting it are stored on the result (AC 1).
- Every derived status is a `CharField(choices=...)` over an `OutcomeState`-derived type
  composed by `core.outcomes.outcome_type` (`CPM-AD-5`). Never a boolean, and the composed
  type is bound once at module scope.
- Version comparison is this pass's and nobody else's: no collector computes it, and the
  comparison rule is documented where it is written.
- A surface with no observation is `unknown`, never `ok`; a surface that does not apply to
  the package is `not_applicable`. The five states stay un-collapsed (`CPM-FR-6`).
- The atomic unit is one package (`CPM-AD-23`); the orchestration already provides it.
- `pixi` is the only runner; `pixi run ci` exits 0 at the end.

**Block If:**
- Deciding currency would require a version *ordering* rule that the PRD does not fix and
  this story cannot derive. This story compares for **equality against the authority**, and
  records `behind` only where the authoritative surface states a version the compared surface
  does not carry. If review finds that a comparison of that shape cannot satisfy AC 1, HALT
  rather than inventing a version-ordering scheme.

**Never:**
- No change to any collector, to any evidence table, or to what any of them records.
- No new outbound call of any kind. A pass makes none (`CPM-AD-9`).
- No write to the rollup table from this pass, and no re-derivation of a status another pass
  owns.
- No priority, score, rank, or recommended work -- those are `CPM-EP-PRIORITY`'s.
- No feedstock *presence or maintenance* verdict: that is `CPM-FR-40` and
  `CPM-CURRENCY-S07`, the next story. This story judges version currency only.
- No `timezone.now()` anywhere; every instant is the run's or the clock's.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Authoritative surface agrees | package with a recorded authority order whose first available surface states `1.2.3`, and the compared surfaces state `1.2.3` | one derived row: per-surface verdicts `current`, overall `current`, the chosen authority named, and the evidence rows it was read from referenced | No error |
| Behind on one surface (AC 3) | source states `2.0.0`, feedstock recipe states `1.9.0` | source `current`, feedstock `behind`, overall `behind`; both are readable separately from the row | No error |
| Default authority order (AC 2) | package with no authority recorded | the documented default order is applied and the row records that it was the default rather than a stored choice | No error |
| Authority recorded on the package | the package carries an explicit order | that order is used, and the row names which authority it chose from it | No error |
| Authority surface unobserved | the first authority in the order has no evidence at the cut-off | the next authority in the order is chosen, and the row records which was chosen and that earlier ones were unobserved | Never `ok` from an absent observation |
| No surface observed at all | no evidence for any surface at the cut-off | every per-surface verdict `unknown`, overall `unknown`; a row is still written | A package nobody observed is not current |
| Surface not applicable | the PyPI snapshot for the package records `not_applicable` | that surface's verdict is `not_applicable`, and it is never the chosen authority and never makes the package behind | `CPM-FR-6`'s third state, carried through |
| Surface errored | the latest snapshot for a surface records `error` | that surface's verdict is `error`; the overall verdict is not `current` | An error is not an absence |
| Evidence after the cut-off | a snapshot written after the run's cut-off | it is not read, and the verdict is what the cut-off's evidence supports | `CPM-AD-21` |
| Replay (`CPM-AD-8`) | the same version re-run at the same cut-off | byte-identical derived rows, and the earlier run's rows are untouched | `(package, policy_run)` keying |
| A package with no evidence tables populated | a fresh inventory | a row per package carrying `unknown`, and the rollup column carrying `unknown` | Never a clean result |
| Rollup contribution | the pass returns its column | the orchestration writes it onto the rollup after the confidence gate; the pass never writes the row | `CPM-AD-21` |
| Contributing an undeclared column | a pass returning a column it did not declare | refused by the orchestration | Already built |
| Unresolved package | a package at `unmapped` confidence | the pass computes and returns as usual; the confidence gate is the rollup writer's, not this pass's | `CPM-AD-4` is not re-implemented here |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/policy.py` -- `PolicyPass` is the
  base: three declarations (`name`, `derived_model`, `contributes`) and one method,
  `evaluate(package, *, policy_run, evidence_cutoff)` returning the rollup columns it
  produced. `register_pass` refuses a pass declaring the rollup as its derived model, and
  refuses a contribution to a column the rollup does not have. Read it fully first.
- `src/django_apps/conda_package_supply_chain_monitor/core/policy_run.py` --
  `execute_policy_run` and `choose_evidence_cutoff`: the cut-off is a completed collection
  run's `finished_at`, the passes run per package in declared order inside that package's
  transaction, and a pass returning an undeclared column is refused. This story adds a pass
  to that machinery and changes none of it.
- `src/django_apps/conda_package_supply_chain_monitor/core/rollup.py` --
  `contributable_columns()` reads the rollup's own fields and is **empty today**; its
  docstring names `currency_status` as the column this epic adds. `permitted_values` is what
  checks a contributed value against the column's choices.
- `src/django_apps/conda_package_supply_chain_monitor/core/models.py` -- `PackageHealth`
  (table `package_health`) carries only stamps today: `package`, `policy_run`, `computed_at`,
  `evidence_cutoff`, `confidence`, `policy_versions`. Add `currency_status`, a
  `CharField(choices=...)` over the composed currency outcome type, and its migration in
  `core`.
- `src/django_apps/conda_package_supply_chain_monitor/core/outcomes.py` -- `outcome_type`
  composes a per-status type carrying the four sentinels by construction. `identity/models.py`
  binds `MappingOutcome` at module scope and explains why binding it twice would be wrong:
  follow that exactly for the currency type.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` -- the four
  snapshot tables this pass reads: `SourceReleaseSnapshot` (`latest_version`, `state`),
  `PyPIReleaseSnapshot` (`latest_version`, `state`), `FeedstockSnapshot` (`recipe_version`,
  `state`), `CondaPackageSnapshot` (`published_version`, `state`, `channel`, `platform`).
  Read only. `snapshot_as_of` in that module is the cut-off-bound read pattern to follow --
  note it orders by `-observed_at`, `-pk` so a replay is reproducible.
- `src/django_apps/conda_package_supply_chain_monitor/identity/models.py` -- `Package`. The
  authority order is data on the package (`CPM-AD-6`) and no column holds one yet; add it
  here as a list column with a documented default, on the terms `alternative_purls` and
  `cpes` are declared (`JSONField(default=list, blank=True)`, never NULL).
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` -- the template for
  a new application's `AppConfig`, including its `ready()` and the registration guard.
- `src/config/settings/base.py` -- `LOCAL_APPS` (line ~193) appends each domain application
  after the stage-two owner and says why. Add `policies` last.
- `component.toml` -- `adopted_apps` (line ~67) is `CPM-AD-8`'s declaration of the same
  adoption, in order. Add `policies` last. `tests/unit/test_component_declaration.py` reads it.
- `tests/unit/test_import_roots.py`, `tests/unit/test_installed_apps_ordering.py`,
  `tests/unit/test_model_registry.py`, `tests/unit/django_apps/test_migration_completeness.py`,
  `tests/unit/django_apps/test_pass_ownership_audit.py`,
  `tests/unit/django_apps/test_outcome_field_audit.py`,
  `tests/unit/django_apps/test_derived_status_writability_audit.py`,
  `tests/unit/django_apps/test_evidence_constraint_audit.py` -- the audits a new application,
  a new model and the first derived status all reach. Run them early; several sweep an empty
  set today and will start mattering.
- `tests/unit/django_apps/test_policy_registry.py`, `tests/unit/django_apps/test_rollup_row.py`,
  `tests/unit/django_apps/test_policy_contribution.py` -- where the pass machinery is proved;
  the first real pass belongs beside them.
- `docs/deployment.md` -- the collector sections are the template; add what an operator has
  to know about the currency pass and the authority default.

## Tasks & Acceptance

**Execution:**
- `src/django_apps/conda_package_supply_chain_monitor/policies/` -- **new application**:
  `__init__.py`, `apps.py` (an `AppConfig` registering the pass in `ready()`, guarded as the
  collectors app guards its registrations), `models.py`, `migrations/`.
- `config/settings/base.py`, `component.toml` -- adopt it, appended last in both.
- `identity/models.py` + migration -- the per-package authority order, with the documented
  default and a refusal for an order naming a surface that does not exist.
- `core/models.py` + migration -- `currency_status` on the rollup, over the composed type.
- `policies/currency.py` -- the composed `CurrencyOutcome` type bound once at module scope;
  the pure comparison functions (a surface's observed version at a cut-off, a per-surface
  verdict, the authority choice over an order, and the overall verdict); and `CurrencyPass`.
- `policies/models.py` + migration -- the derived table keyed `(package, policy_run)`, one row
  per package per run, carrying the per-surface verdicts, the overall verdict, the chosen
  authority, whether the order was the default, and references to the evidence rows the
  verdict rests on.
- `tests/unit/django_apps/test_currency_policy.py` -- new: every matrix row reachable without
  a database, the composed type's sentinels, the comparison functions, the authority choice
  over every order shape, and the module's own source sweeps.
- `tests/integration/django_apps/test_currency_policy.py` -- new: the pass through a real
  policy run against real snapshot tables, replay reproducing identical rows, the cut-off
  excluding later evidence, per-surface separability, and the rollup column arriving through
  the orchestration rather than from the pass.
- The audit and roster updates the new application and the new models require.
- `docs/deployment.md` -- the operator section.

**Acceptance Criteria:**
- Given a package whose source states one version and whose feedstock recipe states an
  earlier one, when the pass runs, then the derived row records the source surface current and
  the feedstock surface behind, separately.
- Given a package with no recorded authority order, when the pass runs, then the documented
  default order is applied and the row records that it was the default.
- Given a package whose first authority has no observation at the cut-off, when the pass runs,
  then the next authority is chosen and the row says which.
- Given the same policy version re-run at the same cut-off, when both runs complete, then the
  second run's derived rows are identical to the first's and the first's are untouched.
- Given a package with no evidence at all, when the pass runs, then every surface reads
  `unknown` and the rollup column reads `unknown`.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

### 2026-09-06 — `CurrencyOutcome` is bound in `policies/outcomes.py`, not `policies/currency.py`

**Task item amended.** The Execution list says "`policies/currency.py` -- the composed
`CurrencyOutcome` type bound once at module scope". Two modules need that type:
`policies/models.py`, whose per-surface columns declare it as their `choices`, and
`core/models.py`, whose rollup column `currency_status` declares the same vocabulary so
`core/rollup.py`'s `permitted_values` can check a contribution against it. `policies/currency.py`
imports `core.policy`, which reaches `core.models` -- so a type bound there and read by
`core/models.py` closes an import cycle and fails at `django.setup()`.

The Code Map's own instruction is what the amendment follows: "`identity/models.py` binds
`MappingOutcome` at module scope and explains why binding it twice would be wrong: follow that
exactly for the currency type." `identity` solved the same cycle by moving the vocabulary into a
leaf module that imports nothing -- `identity/confidence.py`, which says so at length -- and
`policies/outcomes.py` is that shape applied here. The type is still composed by
`core.outcomes.outcome_type` and still bound exactly once; only the module it is bound in moved,
and `policies/currency.py` imports it from there.

Nothing else in the story changes: the pure comparison functions and `CurrencyPass` are in
`policies/currency.py` as the task item states.

## Review Triage Log

### 2026-09-06 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 24: (high 4, medium 16, low 4)
- defer: 3: (high 0, medium 3, low 0)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[high]` `[patch]` One inapplicable surface took the whole package's verdict away. The
    reduction sent `not_applicable` through `core`'s order, where it outranks the determinate
    value, so a package current on source, feedstock and conda and inapplicable on PyPI read
    `not_applicable` overall — and the PyPI collector writes exactly that row for every
    non-Python package. The rollup's first domain column would have reported "no currency
    question applies here" for a large population where three surfaces answered. Inapplicable
    surfaces are dropped before the reduction, and `not_applicable` is the package's verdict
    only when every surface is.
  - `[high]` `[patch]` The verdict ranking was written as control flow specifically so the
    single-ordering audit would not see it, which made the audit evadable by anyone willing to
    spell an order as an `if`. The order is now data in the module that owns the vocabulary,
    the audit is taught about it by name in both directions, and `error` outranks `behind` —
    so a surface that could not be read at all is no longer reported as a discrepancy that
    was found.
  - `[high]` `[patch]` The replay the architecture requires was not an operation the product
    offered: the orchestration took no cut-off and re-derived one, so the boundary moved
    whenever a collection finished in between, while the operator documentation told readers
    they could replay a run and diff it. An explicit cut-off is now accepted, and the replay
    case finishes a later collection run between the two and replays against the original.
  - `[high]` `[patch]` Two database constraints were asserted by name only, and a reviewer
    demonstrated that weakening either left the whole suite green — every test path went
    through the pass, which cannot produce a violating row, while the constraints exist for
    the hand-written write that can. Both are now proved by the database refusing a row, with
    the determinate-verdict one parametrised so each conjunct is load-bearing.
  - `[medium]` `[patch]` Sixteen further findings, each addressed: the published-package
    tie-break was decided by insertion order in exactly the case that matters, because one
    sweep stamps every row with the run's single instant; a bare tag prefix survived as a
    version and could become the chosen authority; the rollup module still said in three
    places that no column was contributable, which this story made false; four test-module
    docstrings said the same; the audits' scope anchor did not name the new application; the
    prefix reconciliation — the one deviation from the specified comparison rule — was never
    exercised through the pass, though the source collector provably writes the tagged form;
    nothing asserted that a surface *ahead* of the authority also reads behind, which is the
    property distinguishing an equality rule from a smuggled-in ordering; a constant claiming
    to be the single surface-to-column map was read by nothing in the source; the derived
    row's authority columns were editable; the row could not distinguish a false discrepancy
    from a real one; the query count was unpinned; a case promised assertions it did not make;
    and a shared substitution helper was used in one module and not its sibling.
  - `[low]` `[patch]` Four further findings: the comparison rule was restated near-verbatim in
    six places against this story's own argument that a rule stated twice holds in one of
    them; the operator documentation said what the pass would not do but not how to run it,
    where to read it, or that its rows accumulate with no retention path; nothing asserted two
    surface readers cannot name the same evidence column; and the story's own Verification
    section miscounted its migrations.

## Design Notes

**Why comparison is equality against the authority, not ordering.** Version ordering across
four ecosystems is a genuinely hard problem -- PEP 440, conda's own ordering, and a recipe's
Jinja-set string do not share a grammar -- and the PRD fixes no rule for it. What AC 1 asks
for is that a package is compared "against the ecosystem that is actually authoritative", and
what `CPM-SM-C1` is about is a package being *called stale against a registry it never
published to*. Equality against the authoritative surface answers both: a surface stating the
same version as the authority is `current`, one stating a different version is `behind`, and
one stating nothing is `unknown`. The Block If exists because a reviewer may reasonably find
that insufficient, and inventing an ordering scheme silently would be worse than halting.

**Why the authority order is a column with a default rather than a constant.** `CPM-AD-6` says
"the authority order is data on the package, defaulting to" a stated order. A constant would
make AC 2 unfalsifiable -- there would be no explicit order to differ from -- and would make
the later non-Python phase a code change. The column holds an empty list for the ordinary
package, which is what "no authority is explicitly set" means, and the default is applied then.

**Why the derived table stores the supporting evidence.** AC 1 says the chosen authority *and
its supporting evidence* are stored with the result. A row that named an authority without
saying which observation it read could not be audited or replayed by a reader, and
`CPM-AD-8`'s replay guarantee is about reproducing output, not about explaining it.

**Why this creates the `policies` application.** The architecture's source tree gives passes
their own application and the capability map puts `CPM-EP-CURRENCY` in `collectors` and
`policies`. `core` holds the machinery and must not grow a domain policy; `collectors` must
not compute a derived status (`CPM-AD-8`). This is the first pass, so it is the story that
creates the home, exactly as `CPM-IDENTITY-S06` was the story that made the collectors
application declare a `ready()`.

## Verification

**Commands:**
- `pixi run test` -- expected: exit 0, the new unit module collected and passing.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: exit 0, no diagnostics.
- `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected".
- `pixi run ci` -- expected: exit 0; coverage >= 90%, `policies/currency.py` at 100%.
- `pixi run gate-postgres` -- expected: exit 0; the new constraints are enforced there.

**Manual checks (if no CLI):**
- `git diff --stat b5ce254` names the new application, the three migrations -- `identity`'s
  authority-order column, `core`'s rollup column and `policies`' own initial -- the settings and
  component adoption, and no collector module. (Corrected from "the two migrations": the Tasks
  list above enumerates three, and this line had counted the new application's own out.)

## Dev Notes

**Satisfies:** `CPM-FR-16`

**Governed by:**

- `CPM-AD-6` — Version authority is explicit per package
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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-CURRENCY-S06]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-6]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-16]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context) — `claude-opus-5[1m]`.

### Debug Log References

After the review round:

- `pixi run ci` — exits 0; 5,629 cases pass, coverage 98.87%, and `policies/currency.py`,
  `policies/models.py`, `policies/outcomes.py`, `policies/apps.py`, `identity/models.py` and
  `core/policy_run.py` each at 100%.
- `pixi run manage makemigrations --check --dry-run` — "No changes detected".
- `pixi run gate-postgres` — the suite passes against `postgres:17`, which is where the three
  constraints on `package_currency` are actually enforced and where the four new refusal cases
  land.
- `pixi run gate-redis` — the suite passed against `redis:7` before the review round; unaffected
  by it (nothing here touches the broker or the cache).

### Completion Notes List

**What was built.** The `policies` application, the first policy pass, and the two columns that
make it possible: `Package.version_authority_order` (`CPM-AD-6`'s per-package data, defaulting to
an empty list) and `PackageHealth.currency_status` (the first domain status column on the rollup).
`CurrencyPass` reads the four snapshot tables at the run's cut-off, picks the authoritative
surface by the applied order, records a verdict per surface plus one overall in
`package_currency`, references the four evidence rows the verdicts rest on, and returns one rollup
column. It makes no outbound call, writes no evidence, never writes the rollup, and never reads
the current time.

**Review round — what the 24 findings changed.** Four were high. The reduction was rewritten
twice over: an inapplicable surface no longer takes a package's verdict away (a non-Python package
current on its other three surfaces read `not_applicable` overall, discarding determinate findings
for a large population), and the ranking that had been written as control flow is now
`CURRENCY_PRECEDENCE`, declared as data in `policies/outcomes.py` with `error` above `behind` and
recorded by name in `test_single_ordering_audit.py`'s new `RECORDED_ORDERINGS` table. The order is
spelled with `OutcomeState` members for its four sentinel ranks specifically so that audit's
detector can see it — an order written only over this module's own constants would have been
invisible to the one check built to enumerate orders, which is the evasion the first version had
made. `execute_policy_run` gained an optional `evidence_cutoff`, so `CPM-FR-22`'s replay is an
operation a caller can express rather than a property a test happened to observe; the replay case
now finishes a *later* collection run between the two, asserts the boundary moved, and replays
against the original cut-off. And the two check constraints that were asserted by name only now
have refusal cases building the row directly, parametrised over all four surface columns so each
conjunct is load-bearing.

Of the mediums: the conda tie-break is a stated key (`channel`, `platform`, ascending) rather than
insertion order, with the `not_found`-from-a-first-sorting-channel cost made executable; a bare `v`
now names no version; `PackageCurrency` gained a `detail` column recording both the stored and the
compared spelling of every discrepancy, which is what makes a false `behind` distinguishable
without re-deriving the comparison; its three authority columns became `editable=False`;
`DETERMINATE_VERDICT_NEEDS_AN_AUTHORITY` is now built by walking `SURFACE_STATUS_FIELDS`, so the
map is read rather than merely declared; the query cost is pinned at three cardinalities; the
`partial` ending and the surviving prior rollup row are asserted rather than promised; and seven
stale prose claims were corrected — three in `core/rollup.py`, four test-module docstrings, one in
`collectors/models.py`, and the scope anchor in `tests/model_registry.py`.

**Three judgement calls worth flagging to review.**

1. *A leading `v` is reconciled before comparison; nothing else is.* The Block If forbids inventing
   a version **ordering** scheme, and none was invented — but exact equality alone would have made
   almost every feedstock read `behind` against its own source, because `CPM-FR-7` records "the
   latest release **or tag**" and a Git tag is conventionally `v1.2.3` while a recipe pins `1.2.3`.
   That is a false staleness claim at inventory scale, which is the one outcome `CPM-SM-C1` names.
   `comparable_version` strips surrounding whitespace and a single leading `v`/`V` when a digit
   follows it, and that is the whole of the normalisation. `1.0` against `1.0.0`, epochs, build
   suffixes and PEP 440 canonicalisation are all deliberately left reading `behind`, documented in
   the module and in `docs/deployment.md`.

2. *A second precedence order exists, and it is declared as data and recorded in the audit.*
   `core.outcomes.aggregate` cannot rank `behind` at all — a per-status determinate value has no
   place in `PRECEDENCE`, and `core/outcomes.py` says the decision belongs to the story that
   introduces one. `CURRENCY_PRECEDENCE` is that decision: `error`, `behind`, `unknown`,
   `not_found`, `current`, worst first, with `not_applicable` deliberately unranked and excluded
   from the reduction. `error` above `behind` so a surface that could not be read never disappears
   behind a finding; `behind` above the two un-observed states so a proven discrepancy is not
   masked by a surface nobody looked at. The consequence, stated in the module and in the operator
   docs, is that a package current on the surfaces somebody observed and unobserved on the rest
   reads `unknown` overall.

3. *The conda surface gets one verdict for a table holding one row per `(channel, platform)`, and
   which pair it is about is a stated key.* Every row of one sweep carries the run's single
   instant, so all of them tie and something has to decide; the key is the channel then the
   platform, both ascending, then the newest row for that pair. Alphabetical is arbitrary and is
   chosen only because it is fixed — the same evidence produces the same verdict on every replay,
   and reordering `CPM_MONITORED_CHANNELS` no longer flips a verdict silently. Two costs are
   documented and one of them is now an executable case: a channel that does not carry the package
   answers `not_found`, and if it sorts first that becomes the package's conda verdict even where a
   later channel publishes the authority's version. A verdict per pair is a larger table than
   `CPM-AD-21`'s `(package, policy_run)` key describes and was not built here.

**`CPM-AD-6`'s fifth default entry is absent, on purpose.** The decision's stated default ends
"→ internal deployed version" and this product observes no such surface: no collector reads a
deployed inventory and no evidence table holds one. A `VersionSurface` member for it would be a
rank over evidence that does not exist — an authority that can never be chosen and can never be
shown to have been skipped — so the vocabulary and the default both stop at four, and
`VersionSurface`'s docstring, `DEFAULT_AUTHORITY_ORDER`'s comment, a unit case and the operator
documentation each record the gap.

**The refusal for a broken authority order is reachable, and its two call sites are named.**
`CPM-CURRENCY-S05`'s review found a boot refusal this product had claimed for an epic and never
made. The rule here is one pure function, `identity.authority_order_fault`, asked by two callers:
a Django field validator (a form, the admin, any `full_clean()`) and `applied_authority_order`,
which the pass calls on every package. The validator's limit is stated where it is declared —
`Model.save()` does not run validators, so it is not the refusal a policy run meets — and nothing
in this product writes the column yet, so the read-side refusal is the one that fires today.

**Audits that were sweeping an empty set and now are not.**
`test_pass_ownership_audit.py` swept an empty pass registry and says so in its own docstring; it
now sweeps a registry holding `CurrencyPass`, and a new case fails if it ever goes back to empty.
`test_derived_status_writability_audit.py` recognised `PackageHealth` as derived state but found
no field its convention matched; a new case asserts there is one. `test_policy_registry.py`'s
stand-in for "a column the rollup does not declare" was literally `currency_status`, which is now
real — it moved to `vulnerability_status`, with a case that fails the day that becomes real too.
`test_policy_contribution.py` and `test_rollup_row.py` each carried a case saying "the real rollup
offers nothing yet"; both now assert the one column it does offer.

**Two pre-existing fragilities this change exposed, and how they were fixed rather than worked
around.** `tests/integration/django_apps/test_run_ledger_migration.py` wrote its fixture package
through a `Package` rendered at `core.0003`'s *ancestors* while `_migrate_to` leaves `identity` at
its leaf — the two agreed only for as long as `identity` had not changed since, and a NOT NULL
column added to `packages` made the insert fail. Its `_historical_apps(target)` helper, which
pinned a migration *state*, was replaced by `_the_applied_state()`, which renders the registry from
`loader.applied_migrations` — what the database actually is rather than a state it was never in.
That also removed the leakage recorded in project memory, where the module's rollback window was
failing six unrelated integration cases.
`tests/unit/django_apps/test_policy_registry.py`'s `monkeypatch` of the rollup model outlived its
case's fixture teardown once the teardown had to re-register a real pass; the substitution is now
`tests/passes.py`'s `substituted_rollup()`, an explicit `with` block that ends where a reader can
see it end, shared with the ownership audit so the two cannot drift into two substitutions with
different lifetimes.

**Risks and what is left.** Three are recorded as `deferred:` entries in this story's frontmatter
— nothing writes the authority order and a hand-written `UPDATE` leaves no audit row; the pass
issues four evidence queries per package with no batching; and `core` now imports `policies` at
module scope, which the leaf module dodges as a *cycle* without addressing as a *direction*. The
rest:

- The false-`behind` class is real and will be visible in the first report over a real inventory.
  `PackageCurrency.detail` now records both spellings of every discrepancy, so a reader can tell a
  real one from a spelling one without re-deriving the comparison — but closing it properly needs a
  version-ordering rule the PRD does not fix, which is a spec change's to decide.
- A conda `not_found` from a first-sorting channel becomes the package's conda verdict even where a
  later channel publishes the authority's version. Documented, and an executable case; the fix is a
  verdict per `(channel, platform)`, which is a larger table than `CPM-AD-21`'s key describes.
- `PackageCurrency` accumulates one row per package per run with `PROTECT` on every relation and no
  retention path. Recorded in `docs/deployment.md` under its own heading; nobody has taken the
  decision to prune, and doing so would have to delete these rows before the `policy_runs` rows
  they protect.
- `PackageCurrency` carries no index beyond the `(package, policy_run)` unique constraint and
  Django's own foreign-key indexes. The per-package read is served by the constraint's index; the
  "which packages are behind" question is the rollup column's, not this table's.
- Nothing schedules `cpm.policy.run`. The pass is adopted and correct; choosing a cadence is not
  this component's decision, and `docs/deployment.md` now says how to enqueue one by hand.

### File List

**New — the `policies` application**

- `src/django_apps/conda_package_supply_chain_monitor/policies/__init__.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/apps.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/outcomes.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/models.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/currency.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/migrations/__init__.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/migrations/0001_package_currency.py`
  — regenerated once after review rather than amended by a second migration: `detail` and the three
  `editable=False` authority columns arrived before this had been applied anywhere, so they belong
  in the `CreateModel`.

**Modified — the two columns, the orchestration, and the adoption**

- `src/django_apps/conda_package_supply_chain_monitor/identity/models.py` — `VersionSurface`,
  `DEFAULT_AUTHORITY_ORDER`, `AuthorityOrderError`, `authority_order_fault`,
  `validate_authority_order`, `applied_authority_order`, and `Package.version_authority_order`.
- `src/django_apps/conda_package_supply_chain_monitor/identity/migrations/0004_version_authority_order.py` *(new)*
- `src/django_apps/conda_package_supply_chain_monitor/core/models.py` —
  `PackageHealth.currency_status`, and the docstring that claimed the table had no domain status
  column.
- `src/django_apps/conda_package_supply_chain_monitor/core/migrations/0006_package_health_currency_status.py` *(new)*
- `src/django_apps/conda_package_supply_chain_monitor/core/policy_run.py` — `execute_policy_run`
  takes an optional `evidence_cutoff`, additive and defaulted, which is what makes `CPM-FR-22`'s
  replay an operation a caller can express.
- `src/django_apps/conda_package_supply_chain_monitor/core/rollup.py` — three prose claims that had
  become their own opposite once the rollup declared a contributable column.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` — one sentence,
  narrowing `snapshot_as_of`'s "the only supported way" to the table it is about. Prose only: no
  collector, no evidence table and nothing any of them records is changed, which is what this
  story's Never list forbids.
- `src/config/settings/base.py` — `policies` appended to `LOCAL_APPS`.
- `component.toml` — `policies` appended to `adopted_apps`.
- `docs/deployment.md` — the operator section: what the pass compares, the verdict table, the
  equality limit, the authority order and its default, the gate, and the one conda verdict.

**New — tests**

- `tests/unit/django_apps/test_currency_policy.py`
- `tests/unit/django_apps/test_policies_app.py`
- `tests/integration/django_apps/test_currency_policy.py`

**Modified — tests and fixtures the new application and columns reach**

- `tests/passes.py` — `ADOPTED_PASS_NAMES`, `ADOPTED_PASSES`,
  `registry_without_adopted_passes()`, `substituted_rollup()`; `AN_UNDECLARED_COLUMN` moved off
  `currency_status`.
- `tests/unit/django_apps/test_pass_ownership_audit.py` — sweeps the live registry; new
  anti-vacuity case; uses the shared `substituted_rollup()` rather than a bare `monkeypatch`.
- `tests/unit/django_apps/test_single_ordering_audit.py` — `RECORDED_ORDERINGS`, the one recorded
  exemption and its reconciliation in both directions; `_recorded_key` and the narrowed subject
  list.
- `tests/model_registry.py` — `policies` added to the scope anchor, with the narration extended to
  say why that application in particular is worth naming.
- `tests/unit/django_apps/test_policy_registry.py` — withdrawal fixture; explicit rollup
  substitution; new case holding the stand-in column to one the rollup does not offer.
- `tests/unit/django_apps/test_policy_contribution.py`, `tests/unit/django_apps/test_rollup_row.py`
  — the "offers nothing yet" cases now assert the one column offered.
- `tests/unit/django_apps/test_derived_status_writability_audit.py` — five recorded write
  exemptions for `policies/currency.py`; new case asserting the rollup carries a field the rule is
  about.
- `tests/unit/django_apps/test_identity_models.py`, `tests/unit/django_apps/test_identity_app.py`
  — the package field roster and the migration list.
- `tests/unit/test_component_declaration.py` — the adopted-app roster.
- `tests/integration/django_apps/test_rollup.py` — the per-domain version map now carries two
  domains; the gate is asserted on a real column.
- `tests/integration/django_apps/test_run_ledger_migration.py` — the `_historical_apps(target)`
  helper, which pinned a migration *state*, was removed; `_the_applied_state()` renders the
  registry from what is actually applied rather than from `core.0003`'s ancestors.

## Auto Run Result

Status: done
Blocking condition: none

**What was implemented.** `CPM-FR-16`'s version currency policy — the first real policy pass in
the product, and the `policies` application the architecture's source tree has been reserving
for it. `CurrencyPass` reads the four snapshot tables at the run's stated cut-off, records a
verdict per surface and one overall, names the authority it judged against and the evidence
rows the verdict rests on, and contributes the rollup's first domain status column. It reads
evidence and writes none; it never writes the rollup.

**The authority is data on the package, with a documented default.** `CPM-AD-6` says the order
is data defaulting to a stated sequence; the column holds an empty list for the ordinary
package, which is what "no authority is explicitly set" means, and the default applies then. A
malformed order is refused rather than silently defaulted, so a package with a bad order fails
its own evaluation and no other.

**Comparison is equality against the authority, and the story says why.** Version ordering
across four ecosystems has no rule the PRD fixes, and inventing one silently would have been
worse than the alternative. A leading tag prefix is reconciled first — the source collector
records "the latest release **or tag**", and tags are conventionally prefixed while recipes are
not, so exact equality alone would have called almost every feedstock stale against its own
source. Everything else compares exactly, and the row now records both spellings so a reader
can tell a false discrepancy from a real one.

**Files changed.**

- `policies/` *(new application)* — the pass, its vocabulary, its derived table, its migration
  and its `AppConfig`, adopted last in both the settings and the component declaration.
- `identity/models.py` + migration — the per-package authority order.
- `core/models.py` + migration — the rollup's first domain status column.
- `core/policy_run.py` — an explicit cut-off, additive and defaulted, so a replay is an
  operation rather than a hope.
- `core/rollup.py` — three claims corrected that this story made false.
- `docs/deployment.md` — how to run the pass, how to replay one, where to read the result, and
  what the comparison does and does not prove.
- New unit and integration modules, and the audits that had been sweeping an empty set and now
  have something to sweep.

**Review findings.** 24 patched (4 high, 16 medium, 4 low), 3 deferred, 2 rejected. Four review
layers ran in parallel over the 5,200-line diff.

**Follow-up review recommended:** true. Four high-severity patches. Patched counts: high 4,
medium 16, low 4; score `3 x 16 + 1 x 4 = 52`, far over the threshold of 5.

**The two most valuable findings were both about the headline verdict being wrong.** A single
inapplicable surface took the whole package's verdict away, which would have reported "no
currency question applies here" for every non-Python package while three surfaces had answered.
And the verdict ranking had been written as control flow specifically so the single-ordering
audit would not see it — which ranked a proven discrepancy above a surface that could not be
read at all, and made the audit evadable by anyone willing to spell an order as a branch. The
order is now data the audit is taught about by name.

**The third was a guarantee the product did not offer.** The architecture requires that
re-running a version at a cut-off reproduces identical output, and the orchestration took no
cut-off — so the boundary moved whenever a collection finished in between, while the operator
documentation told readers they could replay a run and diff it.

**Verification.** `pixi run ci` exits 0 — 5629 passed, 2 pre-existing skips, coverage 98.87%,
with every new module at 100%. `makemigrations --check --dry-run` reports "No changes
detected". `pixi run gate-postgres` passes against `postgres:17`, where the three new
constraints are enforced. All three were re-run by the orchestrating session after the patch
round.

**Residual risks.** Three `deferred` entries, all medium. Nothing in the product writes the
authority order, so every package is judged on the default and a change to it would leave no
audit record — the write path is an application concern no story yet claims. A run issues four
evidence reads per package with no batching, now pinned by a query-count case so a regression
is visible but not yet optimised. And the machinery application now imports the domain
application at module scope to declare the rollup column's choices, which is a dependency
direction that will repeat once per policy epic and that no audit would notice.
