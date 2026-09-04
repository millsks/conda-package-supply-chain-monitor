---
title: 'CPM-EVIDENCE-S01: Five outcome states with one precedence order'
type: 'feature'
created: '2026-09-04'
status: 'done'
baseline_revision: 'a3b98312554b69d4fe863acc35266b790f2043e6'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
warnings: ['oversized']
deferred:
  - summary: >-
      The derived-status field audit still accepts a field offering the four sentinels
      alongside extra values, so a partially free vocabulary passes.
    evidence: |-
      Django discards the `Choices` class during field normalisation, so no registry-level
      audit can assert a field's choices came from a `core`-derived type. Label identity
      closes the hand-rolled case, but a field carrying the four sentinels plus `"clean"`
      and `"pending"` is indistinguishable at this level from the determinate verdicts
      `outcome_type` exists to add. Documented in the audit module; closing it belongs to
      `CPM-EVIDENCE-S02`, which declares the first real status field.
    location: >-
      tests/unit/django_apps/test_outcome_field_audit.py
    severity: medium
  - summary: >-
      The project's "no multi-paragraph docstrings" instruction conflicts with this
      repository's heavily prose-documented house style.
    evidence: |-
      The global CLAUDE.md forbids multi-paragraph docstrings and comment blocks in
      generated code. The inherited platform under `src/config/` and `src/django_service/`
      is written the opposite way, and the modules added here follow the house style with
      module docstrings around fifty lines. Both new and existing code cannot satisfy both
      conventions; a maintainer decision is needed rather than a code change.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/core/
    severity: low
---

<intent-contract>

## Intent

**Problem:** Every derived status in this system needs the same vocabulary and the same
"worst of these" rule, or two policies invent incompatible state sets and three read
surfaces invent three different lattices — `R-01`, the project's highest-scored risk.
Nothing exists yet: `core` has no status type, no precedence order and no clock, and two
inherited platform modules read the wall clock directly.

**Approach:** Define the outcome vocabulary, the single total precedence order, and the
injected clock in `core`, each declared exactly once, and enforce all three mechanically —
a model-registry audit over derived-status fields, a scan proving no second ordering
exists, and a scan proving no module reads the clock directly.

## Boundaries & Constraints

**Always:**
- `not_applicable`, `unknown`, `not_found` and `error` are fixed lowercase string values. A determinate (clean) value makes the fifth state. All five are separately representable everywhere (`CPM-FR-6`).
- The precedence order is one declaration in `core`, total over all five states, and is what every aggregation uses. Aggregation never collapses a sentinel into the determinate value.
- Every derived-status column is `CharField(choices=...)`. Never a boolean, never a nullable boolean.
- Time comes from the clock in `core`. Exactly one module in the repository may call `timezone.now()`, and it is the clock's own implementation.
- Audits are AST scans over the repository in the shape `tests/unit/test_import_roots.py`, `tests/unit/test_suite_policy.py` and `tests/group_writers.py` already use — parsed trees, never text search. Every scan carries an anti-vacuity guard asserting it reaches what it claims to cover.
- A pre-existing violation is grandfathered only as a counted entry in a `RECORDED_EXEMPTIONS`-style table naming the file and the number of occurrences, as `tests/unit/test_suite_policy.py:132` does. Never a path prefix skipped wholesale.
- `structlog` only, no `print`, no stdlib `logging`. Full type hints, Google docstrings, line length 120.

**Block If:**
- Enforcing the clock audit would require editing `src/django_service/` or `src/config/` behaviour rather than recording a counted exemption.
- A derived-status field cannot be expressed as `CharField(choices=...)` without a model this story is not scoped to create.

**Never:**
- Do not create evidence models, the append-only base model, or the run-ledger models — those are `CPM-EVIDENCE-S02`/`S03`.
- Do not create a concrete per-status determinate type for a policy that does not exist yet (no `LicenseOutcome`, no vulnerability outcome); build the mechanism and prove it, and let the owning story declare its own.
- Do not refactor `src/django_service/users/management/commands/prune_expired_state.py` or `src/config/local_dev/tokens.py` onto the new clock. They are inherited platform, outside `CPM-EP-EVIDENCE`'s binding, and `django_service` importing a domain app would invert the dependency direction.
- Do not add a startup refusal, a settings key, or a `component.toml` entry.
- Do not reach for `hypothesis`; it is not a dependency and the cross-product is 25 pairs.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Sentinel values | `OutcomeState` members | four sentinels present with fixed lowercase values, plus a determinate value | No error expected |
| Determinate type built | a per-status type composed from the sentinel table | carries all four sentinels by name **and** value | No error expected |
| Determinate type missing a sentinel | a type composed without one | rejected at construction | Raises, with the missing name |
| Precedence is total | the declared order | every state appears exactly once; no ties | No error expected |
| Aggregate a pair | all 25 ordered pairs | the state earlier in the declared order wins, and the result is order-independent | No error expected |
| Aggregate sentinel with determinate | `{not_applicable, ok}` | `not_applicable` — never folded into the clean result (`CPM-FR-6`) | No error expected |
| Aggregate empty | no states | a stated, documented result rather than an accident | Raises or returns `unknown`; the choice is stated once and tested |
| Second ordering declared | a module other than `core` declaring a sequence of two or more `OutcomeState` members | audit fails, naming the module | Assertion names the offending path |
| Derived-status field audit | every field in the model registry marked a derived status | each is `CharField` with choices carrying all four sentinels | Assertion names the offending field |
| Field audit anti-vacuity | no derived-status model exists yet | the detector is proven against a fixture model, so the audit cannot pass by finding nothing | Test fails if the detector matches nothing |
| Direct clock read | any module under `src/` calling `timezone.now`/`datetime.now`/`utcnow` | audit fails, naming the module | Assertion names the offending path |
| Grandfathered clock read | the two inherited platform call sites | permitted by counted exemption only | A third occurrence in the same file fails |
| Clock injection | a test supplying a fixed instant | every reader observes that instant | No error expected |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/core/` -- currently `apps.py` (`CoreConfig`, no `ready()`), `roles.py`, `migrations/0001_provision_role_groups.py`. No models, no `models.py`. **New files land here.**
- `src/django_apps/.../core/roles.py` -- the shape to mirror for a `core` declaration module: `Final` constants, a frozen slots-`True` dataclass, module docstring carrying the rationale, imports nothing from `django.apps` or `django.contrib.auth`. Read-only.
- `src/django_service/users/management/commands/prune_expired_state.py:229` -- `now = timezone.now()`. Inherited; grandfathered by counted exemption, not refactored.
- `src/config/local_dev/tokens.py:106` -- `issued_at = datetime.now(tz=UTC)`. Same treatment.
- `src/django_service/users/migrations/0001_initial.py:85` -- `django.utils.timezone.now` as a field default, written by Django's own migration autogenerator. Migrations are outside the scan.
- `tests/unit/test_import_roots.py` -- the audit shape `CPM-AD-26` names explicitly: AST + TOML over repository files, assertions written as "this mechanism is absent", named entrypoints kept as an anti-vacuity guard. The model for both new audits.
- `tests/unit/test_suite_policy.py:132` -- `RECORDED_EXEMPTIONS: dict[str, dict[str, int]]`, a licence for a fixed *count* of a fixed form in a fixed file. The exemption mechanism for the two clock call sites, and the reason a prefix skip is not acceptable.
- `tests/group_writers.py` -- the repo's shared-AST-helper module, extracted in `CPM-PLATFORM-S02`. Where a scan helper belongs when two test modules need it, rather than a cross-module private import.
- `tests/unit/django_apps/test_roles.py` -- the assertion shapes for a `core` declaration module, including the AST import scan and its anti-vacuity guard.
- `tests/conftest.py`, `tests/unit/conftest.py` -- where a clock fixture belongs; check which before adding.
- `_bmad-output/planning-artifacts/prds/.../prd.md#CPM-FR-6` -- "A check that does not apply to a package is never folded into clean or unknown." This is what fixes `not_applicable` above the determinate value in the order. Read-only.

## Tasks & Acceptance

**Execution:**

- `src/django_apps/conda_package_supply_chain_monitor/core/outcomes.py` -- new. Declare the four sentinel names and their fixed lowercase values once, as the single table every outcome type is built from; `OutcomeState` as a `models.TextChoices` carrying those four plus the determinate value; the factory that composes a per-status type from the sentinel table plus its own determinate members, refusing to build one that would drop or rename a sentinel; `PRECEDENCE`, the single total order, declared worst-first; and the aggregation callable that reduces states through it. Nothing else declares an order. See Design Notes for why the factory is a factory.
- `src/django_apps/conda_package_supply_chain_monitor/core/clock.py` -- new. A `Clock` protocol with `now() -> datetime` returning an aware UTC instant, the production implementation (the one permitted `timezone.now()` call site in the repository, marked as such in a comment the audit's exemption table points at), and a fixed-instant implementation for tests. Injection is by parameter, not by a module-level singleton a caller can forget to pass.
- `tests/unit/django_apps/test_outcomes.py` -- new. Matrix rows 1-7: sentinel values, a composed determinate type carrying all four by name and value, refusal when one is dropped, the order is total with no ties, all 25 ordered pairs aggregating to the declared winner and doing so order-independently (`EVIDENCE.01-UNIT-002`), `{not_applicable, ok}` never collapsing to `ok`, and the empty aggregation.
- `tests/unit/django_apps/test_single_ordering_audit.py` -- new. `EVIDENCE.01-UNIT-001`: AST scan proving `core.outcomes` is the only module declaring a sequence of two or more `OutcomeState` members. Anti-vacuity guard: the scan finds the declaration in `core.outcomes`, and the detector matches a synthetic second declaration.
- `tests/unit/django_apps/test_outcome_field_audit.py` -- new. `EVIDENCE.01-AUDIT-001`: enumerate derived-status fields from the Django model registry — never a hand-written list — and assert each is a `CharField` whose choices carry all four sentinels. No such model exists yet, so the anti-vacuity guard is the load-bearing half: prove the detector against a fixture model, one conforming and one not, so the audit cannot pass by finding nothing.
- `tests/unit/django_apps/test_clock_audit.py` -- new. `EVIDENCE.01-AUDIT-002`: AST scan over `src/` for `timezone.now`, `datetime.now` and `utcnow` calls, excluding `*/migrations/*`. A counted exemption table in the `test_suite_policy.py` shape licenses exactly one occurrence in each of the two inherited modules and the clock's own implementation; a second occurrence in any of them fails. Anti-vacuity guard: the scan reaches the named inherited call sites.
- `tests/unit/django_apps/test_clock.py` -- new. The fixed-instant implementation returns what it was given; the production one returns an aware UTC instant; both satisfy the protocol.
- `tests/group_writers.py` or a sibling -- if two of the new audits need the same AST walk, lift it beside the existing shared helpers rather than importing across test modules.

**Acceptance Criteria:**

- Given `django_apps.core` exists, when `OutcomeState` is defined as a `TextChoices` with fixed lowercase string values, then it carries `not_applicable`, `unknown`, `not_found` and `error`, and a per-status determinate type inherits those four sentinels by name and value.
- Given a derived status needs storing, when the field is declared, then it is a `CharField` with `choices`, never a boolean and never a nullable boolean, and a test enumerates every derived-status field from the model registry, never a hand-written list, and asserts the four sentinels are present.
- Given two statuses must be aggregated into one, when the precedence order is applied, then it comes from the single total order defined in `core`, and a test asserts no other module defines an ordering.
- Given any module in the project, when it needs the current time, then it takes it from the injected clock in `core`, and an audit fails on a direct `timezone.now()` call.
- Given the whole change, when `pixi run ci` runs, then it exits 0 with coverage at or above the 90% floor.

## Spec Change Log

## Review Triage Log

### 2026-09-04 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 28: (high 3, medium 12, low 13)
- defer: 2: (high 0, medium 1, low 1)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[high]` `[patch]` The clock audit inspected only `ast.Call`, so a wall clock handed over as a
    callable was invisible -- `default=timezone.now`, and `auto_now_add=True` where Django reads the
    clock on the model's behalf. `src/django_service/users/models.py` already carried one, unrecorded.
    The detector now walks attribute and name references and matches the `auto_now*` keywords; the
    existing read is a fourth counted exemption. Probed independently: both forms now fail.
  - `[high]` `[patch]` `from django.utils import timezone as tz; tz.now()` defeated the audit entirely.
    Receiver aliases are now resolved from `Import`/`ImportFrom` as the sibling ordering audit already
    did. Probed independently: the aliased read now fails.
  - `[high]` `[patch]` A dict of ranks was a complete second precedence order that passed, and the
    comment above `SEQUENCE_NODES` asserted it was caught -- reasoning that was wrong rather than
    incomplete. `ast.Dict` is now counted across keys and values. Probed independently: a five-entry
    rank map now fails.
  - `[medium]` `[patch]` Assignments nested in module-level `if`/`try` escaped the ordering audit;
    statement recursion added, stopping at function boundaries.
  - `[medium]` `[patch]` The banned-read set covered only `now`/`utcnow`; widened with `datetime.today`,
    `date.today`, `timezone.localtime`, `timezone.localdate`, `time.time` and `time.time_ns`.
  - `[medium]` `[patch]` `verify_sentinels`' name-and-value claim tested only the missing-name branch;
    a type renaming a sentinel's value is now the case that proves it.
  - `[medium]` `[patch]` The field audit accepted `blank=True`, a default outside the choices, a
    non-lowercase value and a malformed choices entry; all now rejected, and label identity closes the
    hand-rolled-table case.
  - `[medium]` `[patch]` `outcome_type` validated the caller's members only against the sentinels;
    duplicate names, duplicate values, an empty determinate set and non-identifier names now raise.
  - `[medium]` `[patch]` The file walk descended into virtualenv and build directories and followed
    directory symlinks; exclusions widened, symlinks skipped, `OSError` recorded rather than raised so
    a failure names a test instead of aborting collection.
  - `[medium]` `[patch]` `allauth.account` was asserted out of scope without first being asserted
    installed, so the case passed vacuously if allauth were removed.
  - `[medium]` `[patch]` `tests/source_scan.py` had no tests though both audits depend on it, and its
    docstring claimed a consolidation it had not performed. It now has its own suite, and
    `test_import_roots.py` imports the shared walk instead of keeping a divergent copy.
  - `[medium]` `[patch]` `FixedClock` documented a UTC instant but accepted any aware offset; it now
    normalises to UTC while staying frozen.
  - `[low]` `[patch]` Thirteen further fixes: a protocol negative control; `outcome_type`'s
    fresh-class-per-call identity documented and pinned; grouped and malformed choices handled;
    `dotted_name`'s divergence from its namesake recorded; the deferred rank decision given story
    references; `FIXED_INSTANT` moved out of the conftest into `tests/clocks.py`; `aggregate` refusing
    a bare string; `verify_sentinels` converting `TypeError` to its own error; `parse` naming the path
    on unreadable, non-UTF-8 and invalid files; `outcomes.__file__ is None` raising rather than
    resolving to the cwd; and the `AD-`/`CPM-AD-` register stated in each new module.
  - `[medium]` `[patch]` One item was applied in part by the implementer's judgement and accepted on
    review: `time.monotonic` was left legal. It carries no epoch, cannot stamp an `observed_at` or
    answer a freshness question, and is the correct source for the timeouts and backoff the collector
    base needs; `config/authorization/jwks.py` already injects it. Banning it would have required
    exempting correct code. A negative control pins the decision.

## Design Notes

**The determinate type is composed, not subclassed.** AC #1 says a per-status type "inherits"
the four sentinels, but a Python enum that has members cannot be subclassed — `class
LicenseOutcome(OutcomeState)` raises `TypeError`. The mechanism that delivers the property
the word "inherits" is asking for is a factory over one sentinel table: every per-status type
is built from it, so no type can drift a name or a value, and the factory refuses to build one
that drops a sentinel. Do not work around the enum restriction with duplicated member lists —
duplication is exactly what `CPM-AD-5` exists to prevent.

**Why `not_applicable` outranks the determinate value.** `CPM-FR-6` is explicit that a check
which does not apply "is never folded into clean or unknown". An order placing the determinate
value above `not_applicable` would make aggregating `{ok, not_applicable}` yield `ok`, which is
that fold. So the order is constrained, not free, at that boundary.

**The order this spec declares, worst first:** `error`, `unknown`, `not_found`,
`not_applicable`, determinate. `error` is worst because a failed observation is the loudest
signal. `unknown` ranks above `not_found` because an un-observed state hides risk, while
`not_found` is an informative negative — we looked, and the thing is not there.

*This last distinction is the one genuinely free choice in the story.* Nothing in the PRD, the
spine or the test design fixes `unknown` against `not_found`, and no consumer of the order
exists yet. It is recorded here so a reviewer can overturn it cheaply; a later story that finds
the opposite reading changes one tuple in `core` and the 25-pair test follows it, because the
test asserts aggregation matches the *declared* order rather than a hardcoded winner.

**Why the two inherited clock reads are exempted rather than fixed.** `CPM-AD-26` binds
`CPM-EP-EVIDENCE`; `prune_expired_state.py` and `local_dev/tokens.py` are inherited platform.
Refactoring them onto `core`'s clock would make `django_service` import a domain app, inverting
the dependency direction `AD-4` fixes. The counted-exemption table is what keeps the audit
honest anyway: it names both files and licenses exactly one occurrence each, so a third
direct read anywhere — including a second one in those files — fails the gate.

## Verification

**Commands:**
- `pixi run test` -- expected: the new unit tests pass; run after each file rather than once at the end.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: clean under strict mypy.
- `pixi run python manage.py makemigrations --check --dry-run` -- expected: "No changes detected". This story adds no model, so a migration appearing here means one was added by mistake.
- `pixi run ci` -- expected: exit 0, coverage at or above 90.

**Manual checks:**
- Confirm each new audit fails when its guard is removed: temporarily add a `timezone.now()` call to a `django_apps` module, a second `OutcomeState` sequence to a second module, and a boolean status field to the fixture model. Each must fail its own audit and no other.

## Auto Run Result

Status: done

### Implemented change

`core` now owns the vocabulary every derived status in the system will use, the single total
precedence order any aggregation reduces through, and the injected clock every time-dependent
computation takes its instant from. Each is declared once and enforced mechanically rather
than by convention: three AST audits fail the build on a second ordering, on a direct
wall-clock read, and on a derived-status field that cannot represent the five states. This is
`R-01`'s mitigation — the project's highest-scored risk — landed before any consumer exists,
which is the point: the rule is cheap now and expensive after `CPM-EP-EVIDENCE` ships.

### Files changed

- `src/django_apps/conda_package_supply_chain_monitor/core/outcomes.py` — new. `OutcomeState`, the
  sentinel table, `outcome_type` composing per-status types from it, `verify_sentinels`, `PRECEDENCE`,
  `EMPTY_AGGREGATE` and `aggregate`. 100% covered.
- `src/django_apps/.../core/clock.py` — new. The `Clock` protocol, `SystemClock` (the one permitted
  `timezone.now()` call site) and `FixedClock`. Injection by parameter; no ambient accessor. 100% covered.
- `tests/source_scan.py`, `tests/clocks.py` — new shared helpers: the repository file walk and AST
  parse both audits build on, and the fixed instant two test modules share.
- `tests/unit/django_apps/test_outcomes.py` — the vocabulary, the order, and all 25 ordered pairs.
- `tests/unit/django_apps/test_single_ordering_audit.py` — `EVIDENCE.01-UNIT-001`.
- `tests/unit/django_apps/test_outcome_field_audit.py` — `EVIDENCE.01-AUDIT-001`.
- `tests/unit/django_apps/test_clock_audit.py` — `EVIDENCE.01-AUDIT-002`.
- `tests/unit/django_apps/test_clock.py`, `tests/unit/test_source_scan.py` — the two new modules and
  the helper they share.
- `tests/unit/test_import_roots.py` — now imports the shared walk instead of keeping a divergent copy.
- `tests/unit/conftest.py` — the `fixed_clock` fixture.

### Review findings breakdown

- Patches applied: 28 (high 3, medium 12, low 13). One medium item was applied in part by the
  implementer's judgement and accepted on review — see the triage log's `time.monotonic` entry.
- Items deferred: 2 (the residual superset-vocabulary gap in the field audit, assigned to
  `CPM-EVIDENCE-S02`; the docstring-convention conflict, which needs a maintainer decision).
- Items rejected: 2 (the story file's absence from the reviewed diff, an artifact of how the diff was
  constructed; and the `max_length` check, already enforced by Django's own `fields.E009`).

### Follow-up review recommendation

`true`. Patched findings by severity: high 3, medium 12, low 13. Three high-severity patches trip the
rule on their own; the weighted score is `3 × 12 + 1 × 13 = 49`.

### Verification performed

- `pixi run ci` — exit 0. 2105 tests, coverage 97.19%; both new source modules at 100%.
- `pixi run python manage.py makemigrations --check --dry-run` — "No changes detected". This story
  declares no model, so a migration appearing here would mean one crept in.
- Every audit fix was probed independently of the implementer, each introduced then reverted, with
  `git diff --stat src/` empty afterwards. Each failed **only** its own audit: an aliased `tz.now()`,
  a handed-over `default=timezone.now`, and an `auto_now_add=True` each fail the clock audit; a
  five-entry rank map fails the ordering audit and leaves the clock and field audits green.
- The counted exemption was probed in both directions: a second `auto_now_add` in the exempted module
  fails both the sweep and the exemption's own count check.

### Residual risks

- **Nothing consumes any of it yet.** No module in `src/` takes a clock, and no caller aggregates.
  `aggregate` and the precedence order are asserted about themselves rather than about any application,
  and the injection of production code is unexercised because there is no production consumer. That is
  inherent to landing the kernel first, but it means the first real consumer is where these contracts
  meet reality.
- **The `unknown`-above-`not_found` ranking is the one free choice in the story.** Nothing in the PRD,
  the spine or the test design fixes it, and no consumer exists to contradict it. Overturning it is one
  tuple in `core`; the 25-pair test follows the declared order rather than hardcoding winners.
- **The audits catch declarations, not computations.** An ordering built inside a function body, or a
  clock read reached through a helper the scan cannot follow, is out of scope by design. Both modules
  state their own holes; the guarantee is "no new declaration-shaped violation", not "no violation".
- **Two inherited platform modules still read the wall clock**, plus one `auto_now_add`. They are
  counted exemptions, not conversions, and converting them would invert the dependency direction `AD-4`
  fixes. A third read anywhere — including a second in any exempted file — fails the gate.
- **`aggregate` refuses a per-status determinate verdict it cannot rank.** That is the correct default
  given `CPM-FR-6`, but it means the first story adding such a verdict must rank it explicitly rather
  than discovering the refusal at runtime.
