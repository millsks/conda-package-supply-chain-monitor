---
title: 'CPM-SECURITY-S06: Whether a finding can actually be acted on'
type: 'feature'
created: '2026-09-07'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: true
baseline_revision: '8727008ae1d847f06fb01315c5313731554dd0d2'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s05-licence-policy-as-versioned-data.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s04-vulnerability-kev-rollup.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s01-vulnerability-evidence-ranges-match-confidence.md
warnings:
  - oversized
deferred:
  - summary: >-
      `blocked` is unreachable: no evidence this product records can establish that a surface
      does not carry a version, so no row the readiness pass writes reaches the epic's AC 2
      verdict. Closing it needs a version-ordering rule, which no architecture decision owns.
    evidence: |-
      `blocked` is reached only from four `not_published` readings, and `not_published`
      requires a surface to have *established* that the fix is not there. The four surface
      tables store the version each surface states as its **latest** -- `collectors/models.py`
      documents the conda column as "the version the channel itself states as latest" -- not
      the set of versions it carries, so `latest != fix` establishes nothing in either
      direction: PyPI still hosts 1.5 when its latest is 2.0. An earlier build recorded the
      negation as `not_published`, which made `blocked` the steady state rather than an edge --
      advisories name a fix, surfaces move past it, and every package with an older advisory
      decayed into the verdict that tells a security reviewer to stop looking.
      `surface_availability` now reads a non-equal statement as `not_read` and
      `EQUALITY_ONLY_DETAIL` names every version each surface stated. The verdict, its rank in
      `READINESS_PRECEDENCE` and both check constraints stay, so the day an ordering rule
      lands nothing about the schema or the queries changes. The rule itself is not
      `CPM-AD-6`'s -- that is *version authority is explicit per package*, which owns which
      surface is authoritative, not how two version strings compare -- and nothing in the
      spine owns it.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/policies/remediation.py -- surface_availability
    severity: high
  - summary: >-
      The advisory collector cannot record "the source stated there is no fix" distinctly from
      "the field was absent", so a matched advisory with no fixed range is `unknown` where the
      matrix asks for the two to be told apart.
    evidence: |-
      `collectors/vulnerability.py` builds one clause per field the source left **blank** --
      `absences = [reason for stated, reason in ((fixed_range, NO_FIXED_RANGE_DETAIL), ...) if
      not stated]` -- and `collectors/models.py` and PRD line 802 are explicit that blank means
      *missing* and is never inferred. So `NO_FIXED_RANGE_DETAIL` is present on precisely the
      rows whose `fixed_range` is empty and refines nothing. An earlier build read it as "the
      source was asked and answered", reaching `blocked` with four unread surfaces; that made
      `UNRECORDED` unreachable from any row a real collector writes and turned every feed that
      omits a fixed range into an abandoned package. Recording the distinction means a
      collector change -- a field, or a document contract that says the source stated none --
      which is `CPM-SECURITY-S01`'s territory rather than a policy pass's. Until then both
      rows are `unknown` and `NO_FIX_RECORDED_DETAIL` says why on the row.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/vulnerability.py -- NO_FIXED_RANGE_DETAIL
    severity: high
  - summary: >-
      `CPM-AD-21` ("a pass may read an earlier pass's derived output, and must -- it never
      re-derives a status another pass owns") and this story's categorical ban on reading
      derived tables are in genuine tension, and this pass breaches the second half of the
      former.
    evidence: |-
      The Always list bans reading `PackageCurrency`, `PackageFeedstockPresence`,
      `PackageVulnerability` and `PackageLicense`, justified by `CPM-FR-22`: a readiness
      derived from two policy versions could have replay stated for neither. Following that
      ban means re-deriving "no advisory matched this package" here rather than reading
      `package_vulnerability`, which is exactly what `CPM-AD-21`'s second half forbids -- and
      is exactly where the `not_applicable`/`unknown` divergence found in review arrived. The
      re-derivation is now drawn with the same imported constant and the same prefix test the
      owning pass uses, and an integration case asserts the two agree about one sweep, but the
      structural tension is unresolved. Which of the two rules outranks the other is an
      architecture question rather than a story's.
    location: >-
      _bmad-output/planning-artifacts/architecture -- CPM-AD-21 versus CPM-FR-22
    severity: medium
  - summary: >-
      `freshness_target` returns the first registered collector whose `evidence_model` matches;
      a second collector declared for one evidence table would silently win rather than be
      refused.
    evidence: |-
      `for collector in registered_collectors(): if collector.evidence_model is evidence_model:
      return collector.freshness_target`. `CPM-AD-7` gives every collector its own evidence
      table and nothing in this product declares a second for any of the five, so the shape is
      not reachable today -- but the refusal that would hold it belongs with
      `core/registry.py`, where every pass would get it, rather than being one pass's private
      opinion about a registry they all read.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/policies/remediation.py -- freshness_target
    severity: low
---

# CPM-SECURITY-S06: Whether a finding can actually be acted on

Epic: `CPM-EP-SECURITY` — Vulnerability, KEV and licence exposure

<intent-contract>

## Story

As a security reviewer,
I want to know if a fix exists and where,
so that I can separate work I can do now from work that is waiting on someone else.

## Acceptance Criteria

1. **Given** a package with an open finding
   **When** the readiness policy runs
   **Then** it derives readiness from whether a fixed version exists and where it is
   available — upstream, PyPI, recipe or a monitored channel

2. **Given** a finding whose fix exists nowhere yet
   **When** readiness is computed
   **Then** it is `blocked`, distinct from `ready` and from `unknown`

3. **Given** the supporting evidence is past its freshness target
   **When** readiness is computed
   **Then** it reports stale rather than asserting a fix is available

## Intent

**Problem:** The epic now records vulnerabilities, exploited status and licences, and reduces
the first two. None of it tells a reviewer what they can actually do this morning. `CPM-FR-41`
realises `CPM-UJ-1`: separate the work that is available from the work that is waiting on
somebody else. The distinction is entirely about *where a fixed version has appeared*, and the
four surfaces appear at different times — upstream cuts a release, PyPI gets a wheel, the
recipe is updated, the channel publishes a build. A reviewer can act at the recipe stage and
cannot act before upstream has released at all.

**Approach:** A fifth policy pass writing its own per-domain derived table keyed
`(package, policy_run)`. It reads the vulnerability evidence for the fixed version and the
four currency-surface evidence tables for where that version has appeared, and derives a
readiness state plus the surfaces the fix was found on. `blocked` means the fix was looked for
on every surface and found on none. A surface that was not read is not a surface where the fix
is absent.

## Boundaries & Constraints

**Always:**
- The pass writes **only** its own per-domain table, keyed `(package, policy_run)`
  (`CPM-AD-21`). It does not write the health rollup.
- It reads **evidence tables**, never another pass's derived table. All four shipped passes
  import only their own model, and that is the precedent: a readiness verdict derived from
  another pass's verdict would depend on that pass's version as well as its own, and
  `CPM-FR-22` replay could not then be stated for either.
- `ready`, `blocked` and `unknown` are three distinct values and none is a default.
  **`blocked` is an established absence** — the fix was looked for on every surface and found
  on none — and it must never be produced by a surface that was not read.
- **A surface that was not read never counts as a surface where the fix is absent.** This is
  the defect `CPM-SECURITY-S05`'s review found: an absent channel voted against channels that
  had spoken, and the determinate verdict collapsed. Here the same shape would report `blocked`
  for a package whose fix is sitting on a surface nobody checked.
- Where the fix was found is recorded per surface, not collapsed into one flag. AC 1 asks
  *where*, and a reviewer's next action differs by surface.
- Evidence past its freshness target reports **stale** rather than asserting availability
  (`CPM-FR-38`, AC 3). Staleness is read from the freshness machinery in `core`, not
  re-derived here.
- Every row records the policy version and the run's cut-off. Evidence is read as of the
  cut-off, never from a collection run still `running`.
- Time comes from the injected clock; `pixi` is the only runner; `pixi run ci` exits 0.

**Block If:**
- Deriving readiness needs a fixed version that `CPM-SECURITY-S01` did not record in a form
  this pass can compare. If the fixed-version data is present but not comparable without
  inventing version-ordering semantics this product has not decided, do **not** invent them:
  record the finding as `unknown` with the reason, ship the rest, and record the gap. **No
  architecture decision owns version ordering.** An earlier revision of this clause said it
  was `CPM-AD-6`'s territory; `CPM-AD-6` is *version authority is explicit per package*,
  which owns which surface is authoritative and not how two version strings compare. The
  correction and its propagation into the implementation are in the Spec Change Log.

**Never:**
- No refusal that fails the package when a policy parameter or a version entry is missing.
  All passes for one package share a transaction, so a refusal rolls back the other four
  domains' rows and breaks replay for runs recorded before this pass existed. Derive the
  honest state and record the reason. This defect was stated as fact in four documents in
  `CPM-SECURITY-S04` and was false in all of them.
- No write to the health rollup and no new column on it.
- No reading of `PackageCurrency`, `PackageFeedstockPresence`, `PackageVulnerability` or
  `PackageLicense`.
- No re-derivation of a vulnerability status, a currency verdict or a licence outcome. This
  pass answers one question and takes the others as given.
- No priority bucket, score, rank or work type (`CPM-FR-20`, Open Question 8,
  `CPM-EP-PRIORITY`).
- No change to `core/`, to any collector, or to the four shipped policy passes.
- No `timezone.now()` anywhere.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fix published to a monitored channel (AC 1) | an open finding with a fixed version, and a channel snapshot carrying it | `ready`, recording the channel as the surface | The reviewer can act now |
| Fix upstream only | upstream released the fixed version; PyPI, recipe and channel have not | a state distinguishing "released but not yet packaged" from `ready`, recording upstream as the only surface | Not `ready`: nothing to install |
| Fix in the recipe, not yet built | the feedstock carries the fixed version, no channel build | recorded as the recipe surface, distinct from `ready` | The reviewer's next action differs |
| Fix exists nowhere yet (AC 2) | every one of the four surfaces was read, none carries the fixed version | `blocked` | An established absence. **Not reachable as implemented** — see the Spec Change Log: a surface stores its *latest* version, not the set it carries, so "latest is not the fix" establishes nothing. Such a row is `unknown` with the versions named. |
| One surface was never read | three surfaces read, the fourth has no evidence as of the cut-off | **not** `blocked`; the row says which surface is unknown | The `CPM-SECURITY-S05` lesson |
| No surface was read | no currency evidence at all as of the cut-off | `unknown` | Never `blocked`, never `ready` |
| Supporting evidence is stale (AC 3) | the surface carrying the fix is past its freshness target | stale, not `ready` | Never asserts a fix is available |
| Some surfaces fresh, one stale | the fix is on a fresh surface and also on a stale one | `ready` on the fresh surface's evidence, and the row says the stale one was not relied on | Freshness is per surface |
| No open finding | the package has no matched vulnerability as of the cut-off | a state saying there is nothing to be ready for, distinct from `ready` and from `blocked` | Not an absence of a fix |
| An open finding with no fixed version recorded | the advisory names no fix | `unknown` | **The two cannot be told apart from the evidence** — the advisory collector writes its "the source states no fixed range" clause for every *blank* field, so there is no row that says the source was asked and answered. See the Spec Change Log. |
| The advisory's fixed version is not comparable | the recorded value cannot be ordered without new semantics | `unknown` naming the reason; the run does not fail | The Block If |
| The advisory evidence is itself past its freshness target (`CPM-UJ-1`) | the newest advisory sweep at the cut-off is older than `VULNERABILITY_FRESHNESS_TARGET` | `unknown`, `evidence_stale` true, no surface asked | Stale rather than actionable |
| Several open findings | two findings, one fixed everywhere and one nowhere | one row per package, taking the least ready | A package is only as actionable as its worst finding |
| Only an `error` or `not_found` row on a surface | the collector failed, or the surface does not carry the package | that surface is unknown, not absent | Same rule as the missing surface |
| Evidence newer than the cut-off | a row observed after the cut-off | ignored | Replay reproduces it |
| Re-run at the same cut-off and version | the pass runs twice | identical values | |
| Re-run at a different version | the parameters change, the evidence does not | different values, each recording its version | `CPM-FR-22` |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/policies/licence.py` -- the newest
  sibling and the one whose Review Triage Log matters most here. Read it and this story's
  predecessor's Auto Run Result **first**: the absent-channel defect it records is the same
  shape as this story's four-surface reduction, and `contributing_findings` /
  `referenced_findings` is the pattern for "a source that said nothing does not vote, but the
  row can still say which nothing it met".
- `policies/vulnerability.py` -- the other multi-source pass, and the one that carries the
  replay lesson about refusing per package.
- `policies/currency.py`, `policies/feedstock.py` -- the two older passes and the surface
  vocabulary. Read how currency expresses per-surface results without collapsing them.
- `policies/models.py` -- four derived tables are the shape. Add `PackageRemediation` /
  `package_remediation`: `package` FK, `policy_run` FK, `readiness`, the per-surface findings,
  `policy_version`, `evidence_cutoff`, FKs to the `VulnerabilityFinding` and the surface
  snapshot that supported the verdict, and a `detail`. Constraints mirroring the siblings: a
  determinate readiness names the evidence behind it, and `ready` additionally names the
  surface the fix was found on -- so a `ready` row naming no surface is refused by the
  database.
- `policies/outcomes.py` -- four vocabularies with their precedence orders live here. Add the
  readiness vocabulary and a small per-surface vocabulary. The surface vocabulary needs the
  same three-way distinction `CPM-SECURITY-S04`'s KEV membership needed: the fix is here, the
  fix is not here, and **this surface was not read**. Collapsing the third into the second is
  what produces a false `blocked`.
- `policies/parameters.py`, `policies/data/policy-parameters.toml`, `policies/data/README.md`
  -- how a version is read and how an absent entry is handled without refusing.
- `policies/apps.py`, `policies/migrations/` (`0004` is the newest, add `0005`) -- the pass's
  position in the run's declared ordered list.
- `collectors/models.py` -- the five evidence tables read here: `VulnerabilityFinding` for the
  fixed version, and `SourceReleaseSnapshot`, `PyPIReleaseSnapshot`, `FeedstockSnapshot` and
  `CondaPackageSnapshot` for the four surfaces.
- `core/freshness.py` -- `freshness_of`, `is_stale`, `latest_observation` and
  `FreshnessReport`. AC 3 is answered from here, not re-derived.
- `tests/unit/django_apps/test_licence_policy.py` and its integration counterpart -- the module
  shapes and the mutation-test style the last two reviews forced.
- `docs/deployment.md` -- the policy sections, and what each readiness state tells an operator
  to do next.

## Tasks & Acceptance

**Execution:**
- `policies/outcomes.py` -- the readiness vocabulary and the three-valued per-surface
  vocabulary, with their precedence declared here.
- `policies/models.py` + `policies/migrations/0005_package_remediation.py`.
- `policies/parameters.py` + `policies/data/policy-parameters.toml`, if the story needs a
  parameter at all. If it does not, say so rather than inventing one.
- `policies/remediation.py` -- new. The pass.
- `policies/apps.py` -- registration and position in the ordered list.
- `tests/unit/django_apps/test_remediation_policy.py`,
  `tests/integration/django_apps/test_remediation_policy.py` -- every matrix row.
- Every roster and audit test carrying a policy-pass or model count.
- `docs/deployment.md`.

**Acceptance Criteria:**
- Given an open finding whose fixed version is published to a monitored channel, when the pass
  runs, then the row is `ready` and names that surface.
- Given an open finding whose fixed version is on no surface, all four having been read, when
  the pass runs, then the row is `blocked`.
- Given the same package with one surface unread, when the pass runs, then the row is **not**
  `blocked`, and it says which surface is unknown.
- Given a fix present only on evidence past its freshness target, when the pass runs, then the
  row reports stale and does not assert the fix is available.
- Given a `ready` row, when it is written with no surface named, then the database refuses it.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

### 2026-09-07 — Recorded before implementation

**Why this pass reads evidence and not the other passes' tables.** `CPM-FR-41`'s inputs -- a
fixed version, and where that version has appeared -- are exactly what the vulnerability
collector and the four currency collectors record. Reading `PackageCurrency` instead would make
a readiness verdict depend on two policy versions at once, and `CPM-FR-22` replay could then be
stated for neither. All four shipped passes import only their own model; this one does the same.

**Where the epic's third acceptance criterion actually lives.** AC 3 says readiness reports
stale rather than asserting a fix is available. `core/freshness.py` already answers "is this
observation past its target", and `CPM-FR-38` owns the concept. This story consumes that
answer; it does not restate the rule or add a second freshness notion.

### 2026-09-07 — Recorded after review

**The spec was wrong about `CPM-AD-6`, and the implementation faithfully repeated it.** The
Block If above said "version ordering is `CPM-AD-6`'s territory and belongs to whichever story
decides it". `CPM-AD-6` is *version authority is explicit per package*: it owns **which surface
is authoritative** for a package's version, not **how two version strings compare**. Nothing in
the spine owns version-ordering semantics. The implementation cited `CPM-AD-6` in eight places,
two of which were stored `detail` text a reviewer reads on the row — so a reviewer following the
citation would have arrived at a decision that does not answer the question they had. Every
citation now says plainly that no architecture decision owns version ordering yet. The error
originated here, in this spec, and is recorded here first.

**`blocked` is unreachable as implemented, and the story ships saying so.** This is the Block If
firing on a second, larger front than the one it anticipated, and its instruction — record the
honest state with the reason, ship the rest, record the gap — is what was followed.

`blocked` means the fixed version was looked for on every surface and found on none. The only
reading permitted to vote towards it is `not_published`, which requires a surface to have
*established* that the fix is not there. The four surface tables store the version each surface
states as its **latest** (`collectors/models.py` documents the conda column as "the version the
channel itself states as latest"), not the set of versions it carries. So `latest != fix`
establishes nothing in either direction — PyPI still hosts `1.5` when its latest is `2.0` — and
recording it as `not_published` made `blocked` the *steady state* rather than an edge: advisories
name a fix, surfaces move past it, and every package with an older advisory decayed into the one
verdict that tells a security reviewer to stop looking. A surface stating any non-equal version
now reads `not_read`, with `EQUALITY_ONLY_DETAIL` naming every version it stated.

The second route to `blocked` was an advisory that "established there is no fix", selected by the
presence of the advisory collector's `NO_FIXED_RANGE_DETAIL` clause. That clause does not carry
the distinction: `collectors/vulnerability.py` builds one clause per field the source left
**blank**, and `collectors/models.py` and PRD line 802 are explicit that blank means *missing*
and is never inferred. So the clause is present on precisely the rows whose `fixed_range` is
empty, refines nothing, and reading it as an answer made `unknown` unreachable from any row a
real collector writes while sending every feed that omits a fixed range to `blocked` with four
unread surfaces. A matched advisory with no fixed range is `unknown`.

With both routes closed, no row this product writes reaches `blocked`. The value stays in the
vocabulary (the epic's AC 2 requires it to exist and be distinct), `READINESS_PRECEDENCE` still
ranks it worst, and both check constraints still guard it — including the `Q(fixed_version="")`
escape that was removed with the second route, since the hole in the schema had been cut to
exactly the size of the defect above it. Two integration cases assert the unreachability
directly rather than leaving it to be inferred from green cases. The two changes that would
restore it are on the deferred list.

**The asymmetry between the two collector-prose seams, and why one was kept.** This pass depended
on two sentences the advisory collector writes. One (`NO_FIXED_RANGE_DETAIL`) was read as
carrying a distinction it does not carry, and is gone. The other
(`NOTHING_MATCHED_DETAIL`) was *not* consulted, and had to be: the pass treated only `error` and
`not_found` as "established nothing", while the collector writes "established nothing" as
`unknown` — `UNIDENTIFIED_DETAIL` and `NO_VERSION_DETAIL` both produce it. So a package the
advisory source could not identify read `not_applicable` here ("there is nothing to be ready
for") while `package_vulnerability` read `unknown` for the same package, the same run and the
same rows: the clean-looking degradation `CPM-NFR-3` forbids, arrived at through the most common
sentinel. The seam now uses the same imported constant and the same prefix test
`policies/vulnerability.py` already applies to the same rows, so the two passes cannot disagree
about one sweep.

**`CPM-AD-21` and this story's Always list are in tension, and the tension is recorded rather
than resolved.** `CPM-AD-21` says a pass "may read the derived output of a pass declared earlier
in the same run, and must — it never re-derives a status another pass owns." This story's Always
list states a categorical ban on reading derived tables, justified by `CPM-FR-22`: a readiness
derived from `PackageCurrency` would depend on two policy versions at once and replay could be
stated for neither. Both cannot be followed literally at once, and the pass as shipped follows
the ban — and therefore does breach the second half of `CPM-AD-21`, by re-deriving "no advisory
matched this package" its own way rather than reading `package_vulnerability`. That re-derivation
is exactly where the defect above arrived. It is mitigated by drawing the line with the same
imported constant and the same test the owning pass uses, and by an integration case that
asserts the two passes agree about one sweep. Resolving the tension properly — whether
`CPM-FR-22`'s replay argument actually outranks `CPM-AD-21`'s must — belongs with the
architecture rather than with a story, and is on the deferred list.

**`CPM-UJ-1`'s advisory-freshness edge case had no implementation.** "If the vulnerability
evidence is older than its freshness target, the finding shows as stale rather than actionable."
`VULNERABILITY_FRESHNESS_TARGET` was declared by the advisory collector and never consulted:
freshness was measured over the four surfaces alone, so a month-old advisory sweep beside a
channel refreshed this morning produced `ready` with `evidence_stale` false. The advisory
sweep's own age is now measured on the same terms, folded into `evidence_stale`, and where it is
stale the readiness is `unknown` with no surface asked at all — what a stale sweep offers is a
fixed version that may no longer be the one to look for.

## Design Notes

**Why `blocked` needs the same care `allowed` needed in `CPM-SECURITY-S05`.** The two are
mirror images. `allowed` was the value that must never be reached by an absence, because it
looks like good news. `blocked` is the value that must never be reached by an absence for the
opposite reason: it tells a reviewer to stop looking. A false `allowed` ships a forbidden
licence; a false `blocked` abandons a package whose fix is sitting on a surface nobody checked.
Both are absences masquerading as conclusions, and both are prevented the same way -- by making
"not read" a value the vocabulary can hold rather than a silence the reduction has to guess at.

**Why the surfaces stay separate on the row.** AC 1 asks *where*, and the reviewer's next
action differs by surface: upstream released means wait for packaging, the recipe carries it
means a build is due, the channel has it means install it now. Collapsing four surfaces into
one boolean answers a question nobody asked.

## Verification

**Commands:**
- `pixi run test`, `pixi run format && pixi run lint && pixi run typecheck`,
  `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected".
- `pixi run ci` -- expected: exit 0; coverage >= 90%, new modules at 100%.
- `pixi run gate-postgres` -- expected: the suite passes against `postgres:17`. This story adds
  a constraint, and SQLite cannot prove it. Note the task can exit 3 on a local
  coverage-combine artifact after every test passes; confirm `N passed, 0 failed` first.

## Dev Notes

**Satisfies:** `CPM-FR-41`

**Governed by:**

- `CPM-AD-5` — One status type, fixed values, one precedence order
- `CPM-AD-8` — Policy is a separate versioned pass, not a collector's business

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.
- Time comes from the injected clock in `core` (`CPM-AD-26`).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-SECURITY-S06]
- [Source: ARCHITECTURE-SPINE.md#CPM-AD-5]
- [Source: ARCHITECTURE-SPINE.md#CPM-AD-8]
- [Source: prd.md#CPM-FR-41]
- [Source: prd.md#CPM-FR-38]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context) — `claude-opus-5[1m]`.

### Debug Log References

- `pixi run makemigrations policies` generated `0005_packageremediation.py`; renamed to
  `0005_package_remediation.py` and hand-edited to depend on what it references
  (`collectors.0007_vulnerability_findings`, `core.0002_run_ledger`,
  `identity.0001_package_identity`, `policies.0004_package_license`) rather than on each
  app's newest migration, exactly as `0002`–`0004` record.
- Three integration failures during development, each a fixture fault rather than a
  behaviour one: a staleness case measured a feedstock sweep against the
  *published-package* collector's two-day target instead of the feedstock collector's
  fourteen-day one; a unique-constraint case matched on a message PostgreSQL and SQLite
  spell differently; and a case tried to corrupt an advisory row with `update()`, which
  `AppendOnlyModel` refuses outright (`CPM-AD-2`).
- Two `tests/integration/django_apps/test_rollup.py` cases enumerate every domain in
  `PackageHealth.policy_versions` and gained a `remediation` entry.

### Completion Notes List

**The property the story turns on, held in four places — and the state it leaves `blocked`
in.** `blocked` is reached from four `not_published` readings and from nowhere else. It is
held in the vocabulary (`FixAvailability` carries three values, the third being
`not_read`), in the pass (`finding_readiness`), in the reduction (`READINESS_PRECEDENCE`
ranks `blocked` worst), and in the database (`blocked_needs_every_surface_read` plus
`decided_surface_names_its_observation`, which together refuse a `blocked` row whose
surfaces did not all vote from an observation the row names).

**No row this pass writes reaches `blocked`**, because no evidence this product records can
establish that a surface does not carry a version. The Spec Change Log argues it at length;
two integration cases and one unit case assert it directly. The value, the ranking and both
constraints stay, and the two changes that would restore reachability are on the deferred
list.

**On the reduction, corrected.** `worst_readiness` is `min` over `READINESS_PRECEDENCE` and
`blocked` is rank 0, so **any one** blocked finding blocks the package. That is the intended
arithmetic — a package with one unfixable finding is not one a reviewer can finish — but an
earlier revision of this note and of `worst_readiness`'s own docstring claimed the inverse:
that the reduction "can never reach `blocked` unless every verdict is `blocked`". A false
safety claim in the two places a reviewer checks is worse than no claim, and both are
corrected. Where the property is actually held is one level down: a finding whose surfaces
were not all read never reaches `blocked` in the first place, so there is no such verdict for
the reduction to propagate.

**Five evidence tables, no derived table.** `VulnerabilityFinding` for the fixed version and
the four currency-surface snapshots for where it has appeared. Nothing imports
`PackageCurrency`, `PackageFeedstockPresence`, `PackageVulnerability` or `PackageLicense`,
and a unit case asserts the absence of those imports directly.

**No refusal that fails the package, bar one.** Only an advisory finding carrying a state
outside `VulnerabilityOutcome` raises. An uncomparable fixed range, a finding with no fix, an
unread surface, a stale surface and a collector declaring no freshness target are all
recorded on the row. An integration case drives the one refusal and asserts that the
package loses all five domains' rows and its rollup row while every other package's commit —
which is the price that keeps the list from growing.

**AC 3 is consumed, not restated.** `surface_is_stale` calls `core/freshness.py`'s
`freshness_of` and reads the verdict; the target comes from the registered collector that
writes that evidence table (`CPM-AD-7` makes the table the collector, so no collector name is
spelled here). `latest_observation` is deliberately unused: it is not cut-off-bound, and a
staleness verdict measured off a row the cut-off excludes would not replay.

**The Block If was taken, twice.** A `fixed_range` carrying any `ORDERING_MARKERS` character
states a *set* of versions and cannot be compared without version-ordering semantics. That
finding reads `unknown`, the row names the expression, and the run succeeds — asserted end to
end. The second, larger taking is `blocked` itself: the same missing ordering rule is what
makes an established absence unrecordable, so the honest state is recorded with the reason and
the gap is on the deferred list. Neither row cites `CPM-AD-6` any more; see the Spec Change
Log for why the citation was wrong.

**`-` is deliberately not an ordering marker.** It is how ordinary prerelease versions are
spelled (`1.0.0-alpha`, `1.2.3-rc1`), so adding it would make every one of them uncomparable.
`"1.0-2.0"` is therefore read as a bare version; a unit case states the residual, and the
parametrised id that claimed to cover it (it passed on the space in `"1.0 - 2.0"`) is renamed
to what actually catches it.

**No policy parameter, and it is said rather than invented.** The comparison is
`policies/currency.py`'s (imported, never re-spelled), the freshness targets are the
collectors' declarations, and the vocabulary is fixed by `CPM-AD-5`. `parameters.py` and
`policy-parameters.toml` are untouched; `policies/data/README.md` records why. The row still
carries `policy_version`, and `RemediationPass` declares no `prepare`.

**Three places the spec was interpreted rather than followed literally**, each argued on the
row and in the module:

1. *The comparison is equality, so a surface stating any other version establishes nothing.*
   The matrix asks for `blocked` when "every one of the four surfaces was read, none carries
   the fixed version", and "carries" cannot be decided at all from what these tables store:
   each surface records its **latest** version, not the set it carries. Equality can establish
   that a surface states the fix; its negation establishes neither presence nor absence. So
   such a surface reads `not_read` and `EQUALITY_ONLY_DETAIL` names every version it stated —
   the whole sweep, not its first row, since `conda_package_snapshots` holds one row per
   `(channel, platform)` pair. Recorded as this story's gap in `docs/deployment.md`,
   `policies/data/README.md` and the deferred list.
2. *"No open finding" was split into two states rather than one, and the line is the advisory
   collector's own.* The matrix names one state for "the package has no matched
   vulnerability". Only the collector's "read and matched nothing" sentinel establishes that;
   `error`, `not_found`, "the source cannot identify this package" and "this identity names no
   version" all establish nothing, and reporting `not_applicable` for any of them would be the
   clean-looking degradation `CPM-NFR-3` forbids. The test is the prefix test
   `policies/vulnerability.py` already applies to the same rows, against the same imported
   constant.
3. *"Re-run at a different version" produces the same verdict.* The matrix expects different
   values because the three parameterised passes read reviewed data keyed by the version. This
   pass reads none, so the only thing that differs is the recorded version — asserted as such
   rather than left unexercised.

**Two additions beyond the spec's field list, each earning its place.** `evidence_stale`, a
boolean beside the status rather than a sixth status value, which is `core/freshness.py`'s own
decision applied to a derived row and is what makes AC 3 a fact the row holds. And four
surface-snapshot FKs rather than one: the spec says "the surface snapshot that supported the
verdict", singular, which no single FK can express across four models — and four is what
`decided_surface_names_its_observation` needs to make `blocked` unreachable by silence.

**The published-package surface is read as a whole sweep**, unlike `policies/currency.py`,
which picks one row by an alphabetical channel tie-break. Copying that here would let a
channel list decide that a reviewer should give up on a package whose fix a later-sorting
channel publishes. This is `CPM-SECURITY-S05`'s review lesson — read the collector's actual
row-writing behaviour, not the shape the tests construct — applied before the fact, and an
integration case drives it.

**Roster and audit entries updated:** `tests/passes.py`'s `ADOPTED_PASS_NAMES` and
`ADOPTED_PASSES`, `test_policies_app.py`'s `EXPECTED_MODULES` and `EXPECTED_MIGRATIONS`,
`test_derived_status_writability_audit.py`'s `RECORDED_EXEMPTIONS`, and both
`test_rollup.py` cases carrying the per-domain `policy_versions` map.
`test_single_ordering_audit.py`'s `RECORDED_ORDERINGS` needs no entry —
`READINESS_PRECEDENCE` holds one `OutcomeState` member reference and is invisible to that
detector, exactly as `VULNERABILITY_PRECEDENCE` and `LICENSE_PRECEDENCE` are — and the order
is pinned by name and by contents in this story's own unit module instead.

### File List

**Added**

- `src/django_apps/conda_package_supply_chain_monitor/policies/remediation.py`
- `src/django_apps/conda_package_supply_chain_monitor/policies/migrations/0005_package_remediation.py`
- `tests/unit/django_apps/test_remediation_policy.py`
- `tests/integration/django_apps/test_remediation_policy.py`

**Modified**

- `src/django_apps/conda_package_supply_chain_monitor/policies/outcomes.py` —
  `RemediationReadiness`, `FixAvailability`, `READINESS_PRECEDENCE`, `worst_readiness`.
- `src/django_apps/conda_package_supply_chain_monitor/policies/models.py` —
  `PackageRemediation`, `SURFACE_FIX_FIELDS`, `DETERMINATE_READINESS_VERDICTS`, seven
  constraints.
- `src/django_apps/conda_package_supply_chain_monitor/policies/apps.py` — registration and
  position in the ordered list.
- `src/django_apps/conda_package_supply_chain_monitor/policies/data/README.md` — the
  statement that this pass reads no parameter.
- `docs/deployment.md` — the fifth policy section: what each readiness state tells an
  operator to do next, the equality limit, the staleness rule, and what a run costs.
- `tests/passes.py`, `tests/unit/django_apps/test_policies_app.py`,
  `tests/unit/django_apps/test_derived_status_writability_audit.py`,
  `tests/integration/django_apps/test_rollup.py` — roster and audit entries.

## Auto Run Result

**Outcome:** done, with a follow-up review recommended. `blocked` ships **unreachable**, deliberately
and on the record.

**Review loop:** one iteration, four parallel layers. Nine must-fix, thirteen should-fix, six
record-only. This was the most serious review of the epic: every one of the four paths to
`blocked` was unsound, and each reached that verdict from an **absence** rather than an
established fact — the precise thing the story exists to prevent.

**Why that mattered more here than anywhere else in the epic.** `blocked` is the value that
tells a security reviewer to stop looking. `CPM-SECURITY-S05`'s `allowed` was its mirror: the
value that must never be reached by an absence because it looks like good news. Both were, and
for the same structural reason.

**The four unsound paths.**

*A surface stating any non-equal version counted as "the fix is not here."* The four surface
tables store each surface's **latest** version, not the set it carries, so a channel at 1.2.4
still hosts 1.2.3. Inequality establishes nothing in either direction. And this was the steady
state rather than an edge: advisories name a fix, surfaces move past it, and every package with
an older advisory decayed into `blocked`. The integration case that asserted AC 2 built its
`blocked` row from four surfaces that had all *superseded* the fix, and no test anywhere used a
version older than the fix. Such a surface now reads `not_read`, keeping the foreign key to the
observation it looked at.

*A blank field became an established absence.* `ESTABLISHED_ABSENT` was selected by finding a
sentence in the finding's detail, on the belief that the sentence meant "the source answered
there is no fix". The collector writes that clause once per field the source left **blank**,
and both the model and the PRD say blank means missing and is never inferred. So the safe
branch was unreachable from any row a real collector wrote, and every advisory whose feed
omitted the field became `blocked` with no surface consulted.

*A partially-read surface voted as a fully read one.* The positive direction was symmetric
("published if any row carries the fix"); the negative was not, so an errored channel beside a
non-fix channel still cast a full vote. The test helper applied one state to every row in a
sweep, which made the mixed case unconstructible.

*The database backstop had a hole shaped exactly like the second path.* The constraint requiring
all four surfaces carved out an exception for a blank fixed version, and two documents claimed a
hand-written insert going round the pass would be refused by PostgreSQL. It would not.

**The consequence, accepted rather than worked around.** Removing the unsound paths leaves no
evidence this product currently records that can establish `blocked`. That is this story's own
Block If firing as written: record the honest state, ship the rest, record the gap. The value
stays in the vocabulary at rank 0 with both constraints still guarding it, so the day either gap
closes nothing about the schema or any query changes. Three cases assert the unreachability
directly, and one still writes a well-formed `blocked` row so the refusals are not vacuous. Two
`deferred` entries at `severity: high` name what would close it: a version-ordering rule, or a
collector recording "the source stated there is no fix" distinctly from "the field was absent".

**Two further defects worth naming.**

An advisory finding the source could not identify read as `not_applicable` — "nothing to be
ready for" — while `package_vulnerability` said `unknown` for the same package, same run, same
rows. The set of states meaning "established nothing" was `{error, not_found}`, but the collector
writes that condition as `unknown`; only one of three `unknown` shapes means "read and matched
nothing". The sibling pass already drew this line with a prefix test. The asymmetry the auditors
caught is the lesson: this pass trusted one collector-prose seam and declined the other, and both
choices landed unsafe. The test now additionally asserts both passes agree about the same sweep.

The advisory evidence's own freshness was never measured. Staleness was applied to the four
surface tables only, so a month-old advisory sweep beside a fresh channel produced `ready` with
`evidence_stale` reading false — which is `CPM-UJ-1`'s stated edge case, verbatim.

**A defect in this spec, not only in the code.** The Block If asserted that version ordering is
`CPM-AD-6`'s territory. It is not: `CPM-AD-6` governs which *surface* is authoritative, and
nothing in the spine owns version-ordering semantics at all. The implementation faithfully
propagated the error to eight code sites, two of them templates for `detail` text stored on the
row a reviewer reads, plus the deployment documentation. All corrected, including this story's
own Block If, with a Spec Change Log entry recording that the spec was wrong first.

**Why a follow-up review is recommended.** Three of the four defects were found by reading the
*collector's actual row-writing behaviour* rather than the shape this story's tests construct.
That has now been the source of the most serious finding in three consecutive stories, and it
should be a standing instruction for the next epic rather than something each review
rediscovers.

**Verification (run directly, not only reported):** `pixi run ci` exit 0 — 7089 passed, 2
skipped; coverage 99.17%; `policies/remediation.py`, `policies/models.py` and
`policies/outcomes.py` all 100%. `pixi run gate-postgres` exit 0 against `postgres:17` — 7089
passed, which is what proves the amended constraint actually refuses. `makemigrations --check
--dry-run` reports no changes. Migration `0005` was amended in place; it had not left this
branch.
