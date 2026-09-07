---
title: 'CPM-SECURITY-S03: Licence evidence, raw and normalized'
type: 'feature'
created: '2026-09-07'
status: 'done'
review_loop_iteration: 1
followup_review_recommended: true
baseline_revision: 'ce80d19f597ef57988db31aa0f781c510eab9c3a'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s01-vulnerability-evidence-ranges-match-confidence.md
  - _bmad-output/implementation-artifacts/stories/cpm-security-s02-kev-cross-reference.md
  - _bmad-output/implementation-artifacts/stories/cpm-currency-s04-published-conda-package-evidence.md
warnings:
  - oversized
deferred:
  - summary: >-
      The bounded call each further channel costs is not charged against the local allowance, so
      one collection issues up to four times the requests the counter believes it did.
    evidence: |-
      Inherited verbatim from `collectors/conda_package.py`, where `CPM-CURRENCY-S04` already
      records it at severity medium against `conda_package.py -- _channel_instead`. It is
      restated here against this module's own copy so a sweep triaging by *location* does not
      fix one and miss the other: the base charges `1 + retries` = 2 once, before the first
      channel, and `_channel_instead` issues channels two onward from `translate`, after that
      charge. With `MAX_MONITORED_CHANNELS` declared, one collection sends up to 8 requests to
      `api.anaconda.org` and is charged for 2 -- so a declared thirty a minute permits roughly
      120 requests a minute against a host the published-package collector is spending its own
      allowance on at the same tick. `docs/deployment.md` now states the issued figure beside
      the charged one rather than the charged one alone, and
      `test_a_whole_collection_issues_more_requests_than_the_allowance_is_ever_charged_for`
      pins the arithmetic. Charging it means reaching past the base's orchestration into the
      limiter, which is the base seam this story's Never list forbids changing, and the
      arithmetic belongs with the story that first sweeps at volume (`CPM-CURRENCY-S05`).
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/license.py -- _channel_instead
    severity: medium
  - summary: >-
      Only the first monitored channel's answer is cached, so channels two onward re-transfer
      their whole document on every run for ever.
    evidence: |-
      The second inherited item against the same seam, recorded here for the same
      triage-by-location reason. `LICENSE_CACHE_TTL` is declared and honoured -- by the *base*,
      around the one call the base makes. `_channel_instead` passes `entry=None` to
      `request_headers`, so its requests carry no validator, and it neither reads nor writes the
      response cache, so nothing is remembered. A channel's package document lists every file of
      every version and is the largest body this product reads, so a four-channel declaration
      re-transfers three of them daily for ever -- and a `304` from one of them is a source
      answering a question nobody asked, which the row records as `error`. Extending the cache
      to them means reaching past the base's orchestration into the response cache, which this
      story's Never list forbids.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/license.py -- _channel_instead
    severity: medium
  - summary: >-
      `selectable_packages` and `monitored_channels` disagree about what "declared" means, so a
      five-channel declaration is offered as the whole inventory and then fails every collection.
    evidence: |-
      `selectable_packages` asks `declaration_fault`, which checks the container *type* only.
      `monitored_channels` additionally refuses more than `MAX_MONITORED_CHANNELS` entries,
      duplicates, blanks, non-segments and entries wider than the channel column. So
      `CPM_MONITORED_CHANNELS = ["a", "b", "c", "d", "e"]` selects every package and then fails
      every one of them, daily, which is the "ledger fills with failed runs" shape the selection
      exists to prevent -- reached from a misconfiguration rather than from the shipped state.
      The collector's docstring claimed the two "cannot come to disagree"; that claim is
      corrected in place. The behaviour is inherited from `collectors/conda_package.py` and is
      deliberately **not** diverged from here: one collector narrowing its selection where its
      sibling does not would be two answers to "what does declared mean" rather than one, and
      correcting it means editing a shipped collector, which this story's Never list forbids.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/license.py -- LicenseCollector.selectable_packages
    severity: low
  - summary: >-
      A raw licence over 512 characters is a permanent daily failure that records nothing
      reviewable at all.
    evidence: |-
      Spec-conformant and tested -- "refused where the value enters, never truncated", because a
      truncated licence is a different licence -- and deliberately unchanged. It is recorded
      because it is the one refusal in this module that produces an unbreakable loop with zero
      evidence: the run fails, the row carries `raw_license=""`, the observation window only
      suppresses after a success, and it repeats every day with nothing a reviewer can act on.
      That is the opposite of this story's "reviewable rather than merely wrong" posture. The
      alternative not taken is a truncated raw value plus a `detail` naming the true length,
      which would stay reviewable without claiming a licence; it needs a column that can say
      "this is not the whole string", which is a table change. See the Design Note.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/license.py -- _require_storable
    severity: low
---

# CPM-SECURITY-S03: Licence evidence, raw and normalized

Epic: `CPM-EP-SECURITY` — Vulnerability, KEV and licence exposure

<intent-contract>

## Story

As a compliance reviewer,
I want the raw licence and its normalized expression recorded side by side,
so that I can see what normalization did before I trust its result.

## Acceptance Criteria

1. **Given** a package
   **When** the licence collector runs
   **Then** it records raw licence, normalized SPDX expression and detection method

2. **Given** a licence that cannot be parsed
   **When** the collector completes
   **Then** it records `unknown` and routes to manual review, never `allowed`

## Intent

**Problem:** `CPM-FR-13` needs the third security collector, and nothing records what a package
is licensed under. `CPM-SM-2` measures this product on every licence finding carrying source,
timestamp and confidence, with zero findings presenting an unknown as clean — and a licence is
the one surface where a normalizer can quietly turn an ambiguous string into a confident answer.

**Approach:** Add `LicenseCollector` on the base's per-package path, writing `license_findings`.
It reads the licence a monitored channel states for the package, records the raw string exactly
as stated **beside** the normalized SPDX expression and the method that produced it, and refuses
to normalize what it cannot recognise — an unrecognised licence records `unknown` with the raw
value preserved, which is what makes the row reviewable rather than merely wrong.

## Boundaries & Constraints

**Always:**
- Every evidence row is written by the base through `_write_evidence` (`CPM-AD-27`); the
  collector never saves a row and never opens a transaction. AD-27 is the decision that owns
  the transport-and-write seam; AD-7 governs which tables a collector may read and write, which
  is a neighbouring rule and not this one.
- The raw value is recorded **verbatim**, exactly as the source stated it, on every row that has
  one — including rows whose normalization failed. That is the whole point of AC 1: a reviewer
  compares the two columns to judge what normalization did.
- The normalized value is an SPDX expression or it is blank. A licence the collector cannot
  recognise normalizes to blank and the row records `unknown`. Nothing is guessed, and no
  partial normalization is written as if it were complete.
- The detection method is recorded on every determinate row, naming how the licence was
  established. `CPM-SM-2` requires source, timestamp **and** confidence on every licence
  finding; `source` and `observed_at` carry the first two, `detection_method` carries "carries
  source" at the level a reviewer asks about, and the **confidence element is not taken** — see
  the Spec Change Log. There is no confidence column on `license_findings` (nor on
  `kev_findings`), and `detection_method` is not one under another name.
- The state is a vocabulary composed by `core.outcomes.outcome_type`, and **the determinate
  value must not be the bare `ok`** — on a licence table `ok` reads as "this licence is fine",
  which is a compliance verdict this collector must never make and which AC 2 forbids in as many
  words. Name the determinate member for what it means: the licence was recognised and
  normalized. Declare no precedence until the policy that reduces these rows decides one.
- No compliance verdict of any kind. Whether a licence is allowed is `CPM-FR-18`'s policy, which
  is `CPM-SECURITY-S05`, and its seed is PRD Open Question 2.
- Time comes from the injected clock; every row carries the run's instant.
- `pixi` is the only runner; `pixi run ci` exits 0 at the end.

**Block If:**
- Satisfying AC 2's "routes to manual review" would require creating a workflow queue item.
  `CPM-AD-22` gives every queue item to one workflow application that does not exist yet, and
  `CPM-EP-APP` owns it. This story reads "routes to manual review" as *recording the row a
  review queue will select* — an `unknown` state with the raw value preserved — and records the
  queue itself as belonging to the application epic. If review finds that a story recording no
  queue item cannot satisfy AC 2, HALT rather than building a queue this architecture puts
  elsewhere.

**Never:**
- No compliance verdict, no allow list, no deny list, and no column named for one. PRD Appendix
  A.2 lists a policy result on this table; a collector may not compute a derived status
  (`CPM-AD-8`) and a policy pass writes only its own derived table (`CPM-AD-21`), so that column
  is not this story's to add and is recorded rather than smuggled in.
- No reading of another collector's evidence table. The licence is read from the source, not
  from the published-package snapshot that also happens to carry one.
- No new declared adapter. The monitored channels are already configuration
  (`CPM-CURRENCY-S04`); this collector reads the same declaration rather than inventing a
  second source of truth.
- No change to `core/collection.py`, `core/freshness.py`, `OutcomeState`, `identity`'s writers,
  or any shipped collector or policy.
- No `timezone.now()` anywhere.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| A recognised licence (AC 1) | a monitored channel states `MIT` for the package | one determinate row: the raw string verbatim, the normalized SPDX expression, the detection method, the channel and the source; ledger `succeeded` | No error |
| A licence needing normalization | the channel states `Apache 2.0` or `BSD-3` or `mit` | determinate row whose raw column holds the stated string unchanged and whose normalized column holds the SPDX identifier | Raw is never rewritten |
| A compound expression | the channel states `MIT OR Apache-2.0` | determinate row carrying the expression normalized, with the detection method saying it was an expression | Never split into two rows |
| An unrecognised licence (AC 2) | the channel states something the collector cannot recognise | one row carrying `unknown`, the raw value preserved, the normalized column blank, and a detail saying it needs review | Never a determinate row, never a permissive value |
| The source states no licence | the channel serves the package and states `license` as `null`, `""` or whitespace | one row carrying `unknown` whose raw column is blank and whose detail says the source stated none | Distinct detail, same state |
| The document carries no licence field at all | the `license` key is absent — renamed, nested, or the source's shape has changed | one row carrying `unknown` whose detail names the *absent field* rather than claiming the channel stated none | Distinct detail, same state; never an affirmative negative |
| A licence this product will not normalize but the database will hold | the channel states a licence across two lines, or carrying a tab | one row carrying `unknown`, the raw string preserved **verbatim** including the line break, and a detail saying why nothing was normalized | Never a failed run: the value is storable, and failing would cost every other channel its answer |
| A value no database will hold | the stated licence carries a NUL byte or a lone UTF-16 surrogate | refused where the value enters; a document error from `translate`, the base writes an `error` row and re-raises | Refused here rather than inside the driver, which is outside every guard |
| The package is absent from every channel | no monitored channel serves it | one row carrying `not_found` naming what was asked | The base's answer, on the record |
| Nothing declared | no monitored channels or platforms declared | the selection is empty, so a scheduled run records an empty selection rather than failing every package | The lesson `CPM-CURRENCY-S04` was patched for |
| Several channels state different licences | two monitored channels disagree | one row per channel, each naming its channel, never merged into one verdict | Disagreement is a fact to record |
| Raw value wider than its column | any stated value exceeding its column | refused where the value enters, never truncated | A truncated licence is a different licence |
| Unreadable document | body over the bound, not JSON, wrong shape, or a field of the wrong type | a document error from `translate`; the base writes an `error` row and re-raises | Refused rather than partly read |
| Adapter or channel fails | the source raises a transport failure | `error` row, ledger `failed` | Base path |
| Spent allowance | limiter refuses | `error` row, ledger `failed` | Base path |
| Sentinel asked for the determinate value | `sentinel_evidence` asked for it | `CollectorConfigurationError` | Refused at the call |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/collectors/conda_package.py` -- the
  closest template and the source of the licence: it already reads a monitored channel's
  per-package document, already reads `CPM_MONITORED_CHANNELS` / `CPM_MONITORED_PLATFORMS`, and
  already handles one row per channel with a bounded channel count and its own soft-limit
  arithmetic. Read it and `CPM-CURRENCY-S04`'s Review Triage Log first. **Do not read its
  evidence table**; read the same source it reads.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/vulnerability.py` and
  `collectors/kev.py` -- the two security siblings. Their Review Triage Logs carry the findings
  not to repeat, and between them they establish: compose the vocabulary rather than borrow the
  determinate value, offer every selectable package rather than a filtered subset, guard every
  stored value's width and control characters, and never let a row claim what the run did not
  establish.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/outcomes.py` -- where the two
  security vocabularies live and why neither declares a precedence. Add this story's beside them.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` -- the seven
  evidence models are the template. Add `LicenseFinding` / `license_findings`: `package`
  (`PROTECT`), `source`, `state`, `channel`, `raw_license`, `normalized_license`,
  `detection_method`, `detail`, `trace_id`; a read index on `(package, -observed_at)`; a
  `CheckConstraint` making the normalized expression and the detection method present exactly on
  a determinate row **while permitting the raw value on any row** — the raw string is what makes
  an `unknown` row reviewable and must not be constrained away; **no unique constraint**
  (`CPM-AD-7`, and `CPM-AD-2` for why re-observation always inserts). AD-2 is the
  insert-only rule — re-observation always inserts and the manager exposes no `update()` or
  `delete()`; the sentence that actually forbids a *suppressing* unique constraint is AD-7's.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/` -- `0008` is the
  newest; add `0009_license_findings.py`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py`, `apps.py`,
  `src/config/settings/base.py` -- the task, the roster of eight, and the schedule entry
  reconciled against the declared cadence (`CPM-NFR-2` puts security at daily), offset from the
  other security sweeps as `CPM-SECURITY-S02` was.
- `tests/collectors.py`, `tests/unit/django_apps/test_conda_package.py`,
  `tests/integration/django_apps/test_conda_package.py` -- the fixtures and module shapes to
  mirror for a multi-channel collector.
- `tests/unit/test_model_registry.py`, `tests/integration/startup/test_stage_two_collector_registry.py`,
  `tests/unit/django_apps/test_collector_base_audit.py`, `tests/unit/django_apps/test_sweep.py`,
  `tests/unit/startup/test_no_softening.py`, `tests/unit/test_settings.py` -- the rosters and
  audits an eighth collector reaches. Several carry collector counts in prose and have drifted
  before; update every one rather than the one that fails.
- `docs/deployment.md` -- the collector sections are the template; this one must say what
  normalization does and does not do, and that an unrecognised licence is a review item rather
  than a problem with the package.

## Tasks & Acceptance

**Execution:**
- `collectors/models.py`, `collectors/migrations/0009_license_findings.py` -- the table, its read
  index and its constraint.
- `collectors/outcomes.py` -- the composed licence vocabulary, determinate member named for what
  a determinate row means, no precedence declared.
- `collectors/spdx.py` -- new, or a section of the collector if it stays small: the recognised
  identifiers and the normalization, as **data** rather than a chain of branches, so what the
  collector recognises is a list a reviewer can read and extend. It recognises common spellings
  and compound expressions, and refuses everything else rather than guessing.
- `collectors/license.py` -- new. The declarations, the pure functions (a channel document to a
  stated licence, and a stated licence to a normalized expression plus a detection method), and
  `LicenseCollector` with its hooks and `selectable_packages`.
- `collectors/tasks.py`, `collectors/apps.py`, `config/settings/base.py` -- the task, the roster
  of eight, and the schedule entry.
- `tests/unit/django_apps/test_license.py` -- new: every matrix row reachable without a
  database, every normalization case and every refusal, and the module's own source sweeps.
- `tests/integration/django_apps/test_license.py` -- new: every matrix row that needs a run,
  including AC 1's two columns side by side, AC 2's unrecognised licence with its raw value
  preserved, several channels disagreeing, the constraint refused by the database,
  re-observation inserting, the task, and a dispatch case.
- The rosters, audits and `docs/deployment.md`.

**Acceptance Criteria:**
- Given a channel stating a licence the collector recognises, when it runs, then one row holds
  the stated string unchanged and the SPDX expression beside it, with the detection method named.
- Given a channel stating a licence the collector cannot recognise, when it runs, then the row
  carries `unknown`, the normalized column is blank, and the raw value is preserved exactly.
- Given two monitored channels stating different licences, when it runs, then two rows exist,
  each naming its channel, and no row merges them.
- Given a row that is not determinate, when a normalized expression is written to it, then the
  database refuses the row.
- Given the repository, when `pixi run ci` runs, then it exits 0 with coverage above the floor.

## Spec Change Log

### 2026-09-07 — Recorded before implementation

**PRD Appendix A.2 lists a policy result on this table and this story does not add it.** A
collector may not compute a derived status (`CPM-AD-8`), and a policy pass writes only its own
per-domain derived table (`CPM-AD-21`), so no component this architecture permits could write
that column. `CPM-SECURITY-S05` owns the licence policy and will write its own derived table.
The appendix predates those decisions; the column is recorded here as not-taken rather than
smuggled onto an evidence row.

**Where the licence is read from.** A conda package's licence is stated by the artifact metadata
a channel serves, which `CPM-CURRENCY-S04` already reads for a different fact. `CPM-AD-7` forbids
reading that collector's evidence table, so this collector reads the same *source* independently
and records its own row. That is a second call to one host rather than a shared read, and it is
the shape `CPM-AD-7` intends.

### 2026-09-07 — Recorded at review

**The recognised table no longer resolves a version with no disposition, and that narrows what
this story delivers.** `GPL-2.0`, `GPLv2`, `GPL v2`, `GPL-3.0`, `GPLv3`, `GPL v3`, `LGPL-2.1`,
`LGPLv2.1`, `LGPL-3.0`, `LGPLv3`, `AGPL-3.0` and `AGPLv3` each produced a *determinate* row
naming the `-only` variant, which is the guess the module's own docstring uses as its worked
example of an intolerable one — on the single licence family where the only/or-later split is
legally load-bearing, and permanently, in an append-only table `CPM-SECURITY-S05`'s policy will
read. The direction was also inverted: bare `GPL-2.0` resolved confidently while the current,
unambiguous `GPL-2.0-or-later` was refused as unreadable. They are now review items, and the ten
current identifiers (`GPL-2.0-only`, `GPL-2.0-or-later`, and the same pair for `GPL-3.0`,
`LGPL-2.1`, `LGPL-3.0` and `AGPL-3.0`) are recognised under their own names. `psf` and
`python software foundation license` are removed for the neighbouring reason — either could name
`Python-2.0` or `PSF-2.0`, and both identifiers are now recognised exactly — and `freebsd` is
removed because the FreeBSD licence is `BSD-2-Clause-Views` and carries a clause `BSD-2-Clause`
does not.

**Operators are recognised in upper case only, and one expression joins its operands with one
operator.** `MIT and Apache-2.0` normalized determinately to `MIT AND Apache-2.0`; a conda
`license` field is prose at least as often as an expression, and prose "A and B" usually offers a
choice — SPDX `OR` — while SPDX `AND` binds both sets of obligations at once. And
`MIT OR Apache-2.0 AND BSD-3-Clause` normalized cleanly while `(MIT OR Apache-2.0) AND
BSD-3-Clause` was refused for needing a precedence this product does not implement, which is the
same ambiguity treated two ways. Both are now review items.

**`CPM-AD-5`'s "enumerated in `core`" is diverged from, and this is the third time.** AD-5's own
text says the per-status determinate values are enumerated in `core` and names **`LicenseOutcome`**
as its worked example — so the rule's example is now in the wrong place. This story declares the
vocabulary in `collectors/outcomes.py`, following `VulnerabilityOutcome` (`CPM-SECURITY-S01`) and
`KevOutcome` (`CPM-SECURITY-S02`), which diverged the same way and recorded nothing. The factory
that composes it (`core.outcomes.outcome_type`) is `core`'s, the sentinels are verified by
`core`'s own `verify_sentinels`, and `tests/unit/django_apps/test_license.py` asserts both — so
the risk is nil and the divergence is a *location* rather than a rule. It is recorded because
three unrecorded divergences from one decision is how a decision stops being read at all. The
spine's AD-5 text and its example should be corrected to name `collectors/outcomes.py`; that is
an architecture edit rather than this story's.

**`CPM-SM-2`'s confidence element is not taken on this table.** SM-2 measures this product on
every licence finding "carrying source, timestamp and confidence". `source` and `observed_at`
carry the first two. There is **no confidence column** on `license_findings`, and
`detection_method` is not one under another name: it says *how* an expression was established —
identifier, recognised spelling, expression — which is a description of a step rather than a
degree of belief in a match. A confidence value here would have to be a number this collector
invented, and the one place this product has a real one (`collectors/match_confidence.py`) is
about matching a package to an advisory, which has no analogue in reading a field a channel
states. `kev_findings` has no confidence column either, for the same reason and without a record;
this is the record for both. If SM-2 is to be satisfied literally, the element belongs with the
policy that reduces these rows (`CPM-SECURITY-S05`) rather than with the collector that writes
them.

## Review Triage Log

### 2026-09-07 — Four review layers

**Fixed (behaviour), each with a case that fails without it:**

1. **The recognised table guessed dispositions the module documents itself as refusing.** Twelve
   GNU spellings naming a version and no `-only`/`-or-later` produced determinate rows; `psf` and
   `python software foundation license` could each name two licences; `freebsd` recorded a
   licence with one fewer obligation than the one stated. All removed; ten current GNU
   identifiers plus `Python-2.0` and `PSF-2.0` added. `AMBIGUOUS_LICENSES` in the unit module now
   holds spellings that *state a version*, so its guard assertion can fail.
2. **A lone surrogate defeated every guard and crashed the insert outside it.**
   `_require_storable` asked `[\x00-\x1f\x7f-\x9f]`; `'\ud800'` is none of those, decodes out of
   JSON, and reached `_write_evidence` outside the `try` wrapping `translate` — no row at all,
   daily. It now asks whether the value *encodes* as UTF-8, which is the question the driver
   asks.
3. **A newline or a tab misrouted a readable licence to the unreadable-document path.** Split
   into unstorable (NUL, non-UTF-8-encodable — still `LicenseDocumentError`) and
   storable-but-not-normalizable (`\n`, `\t`, `\r`, other C0/C1 — `unknown`, raw preserved
   verbatim, `UNNORMALIZABLE_LICENSE_DETAIL`). The line-break claim in `_WHITESPACE`'s docstring
   is corrected to match: a line break makes the value a review item and never reaches the
   collapse.
4. **`_channel_instead`'s reasons were neither cleaned nor bounded.** All five now go through
   `_safe_detail`, as does `channel_license`'s unrecognised-token list; `_safe_detail` also
   substitutes surrogates.
5. **`LICENSE_FIELD`'s value was unpinned** — both tiers built fixtures from the constant, so
   renaming it kept the suite green. Now asserted against its literal, with one fixture built
   from a hard-coded `"license"` key.
6. **An absent `license` key recorded the affirmative claim that the channel stated none.**
   Present-and-null and absent are now distinct `detail`s under one `unknown` state.
7. **Lower-case `and`/`or` were read as SPDX operators**, and **mixed `AND`/`OR` in one flat
   expression normalized determinately** while the parenthesised form was refused. Both are now
   review items.

**Recorded rather than fixed:** four `deferred` entries — the uncharged bounded calls and the
uncached channels (both inherited from `CPM-CURRENCY-S04`, restated here so a sweep triaging by
location finds this module's copy), the selection/run-time disagreement about "declared", and the
over-wide raw licence's evidence-free loop. See the frontmatter and the Design Notes.

**Test gaps closed without a behaviour change:** the plural sentinel hook's `_safe_detail`; the
second channel's request headers (`sent_headers[1]`); both `except Exception` clauses against a
non-`TransportError` break; the `304` branch's distinguishing sentence; a unit-tier selection
case asserting `.model`, no `WHERE` and `order_by == ("pk",)`; `trace_id` on both row shapes;
`inapplicability`'s three resets; and a cross-collector reconciliation of `CHANNELS_SETTING`,
`MAX_MONITORED_CHANNELS`, `_SEGMENT.pattern` and `ANACONDA_API_HOST` against
`collectors/conda_package.py` — restating them is right under `CPM-AD-7`, but nothing compared
them, and a rename there would have made this collector offer zero packages for ever.

**Corrected prose:** three docstrings claiming guarantees the code does not have
(`selectable_packages`, `sentinel_evidence`, `_require_shapeable`); the `CPM-AD-2`/`CPM-AD-7` and
`CPM-AD-7`/`CPM-AD-27` citations; `CPM-SM-2`'s confidence element recorded as not-taken; the
`CPM-AD-5` location divergence recorded; and `docs/deployment.md`'s rate paragraph, which stated
three wrong numbers to an operator sizing a limit.

## Design Notes

**Why the determinate value is composed rather than `ok`.** On a licence table `ok` reads as
"this licence is fine" — a compliance verdict AC 2 forbids this collector from making and
`CPM-FR-18` gives to a policy that does not exist yet. The two security siblings were both
corrected on exactly this point; here it is made by construction. The determinate member says
the licence was recognised and normalized, which is what the row actually establishes.

**Why the raw value is preserved on every row, including failures.** AC 1 exists so a reviewer
can "see what normalization did before I trust its result", which is only possible if both
columns survive. It matters most on the rows that failed: an `unknown` row carrying the raw
string is a review item somebody can act on, while an `unknown` row carrying nothing is an
absence of information. The constraint is therefore deliberately asymmetric — it requires the
normalized expression and the detection method on determinate rows only, and permits the raw
value everywhere.

**Why normalization is data rather than branches.** What this collector recognises is a
judgement that will be revised, and `CPM-AD-8`'s posture throughout this product is that rule
sets are data. A reviewer extending the recognised set should be reading a list, not tracing
control flow — and the set is also what a later licence policy will be written against.

**Why "the database will not hold this" and "this product will not read this" are two different
refusals.** A value is refused outright — the run fails, the base writes an `error` row — only
where PostgreSQL's driver refuses it from inside itself: a NUL byte, a lone UTF-16 surrogate, and
a value wider than its column. Everything else a channel can state is *recorded*. A licence
carrying a newline or a tab is ordinary conda metadata and PostgreSQL stores it perfectly well,
so it is an `unknown` row with the raw string preserved verbatim and a `detail` saying why
nothing was normalized from it. The difference is not cosmetic: `translate` returns one sequence
for all channels, so a refusal for channel one writes `error` rows for every *other* channel
without asking them and blanks the raw column on all of them — losing the string that caused it
precisely where a reviewer needs it — and repeats every day, because the observation window only
suppresses after a success. Moving the same value to channel two costs one row. A refusal whose
cost depends on which channel happened to state the value is not a rule.

**Why a raw licence over 512 characters is still a permanent failure, and what was not taken.**
This is the one refusal in the module that produces an unbreakable loop with *zero* reviewable
evidence: the run fails, every row carries `raw_license=""`, the window only suppresses after a
success, and it repeats daily. It is nevertheless left alone, because the alternative is worse in
the specific way this story exists to prevent: a truncated licence is a *different licence*, the
matrix says so in as many words, and this table is append-only. The alternative **not taken** is a
truncated raw value plus a `detail` naming the true length — which would stay reviewable without
claiming a licence, and is genuinely better than the loop. It is not taken here because it needs
a column that can say "this value is not the whole string": without one, a reader of
`raw_license` cannot tell a truncated value from a complete one, and a row that silently
misrepresents the source is exactly what AC 1 forbids. That is a table change and belongs with a
story that owns the schema. Recorded as a `deferred` entry rather than fixed.

## Verification

**Commands:**
- `pixi run test` -- expected: exit 0, the new unit module collected and passing.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: exit 0, no diagnostics.
- `pixi run test-integration` -- expected: exit 0.
- `pixi run manage makemigrations --check --dry-run` -- expected: "No changes detected".
- `pixi run ci` -- expected: exit 0; coverage >= 90%, the new modules at 100%.
- `pixi run gate-postgres` -- expected: exit 0; the constraint is enforced there.

**Manual checks (if no CLI):**
- `git diff --stat ce80d19` names the new collector, the migration, the roster updates and the
  settings entry, and shows no change to any shipped collector's behaviour and no read of
  another collector's evidence table.

## Dev Notes

**Satisfies:** `CPM-FR-13`

**Governed by:**

- `CPM-AD-5` — One status type, fixed values, one precedence order
- `CPM-AD-7` — Collectors share nothing but the log; evidence always inserts

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-SECURITY-S03]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-5]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-7]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-13]

## Dev Agent Record

### Agent Model Used

Claude Opus 5 (1M context) — `claude-opus-5[1m]`, via Claude Code.

### Debug Log References

- `pixi run test` — 5 270 passed with the rosters updated and no new module; 5 403 after
  `tests/unit/django_apps/test_license.py` and the roster parametrizations it extends.
- `pixi run test-integration` — 1 105 passed, 8 skipped. The only failure met during development
  was `test_the_registry_this_repository_ships_passes_condition_ten`, which is the roster case an
  eighth collector is expected to fail until it is added to the adopted list.
- `pixi run typecheck` — `Success: no issues found in 152 source files`.
- `pixi run lint` / `pixi run format` — clean; ten autofixes taken (import order, `SIM300`), three
  fixed by hand (`E501` in `collectors/apps.py` and the unit module's summary line, `PLR0913` on
  the integration `_collect` helper, which carries the same `noqa` the sibling module's does).
- `pixi run makemigrations --check --dry-run` — "No changes detected".
- `pixi run ci` — exit 0. 6 516 passed, 2 skipped; total coverage **99.08 %** against a 90 % floor,
  with `collectors/license.py` and `collectors/spdx.py` both at **100 %**. The first gate run left
  `license.py` at 97.98 % — five lines, being `_column_width`'s "declares no `max_length`" refusal
  and `source_for`'s `Package.DoesNotExist` re-raise — and a case was added for each, on the terms
  `tests/unit/django_apps/test_kev.py` and `tests/integration/django_apps/test_conda_package.py`
  cover the same two shapes.
- `pixi run gate-postgres` — exit 0: 6 516 passed, 2 skipped against a throwaway `postgres:17`, so
  all three `license_findings` constraints are enforced by a real backend and not only by SQLite.

**Note on task names:** this repository's pixi tasks are `format` and `typecheck`, not the
`fmt`/`check` the story's Verification block names. The block's intent was run under the real
names.

### Completion Notes List

**The determinate value is `normalized`.** `collectors/outcomes.py` composes `LicenseOutcome`
beside the two security siblings and argues the choice where they argue theirs: on a licence
table `ok` reads as "this licence is fine", which is the compliance verdict AC 2 forbids and
which `core`'s single precedence order would rank best of five. No precedence is declared, so
`core.outcomes.aggregate` refuses `normalized` outright until `CPM-SECURITY-S05` decides.

**Normalization is data.** `collectors/spdx.py` is a new leaf module holding
`RECOGNISED_LICENSES` — a readable table of `(SPDX identifier, other spellings)` — a derived
folded lookup, the two operators (`AND`, `OR`), and `normalize`, which is one small rule over
that table. It refuses rather than guesses: the bare family names (`BSD`, `GPL`, `LGPL`,
`Apache`, `Other`, `Public Domain`, `See LICENSE file`), parenthesised grouping, `WITH`, and
multi-token operands inside an expression all reach a reviewer intact. `DetectionMethod` lives
there too, as a plain `TextChoices` on `collectors/match_confidence.py`'s terms — a leaf both
`collectors/models.py` and `collectors/license.py` can import without closing a cycle.

**The constraint is asymmetric and the asymmetry is tested from both sides.**
`license_facts_present_exactly_when_normalized` requires the expression and the method on a
determinate row and forbids them elsewhere, and says nothing about `raw_license`. Two integration
cases assert the refusals and one asserts the *permission* — the raw string surviving on
`unknown`, `error` and `not_found` rows — because that permission is what AC 1 actually depends
on.

**Two further constraints, both taken from precedent rather than invented.**
`license_applies_to_every_package` refuses `not_applicable` outright, exactly as both security
siblings' tables do. `license_names_the_channel_it_is_about` requires the channel on every row
including sentinels, exactly as `conda_package_snapshots` requires its pair — because two
channels stating different licences are two facts and a row that could not name its channel
would have merged them.

**`sentinel_evidence_rows` is overridden, and that is the `CPM-CURRENCY-S04` defect not
repeated.** The base's `not_found` branch writes without reaching `translate`, so a package
absent from the first channel and licensed on the second would otherwise record nothing about
the second. On `not_found` the remaining channels are asked; on `error` they are not, because the
run is already `failed` and the reason may be a refused allowance. Both are asserted, at the unit
tier and end to end.

**No adapter, and no second declaration.** `CPM_MONITORED_CHANNELS` is the declaration
`CPM-CURRENCY-S04` established and this collector reads it. Its name and the segment grammar are
**restated** in `collectors/license.py` rather than imported, because `CPM-AD-7` forbids one
collector importing another; a unit case reconciles the two spellings.
`CPM_MONITORED_PLATFORMS` is deliberately not read — a licence is not per platform — and a case
sweeps the module's own string constants to keep it that way.

**No read of another collector's evidence table.** The licence is stated by the same
`api.anaconda.org` document `collectors/conda_package.py` reads, which is exactly the shortcut a
reviewer would expect; a source sweep asserts `CondaPackageSnapshot` and `conda_package_snapshots`
appear nowhere in the module. `MODULES_PERMITTED_TO_READ_ANOTHER_COLLECTORS_EVIDENCE` is
unchanged and still holds one entry.

**Widths are measured rather than matched.** `normalized_license` is four times `raw_license`,
because normalization expands (`bsd-3` → `BSD-3-Clause`) and a column merely equal to the raw one
would leave a band of storable raw values whose expression could never be recorded — the
`_FEEDSTOCK_NAME_LENGTH` trap. A unit case asserts the *relation* against the shipped table, so a
spelling added with a longer identifier fails there rather than at an insert.

**Schedule.** `cpm-sweep-license`, daily, with a two-hour `countdown` — deliberately not the KEV
entry's hour, because two entries sharing a phase fire together and buy nothing. The reason is
not KEV's: nothing here reads another collector, and what the offset buys is that the two sweeps
reading `api.anaconda.org` do not spend their separate allowances at one instant.
`tests/unit/test_settings.py`'s phase case was widened from "the one entry carrying a phase" to
"exactly these two, and their offsets differ".

**Every roster and audit that carries a collector count was updated**, not only the ones that
failed: `tests/unit/test_model_registry.py`, `tests/integration/startup/test_stage_two_collector_registry.py`,
`tests/unit/django_apps/test_collector_base_audit.py`, `tests/unit/django_apps/test_sweep.py`,
`tests/unit/startup/test_no_softening.py` and `tests/unit/test_settings.py`. Four of the six
passed unchanged and were updated anyway.

**Where the spec was interpreted rather than followed literally:**

1. **The matrix's "package is absent from every channel → *one* row carrying `not_found`" row.**
   Taken literally with several channels declared, that would mean one row standing for all of
   them — which contradicts the disagreement row ("one row per channel, each naming its channel,
   never merged"), contradicts the channel constraint, and would reinstate the exact defect
   `CPM-CURRENCY-S04`'s Review Triage Log records as `[high]`. Read as *one row per channel it was
   about*, which is literally one row for the single-channel case the matrix describes. Both are
   tested: `test_one_monitored_channel_that_does_not_serve_the_package_is_exactly_one_row` and
   `test_a_package_absent_from_every_channel_is_one_row_per_channel_naming_what_was_asked`.
2. **AC 2's "routes to manual review".** Read, as the Block If directs, as *recording the row a
   review queue will select* — an `unknown` state with the raw value preserved and a `detail`
   saying it needs review. No queue item is created and none is designed; the queue belongs to
   `CPM-EP-APP` (`CPM-AD-22`). The Block If's HALT condition was not reached.
3. **The Code Map names one `CheckConstraint`; the table carries three.** The extra two are the
   applicability refusal both security siblings' tables carry and the channel-presence rule
   `conda_package_snapshots` carries. Neither adds a fact; both are precedent applied to a table
   with the same shape, and both are argued in the model docstring and the migration header.
4. **`collectors/spdx.py` holds `DetectionMethod` as well as the normalization table.** The Code
   Map describes the module as "the recognised identifiers and the normalization"; the vocabulary
   is there because `collectors/models.py` needs it for a column's `choices` and any other home
   closes an import cycle — the reason `collectors/match_confidence.py` exists.
5. **Cache posture differs from the two security siblings.** They declare `NO_CACHE`; this
   collector declares a seven-day conditional cache over the base's one call, on the grounds that
   a licence is a statement in the metadata of an already-published build and the request is
   *conditional* — what is replayed is a body the channel itself says is unchanged. Argued in
   `LICENSE_CACHE_TTL` and asserted in the unit and integration tiers.

### File List

**New:**

- `src/django_apps/conda_package_supply_chain_monitor/collectors/spdx.py`
- `src/django_apps/conda_package_supply_chain_monitor/collectors/license.py`
- `src/django_apps/conda_package_supply_chain_monitor/collectors/migrations/0009_license_findings.py`
- `tests/unit/django_apps/test_license.py`
- `tests/integration/django_apps/test_license.py`

**Changed:**

- `src/django_apps/conda_package_supply_chain_monitor/collectors/outcomes.py` — `LicenseOutcome`,
  `NORMALIZED_MEMBER`, `NORMALIZED` and the four sentinel names; docstring now argues three
  vocabularies rather than two.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/models.py` — `LicenseFinding`,
  the three constraint names, the read index, three column widths; module docstring now eight
  tables.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py` —
  `COLLECT_LICENSE_TASK_NAME`, `collect_license`.
- `src/django_apps/conda_package_supply_chain_monitor/collectors/apps.py` — `LicenseCollector` in
  the adopted roster.
- `src/config/settings/base.py` — the `cpm-sweep-license` beat entry and its offset.
- `docs/deployment.md` — the licence-collector section, and the sweep section's counts, cadence
  table, offered-packages table and phase paragraph.
- `tests/unit/test_model_registry.py`
- `tests/unit/test_settings.py`
- `tests/unit/django_apps/test_sweep.py`
- `tests/unit/django_apps/test_collector_base_audit.py`
- `tests/unit/startup/test_no_softening.py`
- `tests/integration/startup/test_stage_two_collector_registry.py`

## Auto Run Result

**Outcome:** done, with a follow-up review recommended.

**Review loop:** one iteration. Four layers ran in parallel against the staged
implementation -- a blind defect hunter that never read the spec, an edge-case hunter working
from the matrix, a verification-gap auditor asking which mutations survive the suite, and an
intent-alignment auditor checking both the code against the spec and the spec against the
architecture. Fifteen findings were triaged into six must-fix, six should-fix and four
record-only; all were addressed in one fix pass.

**The finding three reviewers reached independently.** `RECOGNISED_LICENSES` mapped twelve GNU
spellings -- `GPL-2.0`, `GPLv2`, `LGPL-2.1` and their siblings -- to a `-only` identifier. None
of those spellings states an only/or-later disposition, which is exactly why SPDX deprecated the
bare identifiers and split them. The module's own docstring names "`GPL` into `GPL-3.0-only`" as
its worked example of an intolerable guess. Worse, the direction was inverted: the ambiguous
spelling resolved confidently while the current unambiguous `GPL-2.0-or-later` was refused as
unreadable. Because a recognised spelling yields a *determinate* row, the one licence family
where the disposition is legally load-bearing bypassed AC 2's review routing entirely, into an
append-only table `CPM-SECURITY-S05`'s policy will be written against. The twelve aliases were
removed and the ten current identifiers added; `psf` and `python software foundation license`
went the same way for the same reason. The test that should have caught it asserted
`family.casefold() not in SPELLINGS` over seven bare family names that were trivially absent,
so it could not fail; `AMBIGUOUS_LICENSES` now carries the version-stating spellings.

**The two defects that would have produced runs with no evidence at all.** A lone surrogate
survives `json.loads`, is not a control character, and is one character wide, so it passed every
guard and reached PostgreSQL, which refuses it from inside the driver -- several frames past the
`try` the base wraps `translate` in. No row at all, repeating daily. `_require_storable` now
tests UTF-8 encodability rather than a character class, which cannot be outrun the same way.
Separately, `_channel_instead` interpolated third-party exception messages into `detail` without
cleaning, so one bad byte in a transport error would have discarded every channel's row from
inside `bulk_create` on the path that exists precisely to prevent that.

**A readable licence was being treated as an unreadable document.** `\n` and `\t` were refused
as control characters on a rationale that is true only of NUL. A multi-line licence string --
ordinary in conda metadata -- made the run fail, wrote `error` rows for every other channel
without asking them, and stored an empty raw column, so the string that caused it was nowhere on
the record. That is AC 1's premise failing exactly where a reviewer needs it. Storability and
normalizability are now separate: NUL and non-encodable values are still refused where they
enter, and anything storable this product will not normalize is a review item with the raw value
verbatim.

**Two places where a source change would have gone silent.** An absent `license` key was
indistinguishable from an explicit null, so a field rename upstream would have recorded "this
channel states no license at all" for every package on every channel, permanently, with nothing
failing. The two cases now carry distinct details. And `LICENSE_FIELD` was never pinned -- both
test tiers built their fixtures from the constant, so renaming it kept the suite green.

**Normalization stopped reading prose as SPDX.** Lowercase `and`/`or` were folded to operators,
so `MIT and Apache-2.0` became a determinate claim that both licences' obligations bind
simultaneously -- when English prose usually means the opposite. SPDX mandates uppercase
operators; lowercase is now a review item. Mixed `AND`/`OR` in one flat expression was accepted
while parentheses were refused for a precedence rationale that applies equally to both; it is
now refused for the same stated reason.

**Recorded rather than fixed.** The declared allowance charges one call while up to four are
issued, so a thirty-per-minute courtesy bound permits about a hundred and twenty. This is
inherited verbatim from `CPM-CURRENCY-S04` and is already a deferred defect there; a second
`deferred` entry now names this location so a sweep triaging by location cannot fix one and miss
the other. The same applies to channels after the first sending no validator and populating no
cache, to `selectable_packages` and `monitored_channels` genuinely disagreeing about "declared",
and to a raw licence over 512 characters producing a permanent daily failure with nothing
reviewable recorded.

**Spec corrections.** `CPM-AD-2` was cited for the absent unique constraint; the sentence that
actually prohibits one is `CPM-AD-7`'s. `CPM-AD-7` was cited for the `_write_evidence` seam,
which is `CPM-AD-27`'s. A Spec Change Log entry now records that `LicenseOutcome` is declared in
`collectors/outcomes.py` while `CPM-AD-5`'s text places per-status vocabularies in `core` and
names this very class as its example -- the third such divergence, following the two security
siblings. `CPM-SM-2`'s confidence element is recorded as not-taken with its reason rather than
mapped onto `detection_method`.

**Why a follow-up review is recommended.** The disposition defect was a data-table entry that
three separate reviewers had to reason about legal semantics to catch, and the recognised set
will grow. A later sweep should re-read `RECOGNISED_LICENSES` against the rule the module states
rather than against its own previous contents.

**Verification:** `pixi run ci` exit 0 (6560 passed, 2 skipped; coverage 99.08%, `license.py`
and `spdx.py` both 100%); `pixi run test-integration` exit 0 (1111 passed, 8 skipped);
`pixi run gate-postgres` exit 0 against `postgres:17`; `makemigrations --check --dry-run`
reports no changes.
