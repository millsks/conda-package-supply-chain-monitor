---
title: 'CPM-SECURITY-S02: KEV cross-reference'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: 'e564a9e7d5b2a239b0acd32e3c0fab5132075dde'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s01-vulnerability-evidence-ranges-match-confidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s04-published-conda-package-evidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s05-source-failing-never-stops-others.md
warnings:
  - oversized
deferred:
  - summary: The declared adapter is asked for the whole KEV catalog once per package, ten
      thousand times a day, and nothing in this component makes that cheaper.
    evidence: the collector base is per-package (`CPM-AD-7`, `CPM-AD-23`) and this collector
      declares `NO_CACHE` for the reason `CPM-SECURITY-S01` declares it -- a remembered
      security answer is the one this product should be slowest to replay. The catalog,
      unlike every other source this component reads, is the *same document* for every
      package, so the per-package shape asks one question ten thousand times where one would
      do. The module docstring and `docs/deployment.md` both tell an adapter author to hold
      the catalog themselves, which is the honest mitigation and not a fix -- a run-scoped
      collector that read the catalog once and cross-referenced every package would need a
      sweep contract that also wrote one ledger row per package, which the base does not
      offer.
    location: 'src/django_apps/conda_package_supply_chain_monitor/collectors/kev.py -- KEV_CACHE_TTL'
    severity: medium
  - summary: A package with more current advisories than one collection may record is refused
      outright, and records `error` on every run until its advisory history ages out.
    evidence: the row count is now bounded (`MAX_CROSS_REFERENCES`) and refused beyond the
      bound rather than left unbounded, which is the correction review asked for -- and the
      refusal is the trade `CPM-SECURITY-S01` recorded for its own document refusal, reached
      from the other side. A package over the bound gets no cross-reference at all rather
      than a partial one, daily, until enough of its advisory observations fall outside the
      freshness window. Recording the readable half beside a refusal for the rest would need
      a partial-answer contract `core/collection.py` does not offer, and truncating would be
      a permanent partial answer nothing could tell from a complete one.
    location: 'src/django_apps/conda_package_supply_chain_monitor/collectors/kev.py -- MAX_CROSS_REFERENCES'
    severity: low
  - summary: Nothing yet reads this table's `state`, so the "never clean" guarantee and the
      `not_listed`/`unknown` distinction are unobserved by any consumer.
    evidence: the guarantee is enforced at the write and asserted by this story's own cases,
      but no policy, rollup or read surface reads a KEV finding yet -- the first consumer is
      `CPM-SECURITY-S04`'s rollup pass, which is also where the precedence this vocabulary
      deliberately does not declare gets decided. Until then `core.outcomes.aggregate`
      refuses both determinate values, which is the safe failure, and the meaning of
      `not_listed` is carried by the table, its `detail` and its tests alone.
    location: 'src/django_apps/conda_package_supply_chain_monitor/collectors/models.py -- KevFinding.state'
    severity: low
  - summary: On this table the `not_found` sentinel means the catalog itself is gone, and the
      shared precedence ranks it better than `unknown`.
    evidence: "`core`'s order is worst-first `error, unknown, not_found, not_applicable, ok`,
      and the sentinels arrive by construction in every composed vocabulary. So a component
      whose KEV source has been withdrawn aggregates as healthier than one that simply had
      nothing to ask, which is backwards. This vocabulary deliberately declares no order for
      its own determinate members, leaving the sentinels ranked by inheritance; the story
      that first reduces these rows is `CPM-SECURITY-S04` and it is the one that can decide
      whether this table needs an order of its own."
    location: 'src/django_apps/conda_package_supply_chain_monitor/collectors/outcomes.py -- KevOutcome'
    severity: medium
  - summary: The read of the sibling evidence table makes one collector's output a function of
      whether another has run, which is the ordering dependency `CPM-AD-7` exists to prevent --
      made explicit rather than removed.
    evidence: the exception is recorded and narrow, but nothing sequences the two sweeps and
      nothing detects the case where the advisory collector has not run at all, so the KEV
      answer is silently one cadence behind. Offsetting the schedule reduces the window;
      removing it needs the dispatch to chain, which `CPM-CURRENCY-S05` deliberately does not
      do.
    location: 'src/django_apps/conda_package_supply_chain_monitor/collectors/kev.py -- current_findings'
    severity: medium
  - summary: "A third design was available and was not taken: rows keyed by advisory
      identifier alone, with the join materialised by the rollup pass."
    evidence: it satisfies `CPM-FR-12`'s cross-reference at the derived layer and leaves
      `CPM-AD-7` untouched, at the cost of this story's AC 1, which requires the evidence row
      itself to carry the link. Recorded so the reviewer who rules against the exception is
      handed the alternative rather than an impasse.
    location: '_bmad-output/implementation-artifacts/stories/cpm-security-s02-kev-cross-reference.md -- Spec Change Log'
    severity: low
---

# CPM-SECURITY-S02: KEV cross-reference

Epic: `CPM-EP-SECURITY` — Vulnerability, KEV and licence exposure

<intent-contract>

## Story

As a security reviewer,
I want to know which vulnerabilities are known to be exploited,
so that the queue leads with what is actually being used against people.

## Acceptance Criteria

1. **Given** existing vulnerability findings
   **When** the KEV collector runs
   **Then** each KEV finding links to the vulnerability finding it derives from and records
   the catalog date added

## Intent

**Problem:** `CPM-SECURITY-S01` records advisories, and nothing says which of them are being
used against people right now. `CPM-FR-12` needs the catalog cross-reference, and PRD
Appendix A.2 gives `kev_findings` exactly two facts: the link to the vulnerability finding it
derives from, and the catalog date added.

**Approach:** Add `KevCollector` on the base's per-package path, reading a KEV catalog through
a **declared adapter** on the terms `CPM-SECURITY-S01` established for advisories — KEV source
availability is part of PRD Open Question 1, so nothing ships. For each of the package's
current vulnerability findings, the collector asks whether that advisory is in the catalog and
writes one `kev_findings` row per answer, each carrying a foreign key to the finding it
derives from.

## Boundaries & Constraints

**Always:**
- Every evidence row is written by the base through `_write_evidence` (`CPM-AD-7`); the
  collector never saves a row and never opens a transaction.
- Every row carries a `PROTECT` foreign key to the `vulnerability_findings` row it derives
  from, and the catalog date added where the catalog stated one (AC 1).
- The state is a vocabulary composed by `core.outcomes.outcome_type`, and **the determinate
  value must not be the bare `ok`** — a determinate row here means an advisory *is* known to
  be exploited, which is the alarming case, and the shared precedence ranks `ok` best of five.
  This is the correction `CPM-SECURITY-S01`'s review forced on its sibling table; make it by
  construction here rather than by patch. Declare no precedence of the composed type's own
  until the story that reduces these rows decides one.
- A package whose advisories are none of them in the catalog writes a row saying so. A package
  with no current vulnerability finding writes a row carrying `unknown`, because there was
  nothing to cross-reference and that is not the same as nothing being exploited
  (`CPM-FR-6`, `CPM-SM-2`).
- The KEV source is a declared adapter at the base's transport seam: one slot, declared where
  a reader can see it, never discovered, refused on a second declaration, and **none ships**.
- Time comes from the injected clock; every row carries the run's instant.
- `pixi` is the only runner; `pixi run ci` exits 0 at the end.

**Block If:**
- `CPM-AD-7` says a collector "never reads another collector's evidence table", and this
  collector must read `vulnerability_findings` to have anything to cross-reference. The
  alternatives are both closed: a policy pass could read both tables but `CPM-AD-9` forbids it
  the outbound call the catalog needs, and a `kev_findings` row that carried no link would fail
  AC 1 outright. This story therefore reads that one table, read-only, and records the
  exception in its Spec Change Log — noting that `CPM-AD-7` binds `CPM-FR-12` and that the
  dependency it exists to prevent is an *implicit* one, where this is required and explicit.
  **If review finds that reading another collector's evidence table cannot be reconciled with
  `CPM-AD-7`, HALT** and hand back the two closed alternatives rather than choosing one.

**Never:**
- No KEV source chosen, named as a default, or shipped.
- No import of another collector module. The evidence model is reached through the shared
  models module, which every collector already imports; what is new is the read, not a
  dependency between collector modules.
- No write to `vulnerability_findings`, ever, and no change to what `CPM-SECURITY-S01` records.
- No severity, no ranking, no priority, and no derived status: what a KEV hit *means* for a
  package is `CPM-FR-17`'s rollup, which is `CPM-SECURITY-S04`.
- No change to `core/collection.py`, `core/freshness.py`, `OutcomeState`, `identity`'s writers,
  or any shipped collector or policy.
- No `timezone.now()` anywhere.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| One advisory is in the catalog (AC 1) | the package has one current matched vulnerability finding, and the catalog lists that advisory | one determinate row linking to that finding and carrying the catalog date added; ledger `succeeded` | No error |
| Several advisories, some listed | three current findings, two listed | three rows — two determinate with their dates, one saying that advisory is not in the catalog — each linked to its own finding | Never merged |
| No advisory is listed | current findings, none in the catalog | one row per finding saying so; ledger `succeeded` | A negative that was established |
| Catalog states no date | the advisory is listed with no date added | determinate row with the date blank and a detail saying the catalog stated none | Blank means missing, never invented |
| No current vulnerability finding | the package has no finding, or only non-determinate ones | one row carrying `unknown` saying there was nothing to cross-reference; no call is made if the collector can decide that before asking | Never a clean result |
| Superseded findings | the package has two findings for one advisory at different instants | only the most recent per advisory is cross-referenced, and the row links to that one | Append-only history, one current answer |
| Duplicate catalog entries | the catalog lists one advisory twice | refused as a document defect | The source contradicted itself |
| Date the collector cannot read | the catalog states a date that does not parse, or parses naive | determinate row with the date blank and a detail saying so | Never guessed |
| Unreadable document | body over the bound, not JSON, wrong shape, or a field of the wrong type | a document error from `translate`; the base writes an `error` row and re-raises | Refused rather than partly read |
| No adapter declared | nothing declared the KEV source | the run fails naming the declaration; no evidence row | A misconfiguration, not a finding |
| Two adapters declared | a second declaration of a different adapter | refused at declaration | One slot |
| Adapter fails | the adapter raises a transport failure | `error` row, ledger `failed` | Base path |
| Sweep selection | the dispatch offers packages | every package is offered while a source is declared, so a package with no findings still gets its `unknown` row on a scheduled run | The lesson `CPM-SECURITY-S01` was patched for |
| Spent allowance | limiter refuses | `error` row, ledger `failed` | Base path |
| Sentinel asked for the determinate value | `sentinel_evidence` asked for it | `CollectorConfigurationError` | Refused at the call |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/collectors/vulnerability.py` -- the
  sibling and the closest template: its declarations, its pure functions, its
  `selectable_packages` (patched to offer every package), the way it refuses a document, and
  the shape of its adapter use. Read it and `CPM-SECURITY-S01`'s Review Triage Log first — its
  twenty-six findings are the mistakes not to repeat, and two of them are about exactly the
  vocabulary decision this story must get right by construction.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/advisories.py` -- the one-slot
  adapter contract to mirror: declare, withdraw, read, and the four refusals, made atomic under
  a lock. The KEV source gets its own slot and its own error type; it is a second source, not a
  second use of the first.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/outcomes.py` -- where
  `CPM-SECURITY-S01`'s composed vocabulary lives and why it declares no precedence. Add this
  story's beside it.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` --
  `VulnerabilityFinding` is the table to read and `KevFinding` the table to add:
  `package` (`PROTECT`), a `PROTECT` foreign key to the vulnerability finding, `source`,
  `state`, `catalog_date_added` (nullable), `detail`, `trace_id`; a read index on
  `(package, -observed_at)`; a `CheckConstraint` making the catalog facts present exactly on a
  determinate row; **no unique constraint of any kind** (`CPM-AD-2`).
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/` -- `0007` is the
  newest; add `0008_kev_findings.py` depending on it and on `identity.0001_package_identity`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py`, `apps.py`,
  `src/config/settings/base.py` -- the task, the roster of seven, the adapter declaration
  point, and the beat entry reconciled against the declared cadence (`CPM-NFR-2` puts security
  at daily).
- `tests/collectors.py`, `tests/unit/django_apps/test_vulnerability.py`,
  `tests/integration/django_apps/test_vulnerability.py` -- the fixtures and module shapes to
  mirror, including the adapter-slot autouse fixture that asserts the slot starts empty.
- `tests/unit/test_model_registry.py`, `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py`, `tests/unit/django_apps/test_sweep.py`,
  `tests/unit/test_settings.py` -- the rosters and audits a seventh collector reaches. Several
  of these carry collector counts in prose; `CPM-SECURITY-S01` reconciled four files that had
  drifted, so update every count rather than the one that fails.
- `docs/deployment.md` -- the vulnerability collector's section is the template; this one must
  say that a second source must be declared, that the two are independent, and what a KEV row
  does and does not claim.

## Tasks & Acceptance

**Execution:**
- `collectors/models.py`, `collectors/migrations/0008_kev_findings.py` -- the table, its read
  index and its constraint.
- `collectors/outcomes.py` -- the composed KEV vocabulary, determinate member named for what a
  determinate row means, no precedence declared.
- `collectors/kev.py` -- new. The KEV adapter slot and its refusals; the declarations; the pure
  functions (the catalog document to its entries, and the cross-reference of a package's
  current findings against them); and `KevCollector`.
- `collectors/tasks.py`, `collectors/apps.py`, `config/settings/base.py` -- the task, the
  roster of seven, and the schedule entry.
- `tests/unit/django_apps/test_kev.py` -- new: every matrix row reachable without a database,
  the adapter refusals, and the module's own source sweeps — including one asserting this
  module reads `vulnerability_findings` and writes nothing to it.
- `tests/integration/django_apps/test_kev.py` -- new: every matrix row that needs a run,
  including the link asserted by following the foreign key back to the finding, the superseded
  case, the no-findings case read back through freshness, the constraint refused by the
  database, re-observation inserting, the task, and a dispatch case.
- The rosters, audits and `docs/deployment.md`.

**Acceptance Criteria:**
- Given a package with one current matched vulnerability finding whose advisory the catalog
  lists, when the collector runs, then one row links to that finding by foreign key and carries
  the catalog date added.
- Given a package with three current findings of which two are listed, when the collector runs,
  then three rows exist, each linked to its own finding, and no row links to two.
- Given a package with two findings for one advisory at different instants, when the collector
  runs, then the row links to the more recent.
- Given a package with no current vulnerability finding, when the collector runs, then one row
  carrying `unknown` exists.
- Given no declared KEV source, when the collector runs, then the run fails naming the
  declaration and writes no evidence row.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

### 2026-09-06 — Recorded before implementation

**The architecture decision this story reads against.** `CPM-AD-7` says a collector "writes its
own evidence table plus its run-ledger row, and reads only `identity`. It never imports another
collector, never reads another collector's evidence table". This collector reads
`vulnerability_findings`, which that sentence forbids.

**Why the alternatives are closed.** *Corrected after review, which found the first citation
wrong.* A policy pass may read any evidence and would satisfy the link. `CPM-AD-9` does **not**
close it — that decision is the request/task boundary, and a pass is a Celery task, so the
outbound call is not forbidden by it. What closes it is `CPM-AD-8`, whose replay guarantee a
live catalog fetch cannot meet, and `CPM-AD-21`, under which a pass writes only its own
per-domain derived table while PRD Appendix A.2 makes `kev_findings` evidence. A collector that
read only the catalog could write rows keyed by advisory identifier, but AC 1 requires each row
to link to the vulnerability finding it derives from.

**A third alternative, named for completeness.** A KEV collector could write rows keyed by
advisory identifier alone and let `CPM-SECURITY-S04`'s pass materialise the join in its derived
table. That satisfies `CPM-FR-12`'s "cross-reference" at the derived layer and leaves
`CPM-AD-7` untouched, at the cost of AC 1's literal wording — the evidence row would carry no
link. It is recorded here rather than dismissed, because it is the option a reviewer who rules
against the exception should be handed.

**What is taken.** The read, narrowly: one table, read-only, reached through the shared models
module rather than by importing the sibling collector, and never written. `CPM-AD-7` binds
`CPM-FR-12`, so the architecture had this collector in scope when it was written, and the
dependency the rule exists to prevent is an *implicit* ordering between collectors — this one is
required by the requirement and explicit on the row.

**What is not taken.** No import of another collector module; no write to another table; no
derived status. The exception is this collector's alone and is recorded here rather than
amended into the architecture, which is not this story's to change.

**Surfaced rather than settled.** The Block If hands this judgement to review, which may HALT.

### 2026-09-07 — what shipped for the "no call is made" half of the no-findings cell

Recorded because it is the mistake the sibling story was patched for, and the matrix
cell here is worded conditionally: "one row carrying `unknown` saying there was nothing to
cross-reference; **no call is made if the collector can decide that before asking**". It cannot.
`core/collection.py` charges the allowance and calls the transport before `translate` is reached,
and the only call-free path it offers is `inapplicability`, which writes `not_applicable` — a
state this table refuses outright and which the Always list rules out in as many words.

So the call **is** issued, and the row does not pretend otherwise. What the collector does
control is that no *answer* is read: `translate` reads the package's current findings first and
returns the `unknown` row without touching the payload, so no catalog document is parsed and
nothing a source said can influence a row about our own missing evidence.
`tests/integration/django_apps/test_kev.py` asserts `adapter.calls` at that case — the one place
a `detail` claiming otherwise would have failed — and asserts that the wording does not deny it.

### 2026-09-07 — the vocabulary carries two determinate values rather than one

Tasks asked for "the composed KEV vocabulary, determinate member named for what a determinate row
means" — singular. Three facts have to stay apart on this table and only two of them are
sentinels: the catalog lists the advisory; the catalog was read and does not list it; and there
was nothing to cross-reference. The third is `unknown`. The second is a negative that was
*established* about one advisory, which is neither `unknown` nor `not_found` — `not_found` is
reached by the base when the KEV source reports that the **locator** does not exist, and folding
the two together would leave a reader unable to tell "not in the catalog" from "the catalog is
gone". `CPM-FR-6` is the rule that forbids that fold, so `KevOutcome` composes `listed` and
`not_listed`, and `core.outcomes.aggregate` refuses both until `CPM-SECURITY-S04` ranks them.

Neither is `ok`, which is the requirement the Always list states and the correction the sibling
was patched for.

### 2026-09-07 — the read couples this module to the sibling's schema as well as its rows

Named after review, which found the first record incomplete. The exception above is written
as a read of *rows*, and it is also a read of a *column definition*:
`_require_storable` measures a catalog's advisory identifier against
`VulnerabilityFinding.advisory_id`'s `max_length`, because that is the column an identifier is
ever compared against and nothing on `kev_findings` stores one. So a width changed on that
table changes what this collector refuses.

It is the narrower of the two dependencies and it is taken for the same reason: bounding
against a number restated here would be a second declaration that drifts, and bounding against
nothing would let a catalog state an identifier no vulnerability finding could ever carry. It
is recorded rather than left implicit because "reads one table, read-only" does not, on its
face, cover reading that table's schema.

### 2026-09-07 — the locator names the catalog rather than the package

The Code Map points at `collectors/vulnerability.py` as the closest template, and its locator
embeds the package's purl. This one is a constant, `kev://declared-source/catalog`, and the
difference is what is being asked: a KEV catalog is one document *about advisories*, and which of
this product's advisories get cross-referenced against it is our own evidence rather than
anything an adapter could be told. A locator embedding a purl would name a package the adapter
has no use for, would need the identity read and the width refusal that come with it, and would
have every identity-less package sharing one spelling for a question that was never about
identity. `source_for` therefore raises nothing, and a case asserts the constant fits the column
that records it.

## Review Triage Log

### 2026-09-06 — Review pass

- intent_gap: 0
- bad_spec: 1: (high 0, medium 1, low 0)
- patch: 25: (high 3, medium 19, low 3)
- defer: 3: (high 0, medium 2, low 1)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[medium]` `[bad_spec]` The Spec Change Log closed the policy-pass alternative by citing the
    request/task boundary, and a policy pass *is* a task, so the citation did not hold. The
    conclusion survives on other grounds — a live catalog fetch cannot meet the replay guarantee,
    and a pass writes only its own derived table while this is an evidence table — and the entry
    now says so. A third design was also named rather than left out: rows keyed by advisory
    identifier alone, with the join materialised by the rollup pass, which is what a reviewer
    ruling against the exception should be handed instead of an impasse.
  - `[high]` `[patch]` **Advisory-identifier aliasing produced the reassuring value.** The match
    was an exact case-folded string lookup while the same vulnerability commonly carries a CVE
    number, a GitHub identifier and a Python identifier — the story's own fixtures use all three.
    A finding recorded under one scheme against a catalog listing it under another wrote
    `not_listed`: a confident claim that a vulnerability is *not* known to be actively exploited,
    permanent and in the direction that reassures. Aliases the catalog states are now honoured,
    and where a lookup misses, the catalog is asked whether it states any identifier in that
    scheme at all — a catalog that knows nothing of the scheme answers `unknown`, never the
    negative.
  - `[high]` `[patch]` The module told an adapter author the document may carry a narrative field
    and the reader refuses exactly that field, so an adapter written to the contract would have
    had every catalog refused and every package recording an error indefinitely. The contract
    section is now swept by a case so the two cannot drift again.
  - `[high]` `[patch]` A matched advisory was never retired: the sibling collector records
    "nothing matched today" as one row naming no advisory, so once an advisory had been matched
    every later run kept cross-referencing it for the life of the package. "Current" is now
    bounded by this collector's own freshness target as well as by advisory, and a run that
    excluded something says so on every row rather than only on the run.
  - `[medium]` `[patch]` Nineteen further findings, each addressed. A withdrawn catalog was
    silent — a `succeeded` run and a `not_found` row for every package, daily, with the only
    documented alert firing on a different condition. One sentence covered four different
    reasons for `unknown`, which is the distinction the outcome vocabulary exists to keep. The
    write audit that justified the read-only claim omitted the six escapes the append-only base
    itself enumerates, and the "one table and no third" sweep could be evaded by a registry
    lookup or a reverse relation. Nothing required the linked finding to be about the same
    package. The two document ceilings were within one percent of each other, so the wrong
    refusal fired first. The catalog's stated date and the transport's error message reached a
    row without the guard every other stored value passes. The two security sweeps fired on one
    tick, so the cross-reference ran a cadence behind. And the row count one collection writes
    was unbounded.
  - `[low]` `[patch]` Three further findings: a guarantee claimed by a test name and observed by
    no assertion, because the catalog the case scripted parsed cleanly; a coupling to the sibling
    table's schema as well as its rows, now named; and a note that the in-code pointers cite a
    record living outside the reviewed diff.

## Design Notes

**Why the determinate value is composed rather than `ok`.** `CPM-SECURITY-S01` shipped its
sibling table with the bare determinate value and review caught it: on a security table a
determinate row is the alarming case, while the shared precedence ranks `ok` best of five, so a
read surface would render exactly the exploited packages as clean. That correction is made here
by construction. The vocabulary declares no precedence of its own, so the shared reducer refuses
it outright until `CPM-SECURITY-S04` decides how a KEV hit ranks — a loud refusal being the safe
failure.

**Why "no current finding" is `unknown` rather than a clean answer.** A package with nothing to
cross-reference has not been shown to be free of known-exploited vulnerabilities; it has been
shown that this product has no advisory for it. Those are different facts and `CPM-FR-6` exists
to keep them apart. It is also why the sweep offers every package: `CPM-SECURITY-S01` was
patched for excluding the population whose rows it existed to guarantee, and repeating that here
would be the same defect in a second table.

**Why only the most recent finding per advisory is cross-referenced.** Evidence is append-only
and re-observation inserts, so a package accumulates many rows per advisory. The current answer
is the newest per advisory, ordered by observation instant then primary key so a replay is
reproducible — the tie-break every cut-off-bound read in this product states.

## Verification

**Commands:**
- `pixi run test` -- expected: exit 0, the new unit module collected and passing.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: exit 0, no diagnostics.
- `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected".
- `pixi run ci` -- expected: exit 0; coverage >= 90%, the new modules at 100%.
- `pixi run gate-postgres` -- expected: exit 0; the constraint and both `PROTECT` relations are
  enforced there.

**Manual checks (if no CLI):**
- `git diff --stat e564a9e` names the new collector, the migration, the roster updates and the
  settings entry, and shows no change to `collectors/vulnerability.py`'s behaviour.

## Dev Notes

**Satisfies:** `CPM-FR-12`

**Governed by:**

- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts

**Constrained:** KEV source availability is part of PRD Open Question 1.

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-SECURITY-S02]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-12]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context)

### Debug Log References

None. No harness halt condition was reached and no triage report was generated.

### Completion Notes List

- **AC 1** — a `listed` row carries a `PROTECT` foreign key to the
  `vulnerability_findings` row it derives from and the catalog date added.
  `tests/integration/django_apps/test_kev.py` asserts the link by **following the key
  back** to the finding and reading its advisory and its package, rather than by
  comparing integers: a row carrying the right key in the wrong column, or a relation
  pointed at the wrong model, would pass a comparison and fail that.
- **The determinate values are `listed` and `not_listed`, and neither is `ok`.** This is
  the correction `CPM-SECURITY-S01`'s review forced on its sibling table, made here by
  construction. `collectors/outcomes.py` composes `KevOutcome` beside
  `VulnerabilityOutcome`, declares no precedence, and `core.outcomes.aggregate` refuses
  both determinate values — which is the safe failure until `CPM-SECURITY-S04` decides
  how a KEV hit ranks. Two determinate members rather than one: see the Spec Change Log.
- **A package with no current vulnerability finding writes one row carrying `unknown`**,
  and the sweep offers **every** package so a scheduled run writes it. That is the second
  defect `CPM-SECURITY-S01` was patched for, not repeated in a second table.
- **The `CPM-AD-7` exception is narrow and is asserted mechanically.** `current_findings`
  is the one read: `vulnerability_findings`, filtered to `matched` rows for one package,
  newest per advisory by `(observed_at, pk)`, grouped case-insensitively. The unit sweep
  asserts the module names `VulnerabilityFinding` and reaches no write method anywhere;
  an integration case runs a whole collection and compares that table's rows column by
  column before and after. No collector module is imported — the model is reached through
  `collectors/models.py`, which every collector already imports.
- **The KEV source is a second declared adapter slot, not a second use of the advisory
  one.** `declare_kev_source` / `withdraw_kev_source` / `declared_kev_source` /
  `kev_source` live in `collectors/kev.py` with their own error type and their own lock,
  and a case asserts that declaring one leaves the other empty. **No source is declared
  anywhere under `src/`**, proved by a source sweep against a named, licensable set that
  ships empty.
- **The locator is a constant naming the catalog**, not the package — see the Spec Change
  Log. `source_for` therefore raises nothing and reads no identity.
- **A catalog date that does not parse, or that parses naive, is recorded as missing with
  a reason rather than refused or guessed.** A bare `2024-02-06` is the shape a catalogue
  is likeliest to publish and it parses naive; assuming UTC would be a permanent claim
  shifted by a guess (`CPM-AD-26`). The document is not refused, because what `CPM-FR-12`
  is about is the link and discarding a catalog over one malformed date would lose every
  cross-reference for every package.
- **Two constraints and no unique constraint of any kind.** The link is present exactly on
  a determinate row, the catalog date only on a `listed` one, and `not_applicable` is
  refused outright. Every conjunct is asserted by watching the database refuse a write,
  with anti-vacuity cases for the two shapes the rule must permit.
- **Counts settled**: **seven** collectors are **registered**; **six** are **swept** one
  package at a time. Every count in `collectors/sweep.py`, `collectors/tasks.py`,
  `config/settings/base.py`, `docs/deployment.md`, `tests/collectors.py`,
  `tests/unit/django_apps/test_sweep.py`, `tests/unit/django_apps/test_collection.py`,
  `tests/unit/startup/test_no_softening.py`,
  `tests/integration/django_apps/test_collection.py` and
  `tests/integration/startup/test_stage_two_collector_registry.py` now says which it means.
- `inapplicability` is deliberately **not** overridden and `sentinel_evidence_rows` is
  deliberately **not** overridden; both are asserted to be the base's by identity, with the
  reason recorded beside the omission in the collector.
- The migration is hand-edited once, to depend on `identity.0001_package_identity` rather
  than the later identity migration the autodetector named — the convention `0002` through
  `0007` already follow. `makemigrations --check --dry-run` reports "No changes detected".
- Six `deferred:` entries recorded.

### After the review pass — 25 findings applied

- **`not_listed` is no longer claimed on an exact-match miss alone.** Matching is
  alias-aware — a catalog entry may state `aliases`, and every spelling keys the same
  entry — and a finding whose identifier scheme the catalog never states records
  `unknown` with a reason rather than the reassuring value. A CVE-only catalog has
  nothing to say about a `GHSA-` finding it never had the vocabulary to list. This is
  the highest-value change in the round: the previous behaviour wrote an established
  negative the run had not established, permanently, about whether something is being
  exploited.
- **"Current" is bounded in time.** The newest matched finding per advisory, and only
  while it is no older than this collector's freshness target. Without it nothing ever
  retired an advisory — the sibling records "nothing matched" as one row naming no
  advisory — so one match would have been cross-referenced for the life of the package.
  The bound also bounds the read and the row count, and a run that excluded anything
  says so on **every** row it writes, because a reader holds one row rather than a run.
- **The module's adapter contract said `detail` was permitted while the reader refused
  it.** An adapter written to that docstring would have had every document refused. The
  contract is now swept by a case rather than trusted.
- **`unknown` carries four sentences rather than one** (`CPM-FR-6`): no advisory source
  declared, the advisory collector has not observed this package, it observed and
  matched nothing, or everything it matched is stale. Only the third is a statement
  about the package.
- **`kev.catalog_absent` is a second event.** A declared source answering `found=False`
  writes `not_found` under a **`succeeded`** ledger row, so a withdrawn catalog produced
  a day of clean-looking runs with nothing in the log.
- **An enqueued task that meets a withdrawn source now records a `failed` run.** The
  refusal happens inside an open ledger row, so a withdrawal between a dispatch's
  selection and its tasks running leaves ten thousand recorded refusals rather than
  nothing at all.
- **The KEV beat entry is offset an hour** from the vulnerability one, as a `countdown`
  in the entry's `options` — the only phase the schedule can express, because the
  cadence reconciliation compares intervals. It reduces the window and does not close
  it; the residual is a `deferred` entry.
- **The two catalog ceilings are separately reachable.** They were within a percent of
  each other, so a full-size catalog tripped the character bound and an operator saw the
  wrong refusal. `MAX_ENTRIES` is 20,000 and the parse ceiling 2 MiB, with a case
  asserting both directions.
- **Rows per collection are bounded and refused beyond the bound** rather than left as a
  note; a whitespace-only advisory identifier — which the sibling table's constraint
  permits — is refused rather than cross-referenced; a payload body that is not a string
  is refused by name; a catalog date outside 1999–2200 is recorded as missing rather
  than raising at insert; the echoed date and the sentinel reason both pass guards now
  (the first refuses, the second cleans — a sentinel row must be written).
- **The `unknown` row may carry a link.** It is a fact rather than a loosened rule: a row
  about one advisory the catalog cannot speak to names that advisory; a row about a
  package with nothing to cross-reference names none. The constraint was widened for it
  and the migration regenerated in place.
- **The linked finding must be about the same package**, held where SQL cannot hold it.
  A `CHECK` is per row and the composite foreign key that would express it needs a
  `UniqueConstraint` on `vulnerability_findings`, which `EVIDENCE.02-AUDIT-003` bans.
  `KevFinding.save()` refuses the mismatch, the collector takes the row's package from
  the finding, and the model docstring names the one writer that leaves uncovered.
- **`CPM-AD-7`'s removed clause has a mechanical replacement.**
  `MODULES_PERMITTED_TO_READ_ANOTHER_COLLECTORS_EVIDENCE` in
  `tests/unit/django_apps/test_collector_base_audit.py` sweeps every registered
  collector in both directions, so a second reader fails loudly and a stale licence
  fails too. The evidence models are read off the registry rather than listed.
- The write sweep gained `update`, `bulk_update`, `delete`, `_raw_delete`, `raw` and
  `_base_manager`; the model sweep gained `apps.get_model`, string-valued model
  references and related-manager traversal, with the residual evasion surface stated.
- The outcome vocabulary is no longer re-exported from the collector; the freshness case
  asserts the instant the table supplies rather than the status it was handed; and the
  missing cases landed — a `not_modified` answer, an adapter raising a non-transport
  error, and the unread-catalog case that makes "the payload is not read" falsifiable.

**The Spec Change Log's own record is outside the reviewed diff.** `collectors/kev.py`,
`collectors/models.py` and the new audit all point a reader at
`CPM-SECURITY-S02`'s Spec Change Log for the argument behind the `CPM-AD-7` exception, and
that file is a planning artifact rather than part of the change under review — so a reviewer
reading the diff alone sees the pointers and not the record they point at. The exception's
*shape* is legible from the code (one table, read-only, licensed by an allowlist that fails
in both directions); its *justification* is not.

### File List

**New**

- `src/django_apps/conda_package_supply_chain_monitor/collectors/kev.py`
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/0008_kev_findings.py`
- `tests/unit/django_apps/test_kev.py`
- `tests/integration/django_apps/test_kev.py`

**Modified**

- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py`
- `src/django_apps/conda_package_supply_chain_monitor/collectors/outcomes.py`
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py`
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py`
- `src/django_apps/conda_package_supply_chain_monitor/collectors/sweep.py`
- `src/config/settings/base.py`
- `docs/deployment.md`
- `tests/collectors.py`
- `tests/unit/test_model_registry.py`
- `tests/unit/test_settings.py`
- `tests/unit/django_apps/test_collection.py`
- `tests/unit/django_apps/test_collector_base_audit.py`
- `tests/unit/django_apps/test_sweep.py`
- `tests/unit/startup/test_no_softening.py`
- `tests/integration/django_apps/test_collection.py`
- `tests/integration/startup/test_stage_two_collector_registry.py`

`tests/unit/django_apps/test_collector_base_audit.py` is where the review round added
`MODULES_PERMITTED_TO_READ_ANOTHER_COLLECTORS_EVIDENCE` and its two sweeps; it was already
on the list above for the module roster.

## Auto Run Result

Status: done
Blocking condition: none

**What was implemented.** `CPM-FR-12`'s KEV cross-reference — the seventh collector.
`KevCollector` reads a package's current vulnerability findings, asks a declared catalog source
which of those advisories are known to be actively exploited, and writes one row per advisory
carrying a foreign key to the finding it derives from and the catalog date added. A package with
nothing to cross-reference writes one row carrying `unknown`.

**The vocabulary was got right by construction, which is the lesson the sibling story was
patched for.** `KevOutcome` composes two determinate members, neither of them the shared `ok`,
because three facts must stay apart: the catalog lists this advisory, the catalog was read and
does not list it, and there was nothing to cross-reference. Neither declares a precedence, so the
shared reducer refuses both until the rollup story decides how a known-exploited finding ranks.

**One architecture exception, recorded rather than assumed.** A collector may not read another
collector's evidence table, and this one must. The alternatives are closed: a policy pass cannot
meet the replay guarantee with a live catalog fetch and may write only its own derived table,
while a row carrying no link fails AC 1. The read is one table, read-only, one package, filtered
and bounded — and it is now licensed in the source tree by an allowlist swept in both directions,
so a second collector taking the same read fails loudly rather than inheriting a precedent.

**Files changed.**

- `collectors/kev.py` *(new)* — the KEV adapter slot and its refusals, the declarations, the
  catalog reader, the cross-reference and the collector.
- `collectors/models.py`, `collectors/outcomes.py` + migration — the table, its constraints and
  its vocabulary.
- `collectors/tasks.py`, `collectors/apps.py`, `collectors/sweep.py`, `config/settings/base.py`
  — the task, the roster of seven, and the schedule entry offset from the sibling's.
- `docs/deployment.md` — what an adapter owes, what each row means, and what the cross-reference
  can and cannot establish.
- New unit and integration modules; the rosters and audits a seventh collector reaches.

**Review findings.** 1 spec repair and 25 patched (3 high, 19 medium, 3 low), 3 deferred, 2
rejected. Four review layers ran in parallel over the 5,700-line diff.

**Follow-up review recommended:** true. Three high-severity patches. Patched counts: high 3,
medium 19, low 3; score `3 x 19 + 1 x 3 = 60`, far over the threshold of 5.

**The most dangerous finding was a false negative in the direction that reassures.** The same
vulnerability commonly carries a CVE number, a GitHub identifier and a Python identifier, and the
match was an exact string comparison — so a finding recorded under one scheme against a catalog
listing it under another wrote "not listed", a confident claim that something is *not* known to
be actively exploited, permanently, in a table nothing corrects. Aliases are now honoured, and a
catalog that knows nothing of an identifier's scheme answers `unknown` rather than the negative.

**The other two were of a piece with it.** The module told an adapter author the document may
carry a field the reader refuses, so a compliant adapter would have had every catalog rejected.
And a matched advisory was never retired, so once matched it was cross-referenced for the life of
the package, long after the advisory source stopped matching it.

**Verification.** `pixi run ci` exits 0 — 6303 passed, 2 pre-existing skips, coverage 99.03%,
with `kev.py` and the modules it touches at 100%. `makemigrations --check --dry-run` reports "No
changes detected". `pixi run gate-postgres` passes against `postgres:17`. All three were re-run
by the orchestrating session after the patch round.

**Residual risks.** Six `deferred` entries. Three matter: on this table the "not found" sentinel
means the catalog itself is gone, and the shared order ranks it better than "nothing was
established", so a component whose source was withdrawn aggregates as healthier than one that had
nothing to ask — the rollup story is the first that can decide whether this table needs an order
of its own. The read of the sibling table makes one collector's output a function of whether
another has run, which the schedule offset narrows but does not remove. And a package whose
advisory count exceeds the row bound records an error daily until its history ages out.
