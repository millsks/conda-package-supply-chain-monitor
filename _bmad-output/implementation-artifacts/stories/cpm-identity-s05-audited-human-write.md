---
title: 'CPM-IDENTITY-S05: The one audited human write'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '736370d14850102fe1a4e771d711c07a31b1be11'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s02-resolution-records-where-came-from.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s04-unresolved-packages-selectable-ranked.md
warnings: []
deferred:
  - summary: >-
      The override modal has no owner. The UX contract assigns it to `CPM-EP-IDENTITY`, this story
      ships the write without it, and `CPM-APP-S05`'s acceptance criteria never mention it.
    evidence: |-
      `EXPERIENCE.md` screen S7 says "The override write itself is CPM-AD-14 / CPM-FR-3, owned by
      **CPM-EP-IDENTITY** ... The queue is APP's; the modal is IDENTITY's. Flag the seam." This
      story ships the write, the permission and the audit row, and no surface -- because `core` has
      no permission class until `CPM-APP-S01` and a view built now would have to invent the central
      check `CPM-AD-13` says is implemented once. That is a sequencing argument and it holds. What
      does not hold is the assumption that the surface therefore belongs to `CPM-APP-S05`: that
      story's five acceptance criteria are about the three role-scoped queues and never mention the
      override, the modal, or `CPM-FR-3`. So the modal is currently owed by nobody, and the epic
      that would inherit it does not know it. It needs an owner named in `epics.md` rather than
      inferred, and the natural moment is when `CPM-APP-S01` lands the permission class this write
      is waiting on.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/services.py -- override_identity
    severity: medium
  - summary: >-
      Merging two packages that converge on one canonical name is now refused by both doors and
      owned by neither.
    evidence: |-
      `record_resolution` refuses a correction onto a name another package holds, and its message
      used to hand the job to this story. `override_identity` refuses it too. Both messages now say
      merging is owed by a later story, which is honest but leaves the work unassigned. It is a real
      scenario -- two inventory sources filing one upstream package under two keys is a state this
      product deliberately permits, and `test_one_source_key_may_be_claimed_by_two_different_sources`
      sets it up on purpose. A merge has to decide which key survives, which evidence moves, and what
      the audit row records; none of that is this story's to invent.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/services.py -- _require_name_is_unclaimed
    severity: medium
  - summary: >-
      The override cannot express `unmapped`, so a reviewer who looks and finds nothing has no way
      to record that.
    evidence: |-
      `Correction` carries a name, a display name and a reason; the write always sets `verified`.
      The implementer's argument for the restriction is in `Correction`'s docstring and is
      reasonable: "no upstream identity" is a resolution's finding, carried by mapping outcome rows,
      and lowering to `unmapped` here would return the package to the review queue it just left
      while carrying an audit row saying a human verified it was unverifiable. The counter-argument
      is `CPM-FR-3`'s plain words -- a platform lead corrects an identity, and "there is nothing
      there" is a correction a reviewer may reach. Recorded as a judgement rather than a settled
      question; reversing it is a field on `Correction` and a validation.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/services.py -- Correction
    severity: medium
  - summary: >-
      An active superuser reaches the product's one governed write without the leadership grant.
    evidence: |-
      `PermissionsMixin.has_perm` short-circuits `True` for any active superuser, so
      `_require_permitted` admits one. The implementer recorded this as a decision and asserted it
      both ways rather than leaving it to Django's default: the flag already reaches the Django
      admin, where the same rows are editable with **no** audit row at all, so refusing it here
      would make the one audited path the only one unavailable during a group-sync incident -- and
      the audit row is the mitigation. That reasoning holds, but it means `CPM-AD-14`'s "mutated by
      resolution, or by the override path -- nothing else" has a third door in practice, and the
      admin is the wider hole. Whoever closes the admin should revisit this together with it.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/services.py -- _require_permitted
    severity: low
  - summary: >-
      A corrected canonical name leaves the mapping and feedstock rows established under the old
      identity in place.
    evidence: |-
      The override writes the name, the display name and the confidence; `PackageMapping` and
      `Feedstock` rows resolved against the mis-identified upstream survive it unchanged, and a test
      pins that they are untouched. That is right for this story -- deleting them would be an
      unaudited write, and re-resolving them is a resolver's job -- but it means a corrected package
      can carry mappings that were established for a different upstream, with nothing marking them
      stale. The natural resolution is that the next resolution re-establishes them, which is true
      but unenforced and unstated anywhere a reader would find it.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/services.py -- _write_correction
    severity: low
---

<intent-contract>

## Intent

**Problem:** A collector can get an identity wrong, and today nothing can correct it. `CPM-FR-3`
makes this the **only** human write in the product that mutates governed reference data, which is
why `CPM-AD-14` puts the whole weight of the rule on it: the override requires a permission,
requires a reason, and writes an audit row in the same transaction. Nothing of that exists —
`ROLE_GROUP_PERMISSIONS` grants nothing to anyone, there is no `identity_overrides` model, and
`identity/services.py` opens no transaction at all.

**Approach:** A third door into `identity` — `override_identity` — that takes an actor, refuses one
who lacks the permission, refuses a blank reason, and writes the correction and its audit row inside
one `transaction.atomic()`. The audit row inherits the append-only base, so "append-only" is
enforced by machinery rather than by intention. The override sets `verified`, which
`record_resolution` already refuses to lower, so surviving automated resolution needs no new
mechanism.

## Boundaries & Constraints

**Always:**

- **The correction and its audit row are one atomic unit in one service function** (`CPM-AD-23`:
  "never `transaction.on_commit`, never a follow-up task"). This is `IDENTITY.05-INT-001` and risk
  `R-07`. `identity/services.py` opens no transaction today; this function is the first that must.
- **The audit row inherits `AppendOnlyModel`.** `CPM-FR-32` says the audit record is append-only,
  and the base already refuses a re-save, an `update()` and a `delete()`. Inheriting it makes the
  registry audits enforce that for free rather than leaving it to a docstring.
- The actor relation is `PROTECT` — required of every relation on an evidence model
  (`EVIDENCE.02-AUDIT-001`) and independently right: deleting a user must not delete the record of
  what they decided.
- The row carries `trace_id` from `core/ledger.py`'s `current_trace_id()` (`CPM-AD-15`), which PRD
  Appendix A.2's one-line summary omits and the architecture requires.
- **`identity_source` and `associator_key` are never written.** This is the fourth of the five
  conditions `CPM-IDENTITY-S06`'s review recorded and `CPM-IDENTITY-S02` assigned here: rewriting
  the pair while correcting a name orphans the package from its inventory source on the next sweep.
- The timestamp comes from the injected `Clock`. Never `auto_now_add` — the clock audit's
  exemptions do not cover `identity`.
- A refusal is **logged with the acting user identity**, in the `authorization.<event>` +
  `reason=` + identity-kwarg shape `config/authorization/mapper.py` already uses. Outside a request
  nothing binds `user_id`, so the service logs the actor explicitly rather than relying on
  `django_structlog`'s request binding.
- Every refusal precedes the first write, so a refused override leaves nothing behind.
- `pixi` is the only runner, and `git add -A` before `pixi run ci`. Run the gates **serially** —
  two `pytest --cov` runs in one worktree corrupt coverage's fragments.

**Block If:**

- Satisfying the permission check appears to require contributing `DEFAULT_PERMISSION_CLASSES`,
  `AUTHENTICATION_BACKENDS` or `MIDDLEWARE`. A domain app may contribute none of those.
- The audit row cannot be written in the same transaction as the correction.

**Never:**

- Do **not** build a view, serializer, URL or DRF viewset. See Design Notes: the write is
  `CPM-EP-IDENTITY`'s and the surface that calls it is `CPM-APP-S05`'s, and `identity`'s module list
  is pinned against exactly those names.
- Do **not** create a package. Creation is resolution's (`CPM-AD-25`); the override corrects a row
  that exists and refuses one that does not.
- Do **not** change `resolve_package_shell` or `record_resolution`'s signatures or refusals. The
  `verified`-holds branch is what makes an override survive automated resolution, and it already
  works; this story proves it rather than reimplementing it.
- Do **not** name a column `*_status` or `*_outcome`, and do **not** put a unique constraint on the
  audit model — the evidence audits forbid both.
- Do **not** grant the override permission to the security-reviewer or packaging-engineer slots.
- Do **not** add a dependency, a `pragma`, a coverage omit, a `pytest.skip`, or `databases=`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| A permitted override | an actor in the leadership group corrects a canonical name with a reason | the package is corrected, one audit row records actor, instant, prior value, new value and reason | No error expected |
| The confidence rises | the same override | the package reads `verified`, and the audit row records the prior confidence | No error expected |
| A forbidden actor | an actor holding no override permission | refused, nothing written, and the refusal is logged naming the actor | an override refusal |
| A blank reason | a permitted actor, reason empty or whitespace | refused before any write | an override refusal |
| An unknown package | a permitted actor, a package id that names nothing | refused rather than created | an override refusal |
| The join key is untouched | any successful override | `identity_source` and `associator_key` are byte-identical afterwards | No error expected |
| The audit row cannot be edited | a written audit row is re-saved | refused by the append-only base | `AppendOnlyError` |
| The audit row cannot be deleted | `delete()` on a written row, and `update()` on its queryset | both refused | `AppendOnlyError` |
| The actor cannot be deleted | deleting a user who has overridden | refused by the database | `ProtectedError` |
| Atomicity, write side | the audit row write fails | the correction is rolled back too — neither survives alone | the underlying error |
| Atomicity, audit side | the correction fails | no audit row is left behind | the underlying error |
| An override survives resolution | an override to `verified`, then a lower-confidence resolution | the corrected identity and its confidence stand | No error expected |
| Overrides are queryable | several overrides across packages | every one is retrievable as a set, newest first | No error expected |
| A correction onto a taken name | the new canonical name belongs to another package | refused, naming the collision | an override refusal |
| The queue drops it | an unmapped package in `unresolved_packages`, then overridden to `verified` | it no longer appears in the selection | No error expected |

</intent-contract>

## Code Map

- `identity/services.py:476` `record_resolution` — the second door. `:565-578` is the
  `verified`-holds branch that already refuses to lower a `verified` confidence, which is what makes
  an override survive automated resolution. `:581` `_package_at` — the find-by-pair that refuses
  zero and refuses many. `:625` `_require_name_is_free`, whose refusal message already names this
  story as the owner of collision resolution. `:733` `_write_feedstocks`, additive, with removal
  explicitly deferred here. **No `transaction.atomic()` exists in this module.**
- `identity/models.py` — `Package`, `Feedstock`, `PackageMapping`. `:80-82` records the override
  model and its audit row as this story's. `:328` `display_name`, written by nothing today and
  pinned as untouched by resolution.
- `core/models.py` `AppendOnlyModel` — refuses a re-save, an `update()`, a `delete()`. `:731` is the
  `not_evidence` precedent if an escape were ever needed; this story does not need one.
- `core/ledger.py:117` `current_trace_id()` — `032x` of the active span, never raises.
- `core/roles.py:57-59` the three slots, `:86-90` `ROLE_GROUP_PERMISSIONS` — **all three tuples are
  empty today**, with a comment saying grants "arrive with the surfaces they guard". `:166`
  `role_group_permissions`.
- `core/migrations/0001_provision_role_groups.py:38-43` — its own docstring says that when the first
  real codename is attached, a `create_permissions` call "has to be added here the way it was added"
  in `django_service/users/migrations/0003_provision_designated_groups.py:32-47`. That is the shape
  to copy.
- `config/authorization/mapper.py:296-301` — the refusal-logging idiom: a dotted
  `authorization.<event>` name, a `reason=` constant, and the acting identity as a kwarg.
- `collectors/selection.py:104` `RESOLVED_CONFIDENCES` — the review queue is this set's complement,
  so an override to `verified` removes the package from `CPM-IDENTITY-S04`'s selection.
- `collectors/tasks.py:836-880` `_observe` — the existing "two writes commit together" pattern, one
  `transaction.atomic()` around a shell and its snapshot.
- **Tests that must be rewritten rather than deleted:** `tests/unit/django_apps/test_roles.py:214`
  `test_every_role_slot_grants_nothing_yet` and
  `tests/integration/django_apps/test_role_groups.py:146` `test_the_role_groups_carry_no_permissions`
  both assert the empty state this story ends. `tests/unit/django_apps/test_identity_models.py:208`
  `IDENTITY_TABLES` must gain the new model or every sweep in that file skips it.
  `tests/unit/test_model_registry.py` names the evidence models and must name this one.

## Tasks & Acceptance

**Execution:**

- `identity/models.py` — add `IdentityOverride`, inheriting `AppendOnlyModel`: a `PROTECT` actor
  relation, a `PROTECT` package relation, the prior and new values, the reason, and `trace_id`.
- `identity/services.py` — add `override_identity(...)`: the permission check, the reason check, the
  collision check, and the correction plus audit row inside one `transaction.atomic()`.
- `core/roles.py` — declare the override permission and grant it to the leadership slot alone.
- `identity/migrations/0003_identity_override.py` and a `core` migration adding the
  `create_permissions` call its predecessor's docstring specifies.
- `tests/unit/django_apps/test_roles.py`, `tests/integration/django_apps/test_role_groups.py` —
  rewritten to assert the grant rather than its absence.
- `tests/unit/django_apps/test_identity_models.py`, `tests/unit/test_model_registry.py` — the new
  model added to the swept sets.
- `tests/unit/django_apps/test_identity_overrides.py`, `tests/integration/django_apps/test_identity_overrides.py`
  — new; every matrix row.

**Acceptance Criteria:**

1. Given an actor holding the override permission and a non-empty reason, when an identity is
   corrected, then the package carries the correction at `verified` and exactly one audit row records
   the actor, the instant, the prior value, the new value and the reason.
2. Given an actor without the permission, when the same write is attempted, then it is refused,
   nothing is written, and a log record names the acting user and the reason for refusal.
3. Given a failure on either side of the pair, when the override runs, then neither the correction
   nor the audit row survives alone — asserted in both directions, which is `IDENTITY.05-INT-001`.
4. Given a written audit row, when it is re-saved, deleted, or updated through its queryset, then
   each is refused; and when its actor is deleted, the database refuses that too.
5. Given any successful override, when the row is compared before and after, then `identity_source`
   and `associator_key` are unchanged.
6. Given an override to `verified` and a subsequent lower-confidence resolution, when the package is
   read, then the corrected identity and its confidence stand — and given `unresolved_packages`, the
   overridden package no longer appears.
7. Given the role groups after migration, when their permissions are read, then leadership holds the
   override permission and the other two roles hold none.

## Spec Change Log

### 2026-09-06 — The Design Note's reasons for shipping no surface were partly wrong

**What changed.** The Design Note argued four reasons for shipping the write without a view. Three
of them overstate the record and are corrected below; the decision itself stands on the fourth.

- *"There is no view layer anywhere in the product"* — false as written. The inherited platform has
  `django_service/users/views.py`, `users/api/views.py`, `config/urls.py` and a registered
  api_router. The true claim is the narrower one: no **domain** app has views.
- *"`identity`'s module list is pinned against `views`, `urls`, `serializers` and `api`"* — true, but
  that pin is a test written by earlier identity stories and is editable. This very change edited the
  adjacent constant in the same file to admit `confidence.py`. Citing a self-imposed constraint as an
  external one is not an argument.
- *"Building one would need `DEFAULT_PERMISSION_CLASSES`, which a domain app may not contribute"* —
  `CPM-AD-13` forbids a domain app touching that *setting* while requiring every view to declare its
  own permission class from `core`. Contributing the setting was never the only route.

**The reason that holds** is sequencing: `core` has no permission class yet — that is
`CPM-APP-S01`, still `ready-for-dev` — so a view built now would have to invent the central check
`CPM-AD-13` says is implemented once, and `CPM-IDENTITY-S04` set the precedent one story earlier by
shipping the review selection without the surface that renders it.

**The known-bad state this avoids.** A second permission check, written here and superseded when
`CPM-APP-S01` lands, in the one place the product most needs a single answer to "who may write this".

**What it leaves owed.** The modal itself. The UX contract assigns it to `CPM-EP-IDENTITY`;
`CPM-APP-S05`'s criteria never mention it. Filed in `deferred` rather than assumed, because the epic
that would inherit it does not know it has.

## Review Triage Log

### 2026-09-06 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 24: (high 8, medium 8, low 8)
- defer: 5: (high 0, medium 3, low 2)
- reject: 4: (high 0, medium 1, low 3)
- addressed_findings:
  - `[high]` `[patch]` **Two of this story's guards did not guard, which is the fourth consecutive
    story to ship that defect.** The join-key sweep inspected only literal AST constants while
    `_write_correction` addresses its columns through named constants, so `intended[ASSOCIATOR_KEY_FIELD] = …`
    — the module's own idiom — passed the test written to forbid it. And `DEFERRAL_FORMS` could not
    match `a_task.delay(...)`, because the helper it used returns the full dotted chain while the
    forbidden set held bare names, so `CPM-AD-23`'s "never a follow-up task" was unenforced for the
    common Celery spelling. Both fixed and mutation-verified, with the behavioural assertion added:
    the `update_fields` actually handed to `save()`.
  - `[high]` `[patch]` An `AnonymousUser` raised `AttributeError` rather than being refused, because
    the refusal path read `actor.idp_subject` unconditionally — so the branch AC 2 is written about,
    refused *and logged with the acting identity*, was the branch that broke.
  - `[high]` `[patch]` The package was read and the name collision checked outside the transaction
    with no row lock, so two concurrent overrides could both record the same prior values and a name
    taken between check and write escaped as a raw `IntegrityError`. Both moved inside, with
    `select_for_update()`, and the comment that overstated the old behaviour rewritten to describe
    the new — including that SQLite takes no row lock, so the gate is where it is proven.
  - `[high]` `[patch]` Every normalisation this service performs was dead: deleting all three
    `.strip()` calls passed the entire suite, because every accepted-value constant was already
    stripped and the only whitespace cases asserted refusals of wholly-blank input. A correction
    typed `" numpy "` would have been stored padded, would **not** have collided with the existing
    `"numpy"`, and would have flowed into every export — near-duplicate governed reference data
    through the one audited write path. Mutation-verified after the fix.
  - `[high]` `[patch]` `trace_id` was mutation-proven dead: deleting it from the create call passed
    3813 tests, since `""` is the column default. Now asserted inside a real recording span against
    the exported spans, with the outside-a-span case beside it.
  - `[high]` `[patch]` The "audit side" atomicity case asserted a rollback that never had anything to
    roll back — the correction write precedes the audit insert, so the insert was never attempted and
    its `count() == 0` was true of any implementation. The module claimed two directions and proved
    one twice. Reframed honestly, with a new case pinning the write ordering the claim rests on.
    Note what review *did* verify: replacing `transaction.atomic()` with `if True:` fails both cases,
    so the atomicity itself was never removable undetected.
  - `[high]` `[patch]` The import-cycle fix was half-applied. `identity/confidence.py`'s docstring
    states that a `core` module reading the vocabulary imports it from there, and names
    `core/confidence.py` as one that can — while `core/confidence.py` still imported from
    `identity.models`. It did not fail only because `core/models.py` happens not to import the gate;
    the next module that does would close the cycle again. Moved, with an audit that no `core` module
    may import the vocabulary from `identity.models` and an anti-vacuity case pinning the two that
    legitimately read it.
  - `[high]` `[patch]` A superuser reached the product's one governed write without the leadership
    grant, via Django's `has_perm` short-circuit — and the unit fixture depended on that shortcut,
    making it an accident rather than a decision. Now a recorded decision with the reasoning (the
    flag already reaches the admin, where the same rows are editable with no audit row at all) and
    asserted both ways, so reversing it is a one-line change plus a test edit.
  - `[medium]` `[patch]` Eight more: merge ownership, which both doors now refuse and whose stale
    message pointed at this story; `resolved_at` moving backwards on a correction stamped from
    behind; the rollback cases made symmetric with the injected-`DatabaseError` limitation stated;
    the confidence restriction recorded as a decision rather than an omission; `0004`'s reverse
    scoped to the role contract's own names rather than stripping the codename from every group; nine
    tests for `0004`, whose reverse and unconfigured branch were executed by nothing and whose wrong
    predicate detached nothing while the suite passed; `0001` no longer emitting an
    unresolved-codename warning on a fresh migrate, confirmed by running one; and
    revocation-by-omission documented and pinned.
  - `[low]` `[patch]` Eight smaller ones, including a success log event (only refusals were logged,
    so an operator filtering `authorization.` saw every rejected correction and no accepted one), the
    duplicated logging fixture moved to a conftest, `correction` renamed where it meant two things,
    `OVERRIDE_READ_INDEX` imported rather than re-spelled, an assertion that an override leaves
    mappings, feedstocks and the rollup alone, and an AST guard on the marker absence the
    refusals-precede-writes property silently depends on.

## Design Notes

## Design Notes

**No surface, and the record is thin on this — so it is stated rather than assumed.** The UX contract
says "the queue is APP's; the modal is IDENTITY's", which reads as though this story ships a view.
But there is no view layer anywhere in the product: `api_router.py` registers one viewset from the
inherited platform, no domain app has a `views.py`, and `identity`'s module list is pinned against
`views`, `urls`, `serializers` and `api`. Building one would also need `DEFAULT_PERMISSION_CLASSES`,
which a domain app may not contribute. `CPM-IDENTITY-S04` set the precedent one story ago — the
selection without the surface that renders it — and its story carries an explicit carve-out saying
so. **S05 has no such carve-out, and that asymmetry is a gap in the record rather than a decision.**
So: the write, the permission and the audit row here; the modal that calls it in `CPM-APP-S05`,
which is where the queue it is reached from already lives. Recorded in `deferred` so the surface is
owed by name rather than assumed.

**The permission is enforced at the service boundary, which is where the only caller is.** AC 2 says
a user without the permission is refused and the refusal logged. With no view, the service is the
boundary, and `user.has_perm` is the check. `CPM-AD-13` says authorization is declared per surface
and enforced centrally; when the surface arrives it declares its permission and the service check
becomes the second line rather than the only one. Two lines are correct for the product's single
governed write.

**The audit row inherits `AppendOnlyModel`, and that is the honest reading of "append-only".**
`CPM-FR-32` says the audit record is append-only and independently queryable. The base already
refuses a re-save, an `update()` and a `delete()`, and the registry audits enforce it without this
story writing an assertion. The classification carries obligations — no unique constraint, `PROTECT`
on every relation — and both are what an audit row wants anyway. PRD Appendix A.2 lists
`identity_overrides` among the evidence tables, which agrees.

**One row per human decision, not one per changed field.** The PRD says "prior value, new value"
in the singular, and an override may correct several fields at once. One row per field would split
one human decision across several rows that must then be read back together to reconstruct it; one
row per decision, carrying what changed, keeps "an override" and "a row" the same thing — which is
what AC 5's "queryable as a set" wants, and what an auditor reviewing a correction is looking for.

**Surviving automated resolution needs no new mechanism, and proving it is the point.**
`record_resolution` already refuses to lower a `verified` confidence and refuses to overwrite the
name that goes with it — `CPM-IDENTITY-S02` built that branch and the review that hardened it made
the branch record the resolver's findings while holding the claim. So an override that sets
`verified` is already durable. AC 6 asserts it end to end rather than assuming the two stories agree.

**The permission grant ends a state two tests currently assert.** `ROLE_GROUP_PERMISSIONS` grants
nothing to anyone, and both a unit test and an integration test pin that emptiness deliberately —
they are the mechanism that would catch a permission granted by accident. This story is the first
real grant, so both are rewritten to assert *this* grant and the continued emptiness of the other
two slots. Rewritten, not deleted: the property they protect still matters.

## Verification

**Commands:**

- `pixi run test` -- expected: exits 0.
- `pixi run test-integration` -- expected: exits 0, no new skips.
- `pixi run ci` -- expected: exits 0, coverage at or above 90%. Run **after** `git add -A`.
- `pixi run gate-postgres` -- expected: exits 0. `PROTECT` on the actor relation and the rollback
  cases are database-enforced, so this is where AC 3 and AC 4 are genuinely proven. Run it
  **after** `ci` finishes, never alongside it.

## Auto Run Result

Status: done

**What was implemented.** The only human write in the product that mutates governed reference data.
`override_identity` takes an actor, refuses one without the permission, refuses a blank reason, and
writes the correction and its audit row inside one `transaction.atomic()`. `IdentityOverride`
inherits `AppendOnlyModel`, so "append-only" is enforced by machinery rather than asserted in prose.
`core/roles.py` declares the override permission and grants it to the leadership slot alone — the
first real grant in a table that had been empty by design.

**Files changed.**

- `identity/models.py` — `IdentityOverride` (`identity_overrides`), `PROTECT` on both relations,
  prior/new pairs, reason, `trace_id`, and the permission codename in `Meta.permissions`.
- `identity/services.py` — `override_identity`, the `Correction` value object, and the refusals.
- `identity/confidence.py` — new. `IdentityConfidence` moved to a leaf module to break an import
  cycle; re-exported from `identity/models.py` so no existing importer changed.
- `core/models.py` — `PackageHealth.package` switched to Django's lazy `"identity.Package"`, the
  other half of the cycle break. Deconstructs identically; `makemigrations --check` reports nothing.
- `core/roles.py`, `core/migrations/0005_grant_identity_override.py`,
  `identity/migrations/0003_identity_override.py` — the permission and its provisioning.
- Two new test modules, plus rewrites of the two tests that pinned the empty-permission state.

**Review findings:** 24 patched (8 high, 8 medium, 8 low), 5 deferred, 4 rejected. Four review layers
ran in parallel over the full 3,853-line diff.

**Follow-up review recommended:** true. Eight high-severity patches.

**Four consecutive stories have now shipped guards that did not guard, and this one shipped two.**
The join-key sweep inspected only literal AST constants while the writer addresses its columns
through named constants — so the module's own idiom passed the test written to forbid it. And the
deferred-write guard could not match `a_task.delay(...)`, leaving `CPM-AD-23`'s "never a follow-up
task" unenforced for the common Celery spelling. That pattern — an audit written against the shape
its author had in mind rather than the shape the code takes — is worth carrying into the next epic.

**The review's other work was done by mutation rather than argument.** Three defects were proven by
changes that passed the entire suite: deleting every `.strip()` in the service, which would have let
`" numpy "` be stored padded and *not* collide with the existing `"numpy"`; deleting `trace_id` from
the audit row, which would have shipped every row with the column default; and giving the migration's
`reverse` a wrong predicate, which detached nothing. A fourth mutation confirmed the story's central
claim held — replacing `transaction.atomic()` with `if True:` fails both rollback cases, so
`IDENTITY.05-INT-001` was never removable undetected. What was wrong there was narrower and real: the
"audit side" case asserted a rollback that never had anything to roll back, because the correction
write precedes the audit insert.

**The import-cycle fix was half-applied.** `identity/confidence.py` exists to stop `core` reading the
vocabulary through `identity.models`, and named `core/confidence.py` as a module that could import it
directly — while `core/confidence.py` still imported from `identity.models`. It did not fail only
because nothing in `core/models.py` imports the gate. Now moved, with an audit keeping the rule.

**Verification.** `pixi run ci` exits 0 — 4424 passed, 2 pre-existing skips, coverage 98.43%.
`pixi run gate-postgres` exits 0 with identical counts. All fifteen I/O matrix rows have a covering
test that ran and passed. Two of the review's mutations were re-run independently after the fixes and
now fail as they should.

**Residual risks.** Five `deferred` entries. Two are unassigned work rather than defects: the
override **modal** has no owner — the UX contract gives it to `CPM-EP-IDENTITY`, this story ships the
write without it, and `CPM-APP-S05`'s criteria never mention it — and **merging** two packages that
converge on one canonical name is now refused by both doors and owned by neither. Both need a name in
`epics.md` rather than an inference. The third is a judgement worth revisiting: the override cannot
express `unmapped`, so a reviewer who looks and finds nothing has no way to record that.
