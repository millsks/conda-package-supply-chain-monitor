---
title: 'CPM-IDENTITY-S03: Confidence gates what the system will claim'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '31ac47d45893409b2bace87d94ac5b211d824291'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-evidence-s07-policy-run-writer-rollup.md
warnings: []
deferred:
  - summary: >-
      A wrapper that merely delegates to the gate -- `def currency_gate(v, *, confidence): return
      gated_status(v, confidence=confidence)` -- is forbidden in prose and caught by nothing.
    evidence: |-
      The story's `Never` list says the gate may not be re-exported or wrapped, because a wrapper is
      a second name for "what may be claimed" and the next reader has two doors to choose between.
      The detector deliberately does not catch it: a delegating wrapper contains no comparison and
      selects no status, so every shape the audit recognises is absent, and a detector broad enough
      to flag it would flag every legitimate caller including `core/rollup.py`. The honest bound is
      that this audit catches the *accident* -- a pass that reimplements the rule -- and not a
      deliberate indirection. Closing it needs a different mechanism (an allowlist of modules
      permitted to import `core.confidence` at all, reconciled the way the exemption record is), and
      that is a decision about the whole audit family rather than this one.
    location: >-
      tests/unit/django_apps/test_confidence_gate_audit.py
    severity: medium
  - summary: >-
      `tests/source_scan.parse` is uncached and this is now the sixth audit module to sweep the
      whole tree, so every audit re-parses every file.
    evidence: |-
      `project_files` is `@cache`d but `parse` is not, and each audit walks `REPO_ROOT` or
      `SRC_ROOT` independently -- roughly two hundred files parsed per sweep, six times over. The
      suite is fast today (this module runs in under two seconds) so nothing is wrong yet, and the
      trees are read-only, which is what would make caching safe. It is a change to shared test
      infrastructure that every audit depends on, so it belongs to whoever next touches
      `tests/source_scan.py` deliberately rather than to a story that happens to add the sixth
      caller.
    location: >-
      tests/source_scan.py -- parse
    severity: low
---

<intent-contract>

## Intent

**Problem:** The gate itself already exists. `CPM-EVIDENCE-S07` built `core/confidence.py` —
`gated_status` and `require_known_confidence` — wired it into the one rollup writer, and unit-tested
all three confidences; it recorded the hand-off in its own triage log, saying that whoever picked
this story up "should find them already in `core` and call them; a second implementation is the one
thing `CPM-AD-4` forbids outright." What does **not** exist is the thing that keeps that true. The
gate is three lines in one file, and nothing stops the ninth policy pass from writing
`if confidence == "unmapped": return "unknown"` inline. That is risk `R-08`, and
`IDENTITY.03-AUDIT-001` is the test that closes it.

**Approach:** Ship the audit, and nothing else. An AST sweep over the repository that fails when any
module other than `core/confidence.py` implements the gate — comparing a confidence against
`unmapped` to select a status, or declaring a table from confidence values to outcome values — with
its own detector-fitness cases, because there are no policy passes yet and a sweep over today's tree
would certify nothing.

## Boundaries & Constraints

**Always:**

- **Call the existing gate; never write a second one.** `core.confidence.gated_status` and
  `require_known_confidence` are `CPM-AD-4`'s one implementation. This story adds no gating logic.
- The audit is an **AST sweep**, never a text search. Prose about the prohibition — this spec, the
  audit's own docstring, `CPM-AD-4`'s text quoted in a comment — must not itself register as an
  offence, which is exactly why `test_single_ordering_audit.py` reasons in AST and says so.
- The one exempt file is located from **`confidence.__file__`**, never a hand-built path, and a
  `None` there is a hard failure rather than a silently empty exemption.
- The audit carries **its own detector-fitness cases** as synthetic source parsed in memory. A
  fixture module on disk would be swept by every other audit in the tree and would need its own
  exemption everywhere.
- The audit carries an **anti-vacuity guard**: the scan reaches `core/confidence.py` by name, and
  that file does declare the gate. `registered_passes()` is empty in production, so without this the
  whole sweep passes by finding nothing and certifies nothing.
- Any module that legitimately compares a confidence for a reason **other** than gating an outward
  claim is a **recorded exemption**, named with the reason — not a hole in the detector.
- `pixi` is the only runner, and `git add -A` before `pixi run ci`, or the gate will not see the new
  file.

**Block If:**

- Closing `IDENTITY.03-AUDIT-001` appears to require changing `core/confidence.py`'s behaviour, or
  adding a gated status column to `PackageHealth`. The first would be re-opening a settled decision;
  the second is forbidden by `core/rollup.py`'s own rule against inventing a domain column before a
  policy epic runs.

**Never:**

- Do **not** re-implement, re-export, wrap or "improve" the gate. Do not restate the three
  confidence values anywhere; `core/confidence.py` argues that restating them in `core` would itself
  be the defect.
- Do **not** add a domain status column to `PackageHealth` to make the gate "real". Use the
  synthetic rollup `tests/passes.py` already provides.
- Do **not** add a `policies` app or a `PolicyPass` subclass. This story proves a rule about passes
  that do not exist yet; that is what the fitness cases are for.
- Do **not** duplicate the coverage `tests/unit/django_apps/test_confidence.py` and
  `test_rollup_row.py` already carry — the three confidences, the never-improves-a-sentinel case,
  and the gated default are all pinned.
- Do **not** add a dependency, a `pragma`, a coverage omit, a `pytest.skip`, or `databases=`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| The repository as it stands | every first-party module swept | no offence is reported | No error expected |
| The declaring module is reached | the sweep's file list | `core/confidence.py` is in it, by name rather than by count | No error expected |
| The declaring module declares the gate | `core/confidence.py` parsed | the detector fires on it — proving the detector works at all | No error expected |
| A second gate, member spelling | synthetic source comparing against `IdentityConfidence.UNMAPPED` and returning a status | reported as an offence, naming the file and line | No error expected |
| A second gate, literal spelling | synthetic source comparing against `"unmapped"` and returning a status | reported | No error expected |
| A second gate, aliased import | synthetic source importing the module and reaching the member through it | reported — the alias does not evade the detector | No error expected |
| A confidence-to-outcome table | synthetic module-level `dict` from confidence values to outcome values | reported | No error expected |
| Calling the gate is not an offence | synthetic source importing and calling `gated_status` | not reported | No error expected |
| Comparing a confidence for another reason | synthetic source comparing a confidence and returning something that is not a status | not reported, or reported and recorded — the detector's own decision, asserted either way | No error expected |
| The recorded exemptions still describe real code | each recorded entry | the file exists and still contains the form the entry names | No error expected |
| `confidence.__file__` is absent | the module has no `__file__` | the audit fails loudly rather than exempting nothing | `RuntimeError` |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/confidence.py` — **the gate, already
  built.** `:77` `GATED_VALUE`, `:84` `_KNOWN_CONFIDENCES`, `:87` `ConfidenceError`, `:97`
  `require_known_confidence`, `:129` `gated_status`. `:26-33` states the `inventory-derived` rule
  (label recorded, value not degraded) and `:36-42` argues why the three values are imported from
  `identity` rather than restated. **Read-only in this story.**
- `core/rollup.py:349` and `:367` — the gate's one caller, inside `_replacement`. `:358-366` routes
  the field *default* through the gate too, so an `unmapped` package cannot read `ok` via a default
  nobody contributed. **Read-only, and a recorded exemption candidate:** it compares nothing, it
  calls.
- `identity/services.py` `_require_confidence_is_earned` — compares against
  `IdentityConfidence.UNMAPPED` and cites `CPM-AD-4`, but it is a *resolution-time* rule about what
  a resolver may claim, not a gate on an outward claim. A naive detector flags it. Decide: recorded
  exemption, or a detector precise enough not to fire.
- `tests/unit/django_apps/test_single_ordering_audit.py` — **the template.** Its shape: a module
  docstring stating the ban and why AST; `_DECLARING_SOURCE = outcomes.__file__` with a hard
  `RuntimeError` on `None`; synthetic sources parsed in memory rather than fixture files; detector
  helpers resolving aliased spellings; `static_statements` descending `if`/`try`/`with`/`for`/`class`
  but stopping at `def`; three test families — anti-vacuity, the ban parametrized per file with
  readable ids, and detector-fitness positives and negatives; and the declaring module filtered out
  of the parametrize list rather than skipped, because skips are banned.
- `tests/unit/django_apps/test_derived_status_writability_audit.py:199` `RECORDED_EXEMPTIONS` and
  `:211` `THE_ROLLUP_WRITER` — the exemption-table shape, counted per form, reconciled in both
  directions.
- `tests/unit/django_apps/test_pass_ownership_audit.py` — the "the sweep is empty today and that is
  the load-bearing problem" idiom, and how it measures its detectors against fixture passes.
- `tests/source_scan.py:44` `REPO_ROOT`, `:130` `project_files`, `:192` `parse`, `:219`
  `dotted_name`.
- `tests/unit/django_apps/test_confidence.py` and `test_rollup_row.py:131-212` — the existing
  coverage of ACs 1 and 2. **Read-only; do not duplicate.**

## Tasks & Acceptance

**Execution:**

- `tests/unit/django_apps/test_confidence_gate_audit.py` — new, and the whole of this story.
  `IDENTITY.03-AUDIT-001`: the AST sweep, the exemption table, the anti-vacuity guards and the
  detector-fitness cases.

**Acceptance Criteria:**

1. Given the repository as it stands, when the audit runs, then it reports no offence — and the
   assertion names the offending file and line when it does, rather than reporting a count.
2. Given the sweep's file list, when it is inspected, then `core/confidence.py` appears in it by
   name, and the detector fires on that file — so the audit is proven to be capable of finding what
   it looks for before it is trusted to have found nothing.
3. Given a synthetic module that re-implements the gate, when the detector runs over it, then it is
   reported — for the member spelling, the literal spelling, the aliased-import spelling, and a
   module-level confidence-to-outcome table.
4. Given a synthetic module that *calls* the gate, when the detector runs over it, then it is not
   reported.
5. Given each recorded exemption, when the audit runs, then the file it names still exists and still
   contains the form the entry describes — reconciled in both directions, so a stale exemption fails.

## Traceability

**Satisfies:** `CPM-FR-5` — confidence gates what automation may claim.

**Governed by:** `CPM-AD-4` — confidence gates every outward claim, by writing a value.

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `IDENTITY.03-AUDIT-001` (this story), `IDENTITY.03-UNIT-001` and
  `IDENTITY.03-UNIT-002` (both delivered by `CPM-EVIDENCE-S07` — see the Spec Change Log).
- Risk this story closes: `R-08` — "the confidence gate is re-implemented per policy: eight passes
  each copy it, and `unmapped` reads differently in two views." BUS, P=3 x I=2 = 6, which is at the
  threshold where the TEA handoff requires a passing test before the epic may be called done.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-IDENTITY-S03]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-4]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-5]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]
- [Source: _bmad-output/implementation-artifacts/stories/cpm-evidence-s07-policy-run-writer-rollup.md]

## Spec Change Log

### 2026-09-05 — Re-scoped to the audit, because the gate already shipped

**What changed.** The story's three acceptance criteria were replaced by five, all about the audit.
The epic's AC 1 (an `unmapped` package reports `unknown` for every gated status) and AC 2
(`inventory-derived` is labelled and not degraded) are **not** implemented here.

**Why.** `CPM-EVIDENCE-S07` built `core/confidence.py` — `gated_status`, `require_known_confidence`
and `GATED_VALUE` — two commits before this story's baseline, because `core/rollup.py` cannot
compose a row for an `unmapped` package without deciding what its statuses read. It pinned all
three confidences in `tests/unit/django_apps/test_confidence.py`, including the case that catches a
gate which *improves* a sentinel rather than only degrading one, and again at the composition site
in `test_rollup_row.py`. It recorded the hand-off in its own frontmatter rather than leaving it to
be rediscovered: whoever picked this story up "should find `gated_status` and
`require_known_confidence` already in `core` and call them; a second implementation is the one thing
`CPM-AD-4` forbids outright."

**The known-bad state this avoids.** Implementing the epic's AC 1 and AC 2 here would have produced
a second gate — which is exactly `R-08`, and exactly what `IDENTITY.03-AUDIT-001` exists to fail on.
The story would have created the defect it was written to prevent.

**KEEP.** `epics.md` still carries the original three criteria and is not amended: they remain the
right statement of what the *epic* must deliver, and all three are delivered — two by S07 and one
here. This log entry, not a rewritten epic, is where the division is recorded.

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 24: (high 9, medium 10, low 5)
- defer: 2: (high 0, medium 1, low 1)
- reject: 5: (high 0, medium 1, low 4)
- addressed_findings:
  - `[high]` `[patch]` **The detector missed most of the shapes a real policy pass would write, and
    three review layers proved it by running the detector rather than reading it.** Every one of
    these returned no finding: a `match`/`case` gate (never scanned — a `match_case` pattern is not
    an `ast.Compare`, so neither net saw it); the gate written from the trusted side
    (`if confidence in {VERIFIED, INVENTORY_DERIVED}: return verdict`, falling through to
    `unknown`); `!= VERIFIED`, which *is* the AC-2 violation because it degrades
    `inventory-derived`; a status from a composed per-domain outcome type such as
    `LicenceOutcome.UNKNOWN`, which is the vocabulary `core/outcomes.py` says every future pass will
    use; a confidence bound to a module-level name, which is what a developer writes after being
    told not to hard-code `"unmapped"`; and a package-then-attribute import, which had neither net.
    All are now caught, verified by an eleven-case probe run against the shipped detector.
  - `[high]` `[patch]` A status inside a returned container was not seen, though `PolicyPass.evaluate`
    returns `Mapping[str, str]` — so `return {"currency_status": UNKNOWN}` is the *normal* return
    shape for a pass and was the single most likely spelling of the offence.
  - `[high]` `[patch]` **The two nets interacted so a real second gate could be legitimised by
    writing a sentence.** When the ban missed and only the comparison backstop fired, the backstop's
    own failure message offered "record an exemption" as the remedy — so a genuine gate was
    misclassified as "a comparison selecting no status" and waved through. A comparison that selects
    a status can no longer be resolved by recording it.
  - `[high]` `[patch]` **The exemption record could be silently transplanted.** Entries were
    `{file: {form: count}}`, so deleting the exempt comparison and adding a different one in the
    same file kept the count at 1 and both reconciliation tests stayed green. Findings now carry the
    enclosing function, so a transplant fails.
  - `[medium]` `[patch]` Seven more evasions closed: relative imports (`from . import outcomes`,
    the most natural spelling *inside* `core/` and `identity/`); the gate module reached through an
    alias; a `DictComp` or `dict(...)` table; membership against a named constant; the
    `(x == UNMAPPED and UNKNOWN) or verdict` short-circuit; a loop-guarded assignment; and
    single-level-only status name resolution.
  - `[medium]` `[patch]` `_class_prefixes` matched the package as a raw substring, so an unrelated
    `pseudo_identity` module invented prefixes.
  - `[medium]` `[patch]` `_selects_a_status` contradicted its own docstring: it claimed a branch
    that raises is not a gate, while `_offence` scanned `body` and `orelse` together.
  - `[medium]` `[patch]` The over-quota failure named every entry of a form, pointing the reader at
    the exempt line as well as the offending one; and the form string was reconstructed by
    `split(": ", 1)` at three sites, making an untested format load-bearing. Findings are a
    `NamedTuple` now.
  - `[medium]` `[patch]` The repo-wide sweep's anti-vacuity guard asserted only `len(scanned) > 1`,
    though the docstring argues test-tree coverage is the point; it now anchors a named file
    under `tests/`.
  - `[low]` `[patch]` Two negative controls could not fail — neither source contained a node kind
    the detector examines, so both would have passed under a detector that never fired; the
    duplicated `THE_ROLLUP_WRITER` path literal; and fitness cases for the documented
    `**expansion` and `AugAssign` edges.
  - `[low]` `[patch]` Traceability the story rewrite had dropped: `CPM-FR-5`, the TEA test-design
    block, the `References` list, and the Spec Change Log entry recording why two of the epic's
    three criteria are not implemented here.

## Design Notes

**Two of this story's three acceptance criteria were delivered by another story, and saying so is
the point.** `CPM-EVIDENCE-S07` needed the gate to write a rollup row at all — `core/rollup.py`
cannot compose a row for an `unmapped` package without deciding what its statuses read — so it built
`core/confidence.py` and pinned all three confidences, including the case that catches a gate which
*improves* a sentinel rather than only degrading one. It recorded the hand-off in its own triage log
rather than leaving it to be rediscovered. The honest scope for this story is therefore the audit,
and building the gate again would be the exact defect `CPM-AD-4` and `R-08` exist to prevent —
the story would create the thing it was written to forbid.

**The sweep is empty today, and that is the load-bearing problem.** There is no `policies` app and
no `PolicyPass` subclass anywhere in `src/`, so "no policy module defines its own gate" is true of a
tree with no policies in it. An audit that only sweeps today's files certifies nothing and would go
on certifying nothing right up until the first pass gets it wrong. So the detector has to be
measured: synthetic sources that *do* re-implement the gate, in every spelling a person would
plausibly reach for, asserted to be caught — and one that merely calls the gate, asserted not to be.
`tests/unit/django_apps/test_pass_ownership_audit.py` faces the same emptiness and solves it the same
way.

**The interesting detector question is what counts as "the gate".** A comparison against `unmapped`
is not on its own an offence: `identity/services.py`'s `_require_confidence_is_earned` compares one,
and it is a rule about what a *resolver* may claim, not about what the system reports outward. The
distinction the detector has to make is whether the comparison **selects a status value** — that is
what `CPM-AD-4` means by "expressed as writing a value". Either the detector is precise enough to
tell those apart, or the resolution-time rule is a recorded exemption with its reason. Both are
defensible; what is not defensible is widening the detector until it stops firing.

**`inventory-derived`'s label already exists as a column, not as a view concept.**
`PackageHealth.confidence` is stamped on every rollup row, and `core/models.py` argues it is recorded
there rather than read through the relation because it is the provenance of *that computation* —
`Package.confidence` is mutable, and a later resolution would otherwise make the row claim to have
been gated at a confidence it was not. Rendering that label is `CPM-EP-APP`'s. There is nothing for
this story to add.

## Verification

**Commands:**

- `pixi run test` -- expected: exits 0. This story adds one unit module and touches no database.
- `pixi run ci` -- expected: exits 0, coverage at or above 90%. Run it **after** `git add -A`.
- `pixi run gate-postgres` -- expected: exits 0 with nothing newly skipped. Nothing here is
  backend-sensitive; the run confirms the audit costs the gate nothing.

## Auto Run Result

Status: done

**What was implemented.** One file: `tests/unit/django_apps/test_confidence_gate_audit.py`, which is
`IDENTITY.03-AUDIT-001`. No production code changed, and that is the story's whole point — the
confidence gate already exists in `core/confidence.py`, built by `CPM-EVIDENCE-S07` two commits
before this story's baseline. What did not exist was the thing that keeps it the only one.

**Files changed.**

- `tests/unit/django_apps/test_confidence_gate_audit.py` — new. An AST sweep over the repository
  that reports any module but `core/confidence.py` selecting a status on an identity confidence,
  plus a reconciled exemption record for comparisons that legitimately do something else.

**Review findings:** 24 patched (9 high, 10 medium, 5 low), 2 deferred, 5 rejected. Four review
layers ran in parallel; three of them stopped reading the detector and started running it.

**Follow-up review recommended:** true. Nine high-severity patches.

**The audit was the thing under test, and it did not catch what it claimed to.** The first version
passed 405 cases and reported a clean tree. Three reviewers probed it with synthetic gates and found
that it missed most of the spellings a real policy pass would write: a `match`/`case` gate (never
scanned, and a `match_case` pattern is not an `ast.Compare`, so neither net saw it); the rule stated
from the trusted side; `!= VERIFIED`, which is itself the AC-2 violation because it degrades
`inventory-derived`; a status from a composed per-domain outcome type, which is the vocabulary
`core/outcomes.py` says every future pass will use; a status inside a returned `dict`, which is the
*normal* return shape for a `PolicyPass`; a confidence bound to a name, which is what a developer
writes after being told not to hard-code `"unmapped"`; and a package-then-attribute import, which
had no net at all.

Two structural findings mattered more than any spelling. When the ban missed and only the comparison
backstop fired, the backstop's own failure message offered "record an exemption" as the remedy — so
a genuine second gate could be legitimised by writing a sentence. And the exemption record was keyed
`{file: {form: count}}`, so deleting the exempt comparison and adding a different one in the same
file kept the count at 1 while both reconciliation tests stayed green.

**Verification.** `pixi run ci` exits 0 — 4263 passed, 2 pre-existing skips, coverage 98.37%.
`pixi run gate-postgres` exits 0 against a throwaway `postgres:17`. Beyond the gates, the detector
was measured rather than trusted: an eleven-case probe run against the shipped module reports every
evasion above and stays silent on a module that merely calls the gate. Separately, injecting a second
gate into `collectors/models.py` fails the audit on both fronts, naming the file and line, and the
tree passes again once reverted.

**Residual risks.** Two `deferred` entries. A wrapper that merely delegates to the gate is forbidden
in prose and caught by nothing — deliberately, since a detector broad enough to flag it would flag
every legitimate caller including `core/rollup.py`; the honest bound is that this audit catches the
accident and not a deliberate indirection, and closing it needs an import allowlist rather than a
wider detector. And `tests/source_scan.parse` is uncached with six audits now sweeping the tree,
which costs nothing today and belongs to whoever next touches that shared helper.
