---
title: 'CPM-PLATFORM-S02: Group claims resolve to the three product roles'
type: 'feature'
created: '2026-09-03'
status: 'done'
baseline_revision: 'da0a84d558be92b3afca24b7b8d196a28d915ee5'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md
warnings: ['oversized']
deferred:
  - summary: >-
      A group name longer than `auth.Group.name`'s 150 characters raises `DataError`
      inside `migrate`, leaving the database mid-migration.
    evidence: |-
      `load_role_contract` passes the value through untouched, and `provision_groups`
      hands it straight to `get_or_create`. The claims contract has the identical
      exposure today through `COMPONENT_STAFF_GROUP`, so this is pre-existing rather
      than introduced here; it is recorded because the role contract widens the number
      of variables that can trigger it from two to five.
    location: >-
      src/django_service/users/provisioning.py
    severity: medium
  - summary: >-
      The migration-output integration test reads state left by `migrate`, so it fails
      against a database reused from before this migration existed.
    evidence: |-
      `--reuse-db` in the pytest addopts keeps a test database between runs. The test was
      verified with `--create-db`, but a developer whose database predates the migration
      sees a failure whose cause is the stale database rather than the code.
    location: >-
      tests/integration/django_apps/test_role_groups.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** The brief names three account-holding roles (security and compliance reviewer,
packaging engineer, platform and engineering leadership), but no `Group` row exists for any
of them. `sync_authorization` only grants groups that already exist and never creates one,
so today an IdP asserting a role group grants nothing and logs it as an unknown claim.

**Approach:** Give the product a role contract read from the environment, provision its three
groups through the platform's single group-creation mechanism from a `core` data migration,
and prove the inherited resolution and refusal behaviour holds for these groups. No new
resolution, sync or permission-class code — `CPM-FR-30` is satisfied by the platform (`AD-10`).

## Boundaries & Constraints

**Always:**
- Group rows are created only by `src/django_service/users/provisioning.py`. `tests/unit/users/test_provisioning.py::test_the_provisioning_module_is_the_only_writer_of_groups` AST-scans all of `src/` and fails the moment a second module binds `auth.Group` to a creation verb. The product's migration calls into that module; it never creates a group itself.
- Role group *names* come from the environment with no default anywhere in `src/config/settings/base.py` or in the role module. Values are `.strip()`ed, so whitespace-only reads as unset — the `load_claims_contract` convention.
- No role group name is hardcoded in the module that provisions or permissions it; keying is by role slot, as `DESIGNATED_GROUP_PERMISSIONS` does.
- Reading an unconfigured role contract raises nothing and provisions nothing; it logs and returns, exactly as `provision_designated_groups` does for an unconfigured claims contract. `migrate` on a fresh clone must stay usable.
- `structlog` only, no `print`, no stdlib `logging`. Full type hints, Google docstrings, line length 120.

**Block If:**
- Satisfying an acceptance criterion would require a domain app to contribute to `AUTHENTICATION_BACKENDS`, `DEFAULT_AUTHENTICATION_CLASSES`, `DEFAULT_PERMISSION_CLASSES` or `MIDDLEWARE` (the inherited `CONTRIBUTABLE_KEYS` allowlist forbids it).
- The single-writer audit cannot be kept green without weakening or editing that audit.

**Never:**
- Do not add a stage-one or stage-two startup refusal for an unconfigured role contract, and do not touch `tests/payload.py`'s `BUILD_SCAFFOLDING_VARIABLES` or the `Dockerfile` build-stage roster — that refusal is not this story's, and adding one makes every existing deployed-import test need new variables.
- Do not write permission classes, views, routes, queues or role-scoped surfaces (`CPM-AD-13`, `CPM-FR-31` — those are `CPM-EP-APP`).
- Do not add local-dev personas for the three roles.
- Do not re-implement group resolution, claim reading, or `is_staff`/`is_superuser` derivation.
- Do not change what `provision_designated_groups` provisions; its existing callers (37 test call sites) must see identical behaviour.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Configured contract | all three `CPM_*_GROUP` set | `RoleContract.is_configured` True; three names returned stripped | No error expected |
| Partially configured | one or two of three set | `is_configured` False | No error expected |
| Blank value | a variable set to `"  "` / `"\n"` | read as unset; `is_configured` False | No error expected |
| Provisioning, configured | migration runs, contract configured | three `Group` rows exist; second run creates none | No error expected |
| Provisioning, unconfigured | migration runs, contract unset | no group created, no raise | Warning event logged, empty result returned |
| Two slots, one name | two role variables naming one group | one `Group` row, permissions unioned not clobbered | No error expected |
| Role asserted | claims assert a role group name | user holds that group after sync | No error expected |
| Role revoked | next claims omit it | group removed at that sync | No error expected |
| Group claim absent | configured group claim missing from token | `ClaimsRejected("group claim absent")` | Raised, logged with the claim name |
| Zero groups asserted | group claim present and empty | syncs normally to zero groups, no raise | No error expected |

</intent-contract>

## Code Map

- `src/config/authorization/claims.py` -- `CLAIMS_ENVIRONMENT_VARIABLES`, `ClaimsContract`, `load_claims_contract` (L45-128). The exact shape to mirror for the role contract: names-not-values, `env.str(name, default="").strip()`, no raise, an `is_configured` property. Read-only.
- `src/config/authorization/mapper.py` -- `sync_authorization` (L678-790). Already does all of AC1's resolution and all of AC3: it raises `ClaimsRejected(_GROUP_CLAIM_ABSENT)` on an absent claim (L710-720) and adds/removes only groups that resolve to existing rows (L727-750). Read-only — do not edit.
- `src/django_service/users/provisioning.py` -- the one group writer. `DESIGNATED_GROUP_PERMISSIONS` keyed by slot (L78-92), `_DesignatedGroup` (L113-119), `provision_designated_groups` (L122-193), `_designated_groups` union-by-name (L196-226), `_resolve_permissions` (L229-261). **Edit point:** extract a public `provision_groups(groups, apps=None)` taking a name -> codenames mapping; `provision_designated_groups` becomes a thin caller of it with unchanged behaviour.
- `src/django_service/users/migrations/0003_provision_designated_groups.py` -- the migration pattern to copy: hand-written, logic-free body, `elidable=False`, a `reverse` that deletes only the configured names.
- `src/django_apps/conda_package_supply_chain_monitor/core/` -- has `apps.py` (`CoreConfig`, no `ready()`), an empty `migrations/`, no models. **New files land here.**
- `src/config/settings/base.py` -- L12 `from config.authorization.claims import load_claims_contract`; L253 `CLAIMS_CONTRACT = load_claims_contract(env)`; L188-201 `LOCAL_APPS` already names `conda_package_supply_chain_monitor.core`. **Edit point:** the same two lines for `ROLE_CONTRACT`.
- `src/config/settings/local.py` -- L156-166 fills only *unset* `CLAIMS_CONTRACT` fields with local values. **Edit point:** the same `or`-fill for `ROLE_CONTRACT`, values stripped before the test.
- `_bmad-output/planning-artifacts/briefs/.../brief.md` L38-42 -- the role table; the product-level source for the three slots. Read-only.
- `tests/unit/users/test_provisioning.py` -- L45-48 `CREATION_VERBS`, L240-253 the single-writer audit, L160-170 the no-hardcoded-names assertion, L256-268 the idempotence assertion. Constrains the design; extend rather than weaken.
- `tests/unit/authorization/test_claims.py` -- the assertion shapes to mirror for the role contract (partial config, blank-reads-as-unset, loading never raises).
- `tests/integration/authorization/test_mapper_sync.py` L100-115 -- how an integration test seeds groups through `provision_designated_groups` and drives a sync. The template for the AC1/AC3 integration test.
- `tests/integration/users/test_provisioning.py` L239-270 -- how the migration's `reverse` is imported and exercised directly.
- `docs/authentication.md` L54-66, L89-93 -- the operator-facing env-var table and the provisioning paragraph. **Edit point:** add the three variables and the role-group paragraph.

## Tasks & Acceptance

**Execution:**

- `src/django_apps/conda_package_supply_chain_monitor/core/roles.py` -- new. Declare three role slots as `Final` constants (`SECURITY_REVIEWER`, `PACKAGING_ENGINEER`, `LEADERSHIP`), `ROLE_ENVIRONMENT_VARIABLES` in field order (`CPM_SECURITY_REVIEWER_GROUP`, `CPM_PACKAGING_ENGINEER_GROUP`, `CPM_LEADERSHIP_GROUP`), a frozen slots-`True` `RoleContract` with the three name fields and `is_configured`, `load_role_contract(env)` mirroring `load_claims_contract`, `ROLE_GROUP_PERMISSIONS` keyed by slot (all three empty for now — grants arrive with the surfaces in `CPM-EP-APP`, and a decorative grant drifts into a load-bearing one), and `role_group_permissions(contract)` returning the name -> codenames mapping with names unioned so two slots pointing at one group do not clobber each other. No group name appears in the module. Imports nothing from `django.contrib.auth` and nothing from `django.apps` -- it is imported at settings-import time.
- `src/django_service/users/provisioning.py` -- extract `provision_groups(groups: Mapping[str, Sequence[str]], apps: StateApps | Apps | None = None) -> ProvisionResult` holding the existing registry lookup, `get_or_create`, `permissions.set` and `authorization.groups_provisioned` event; an empty mapping returns an empty result and creates nothing. Reduce `provision_designated_groups` to the contract read, the unconfigured guard, `_designated_groups`, and a delegation. Behaviour for existing callers is unchanged -- this is the seam that keeps group creation to one module.
- `src/config/settings/base.py` -- import `load_role_contract` from `conda_package_supply_chain_monitor.core.roles` and set `ROLE_CONTRACT = load_role_contract(env)` beside `CLAIMS_CONTRACT`, with no default value for any name. Comment why the product's contract is read here rather than in the app (FR-38's single `.env` read).
- `src/config/settings/local.py` -- fill only unset `ROLE_CONTRACT` fields with stripped local development values, in the same shape and with the same reasoning as the `CLAIMS_CONTRACT` fill; do not re-spell the variable names.
- `src/django_apps/conda_package_supply_chain_monitor/core/migrations/0001_provision_role_groups.py` -- new, hand-written, no logic of its own. `forward` reads `settings.ROLE_CONTRACT`, returns early when it is unconfigured, and otherwise calls `provision_groups(role_group_permissions(contract), apps)`. `reverse` deletes only the configured role group names, and nothing when unconfigured. `elidable=False`, dependencies on `("auth", "0012_alter_user_first_name_max_length")` and `("users", "0003_provision_designated_groups")` so the one writer's own migration has already run.
- `tests/unit/django_apps/test_roles.py` -- new. Cover the first three I/O matrix rows plus: the slot constants are distinct, `ROLE_ENVIRONMENT_VARIABLES` matches the fields in order, `role_group_permissions` unions two slots onto one name, loading never raises, and an AST or text assertion that no configured group name is hardcoded in `roles.py`.
- `tests/unit/django_apps/test_role_migration.py` -- new. Assert the migration is non-elidable, that it declares both dependencies, and that it creates no `Group` row of its own (reuse the `CREATION_VERBS` scan shape from `tests/unit/users/test_provisioning.py`).
- `tests/unit/users/test_provisioning.py` -- extend for the new seam: `provision_groups` with an empty mapping creates nothing and raises nothing; the single-writer and idempotence audits still name only this module.
- `tests/unit/test_settings.py` -- assert `base` reads all three role variables from the environment and defaults none, and that `local` fills only what the environment left unset (mirroring the existing `CLAIMS_CONTRACT` cases at L156-188 and L341-368).
- `tests/integration/django_apps/test_role_groups.py` -- new, `@pytest.mark.integration` by directory. Cover the remaining I/O matrix rows: provisioning creates the three rows and is idempotent; an unconfigured contract provisions nothing without raising; two slots naming one group produce one row; a user whose claims assert a role group holds it after `sync_authorization` and loses it when the next claims omit it; an absent group claim raises `ClaimsRejected` while a present-but-empty claim syncs to zero groups.
- `docs/authentication.md` -- document the three variables in the existing table and state that the role groups are provisioned by `core/0001_provision_role_groups` through the same single writer.

**Acceptance Criteria:**

- Given the platform already syncs asserted group claims to Django groups, when the three product role groups are provisioned by migration as the platform provisions its designated groups, then a person whose claims assert a role group holds that role at their next authentication, and a group revoked at the provider removes the role at the next resolution.
- Given a role group name is configured, when the configuration is read, then it comes from the environment and has no default value baked into the settings module.
- Given an authentication asserts no group claim at all, when authorization is resolved, then it is refused, and that refusal is distinguishable from an authentication asserting zero groups.
- Given the whole change, when `pixi run ci` runs, then it exits 0 with coverage at or above the 90% floor and the single-writer audit still names `src/django_service/users/provisioning.py` alone.

## Spec Change Log

## Review Triage Log

### 2026-09-03 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 21: (high 1, medium 7, low 13)
- defer: 2: (high 0, medium 1, low 1)
- reject: 3: (high 0, medium 0, low 3)
- addressed_findings:
  - `[high]` `[patch]` A role group name colliding with a designated group name cleared that group's
    permissions on every migrate, and `reverse` deleted the shared row outright. `provision_groups`
    gained a keyword-only `preserve_existing`; the role migration passes it and `reverse` subtracts the
    claims contract's names. Two integration cases added and mutation-checked — each fails with its
    guard removed.
  - `[medium]` `[patch]` The migration's unconfigured path emitted no event where the platform's logs
    `authorization.provisioning_skipped`. Mirror event added with `reason="role_contract_unconfigured"`
    and asserted through `structlog.testing.capture_logs()`.
  - `[medium]` `[patch]` Nothing asserted that holding a role group confers neither `is_staff` nor
    `is_superuser`. Added, parametrized over all three slots, against both the outcome and the row.
  - `[medium]` `[patch]` `CPM_` was missing from `tests/settings_import.py`'s `CONFIGURATION_PREFIXES`,
    so two local-settings tests could pass on a leaked ambient variable. Prefix added and both tests
    pinned to named constants.
  - `[medium]` `[patch]` The migration's `forward` happy path was never driven, and migrations are
    excluded from coverage. Two cases added, one spying on the writer to prove `apps` is passed through.
  - `[medium]` `[patch]` Nothing pinned `settings.ROLE_CONTRACT` to the `test.py` fixture every other
    case depends on. Mirror of the existing claims assertion added.
  - `[medium]` `[patch]` `docs/authentication.md` omitted the operational consequences: no startup
    refusal, never `[activation.env]`, a role-only holder has no access today, and a `CPM_*` rename
    after migrate silently does nothing. All four added; the migration path corrected.
  - `[low]` `[patch]` Thirteen corrections and cleanups: stale `provision_designated_groups` and
    "designated" wording in the docs and docstrings; a tautological `is not None` assertion; the
    membership cascade stated in `reverse`; unexplained `initial = True` dropped; the AST helper lifted
    to `tests/group_writers.py` instead of a cross-module private import; paths resolved from
    `module.__file__`; the redundant `.strip()` in `local.py` removed to match its sibling block;
    `is_configured` and `role_group_permissions` strip before testing; `declared_by` added to
    `authorization.groups_provisioned`; the dropped `roles=` field recorded as deliberate; a
    hardcoded-name scan added for the migration; an inaccurate comment in `test.py` corrected; and an
    AST import scan pinning `roles.py`'s load-bearing import-freedom.

## Design Notes

**Why the platform module is edited at all.** Group creation has exactly one call site by
design (`AD-27`), and an AST audit over all of `src/` enforces it. The product therefore
cannot own a writer of its own, and `provision_designated_groups` provisions only the two
claims-contract groups. Extracting `provision_groups` is the smallest change that lets the
product provision through the one writer without changing what any existing caller gets.
The alternative — teaching `provision_designated_groups` about product roles — would put
product concepts into the reusable platform and change behaviour under 37 existing call sites.

**Why role groups carry no permissions yet.** `core` has no models and the product has no
views, so every codename would resolve to nothing and be logged as unresolved on every
migrate. `SUPERUSER_ROLE`'s deliberately empty tuple is the precedent. Role membership is
the fact this story establishes; `CPM-AD-13`'s permission classes read it later.

**Why no startup refusal.** `CG-3` governs how a refusal is spelled, not that one must be
added. The platform's own answer for an unconfigured contract is log-and-skip in provisioning
plus a stage-one refusal to *serve*; adding a stage-one condition here would pull three new
variables into `BUILD_SCAFFOLDING_VARIABLES`, the `Dockerfile` build stage and every deployed
import test — scope this story does not carry.

**Shape to mirror, from `claims.py`:**

```python
ROLE_ENVIRONMENT_VARIABLES: Final[tuple[str, ...]] = (
    "CPM_SECURITY_REVIEWER_GROUP", "CPM_PACKAGING_ENGINEER_GROUP", "CPM_LEADERSHIP_GROUP",
)

def load_role_contract(env: environ.Env) -> RoleContract:
    reviewer, packaging, leadership = (env.str(n, default="").strip() for n in ROLE_ENVIRONMENT_VARIABLES)
    return RoleContract(security_reviewer=reviewer, packaging_engineer=packaging, leadership=leadership)
```

## Verification

**Commands:**
- `pixi run test` -- expected: the new unit tests pass; run it after each file, not once at the end.
- `pixi run fmt && pixi run lint && pixi run check` -- expected: clean; strict mypy over `src/`.
- `pixi run test-integration` -- expected: the new role-group integration tests pass and no existing provisioning, mapper-sync, local-dev or startup test regresses.
- `pixi run python manage.py makemigrations --check --dry-run` -- expected: no missing migration.
- `pixi run ci` -- expected: exit 0, coverage at or above 90.

## Auto Run Result

Status: done

### Implemented change

The product's three role groups now exist as `Group` rows and are granted by the identity
provider's group claims through the platform's inherited resolution, with no manual step.
A role contract read from the environment names the three groups; a `core` data migration
provisions them through the repository's single group-creation mechanism; the inherited
`sync_authorization` does all of the granting, revoking and refusing, unchanged. No
permission class, view, queue or startup refusal was added — those remain `CPM-EP-APP`'s.

### Files changed

- `src/django_apps/conda_package_supply_chain_monitor/core/roles.py` — new. Three role slots, their
  three `CPM_*_GROUP` environment variables, a frozen `RoleContract` with `is_configured`,
  `load_role_contract` (no defaults, stripped, never raises), and the slot-keyed permission
  declaration (all three empty until the surfaces exist). Names no group and imports no Django app
  registry or auth model.
- `src/django_apps/.../core/migrations/0001_provision_role_groups.py` — new. Non-elidable, logic-free;
  provisions through `provision_groups` with `preserve_existing=True`, logs and returns on an
  unconfigured contract, and reverses only names the claims contract does not designate.
- `src/django_service/users/provisioning.py` — `provision_groups` extracted as the one writer, taking
  names rather than a contract, with `declared_by` and `preserve_existing`. `provision_designated_groups`
  is now its claims-contract reader; what it provisions is unchanged.
- `src/config/settings/base.py` — reads `ROLE_CONTRACT` from the environment, defaulting nothing.
- `src/config/settings/local.py`, `test.py` — locality fills of only the fields the environment left unset.
- `docs/authentication.md` — the three variables, the shared-group case, and the four operational
  consequences an operator cannot infer from the claims section.
- `tests/group_writers.py` — new shared AST helper for the group-creation scan.
- `tests/settings_import.py` — `CPM_` added to `CONFIGURATION_PREFIXES`.
- `tests/unit/django_apps/test_roles.py`, `test_role_migration.py`, `tests/integration/django_apps/test_role_groups.py` — new.
- `tests/unit/test_settings.py`, `tests/unit/users/test_provisioning.py` — extended.

### Review findings breakdown

- Patches applied: 21 (high 1, medium 7, low 13).
- Items deferred: 2 (the 150-character `Group.name` exposure, pre-existing and shared with the claims
  contract; `--reuse-db` staleness on the migration-output test).
- Items rejected: 3 (speculative future-caller guards and an over-strict documentation grep).

### Follow-up review recommendation

`true`. Patched findings by severity: high 1, medium 7, low 13. The rule fires on the high-severity
patch alone; the weighted score is `3 × 7 + 1 × 13 = 34`, also at or above 5.

### Verification performed

- `pixi run ci` — exit 0. 1626 passed, coverage 97.09% against a 90% floor.
- `pixi run python manage.py makemigrations --check --dry-run` — "No changes detected".
- `pixi run fmt`, `lint`, `check` — clean (mypy strict, 80 files).
- The high-severity fix was mutation-checked independently of the implementer: with
  `permissions.add` reverted to `set` and the designated-name exclusion removed from `reverse`,
  `test_provisioning_a_role_group_never_clears_a_designated_groups_permissions` and
  `test_the_migration_reverse_never_deletes_a_designated_group` both fail; both pass restored.
- The I/O matrix audit found one uncovered row — partial configuration was parametrized over
  one-of-three only — and it was closed by widening the case to every one- and two-name subset.

### Residual risks

- **A role group carries no permissions, so a role is a membership and nothing more today.** Every
  authorization decision still treats a role holder and a role-less person identically. The story
  scopes it that way deliberately, but `CPM-FR-30`'s "grants its role" is only half-observable until
  `CPM-EP-APP` adds the permission classes.
- **Nothing refuses to start on an unconfigured role contract.** A deployment that sets none or only
  some of the three variables provisions no role groups and starts normally; the only signal is the
  `authorization.provisioning_skipped` warning at migrate time. Deliberate — the refusal was out of
  scope — but it is an asymmetry with the claims contract, which stage one and stage two both enforce.
- **A `CPM_*` rename after the migration has been applied silently does nothing.** The contract has no
  runtime reader, so the new group is never provisioned and the stale row is never removed. Documented,
  not mechanised.
- **`preserve_existing=True` means the role contract cannot revoke a permission by omission.** It is
  the correct trade for a secondary declaration sharing a row, but whoever later gives role groups real
  permissions has to remove them explicitly.
- **The tests drive `sync_authorization` directly**, one layer below the deployed entry points. On the
  Bearer path `sync_once_per_epoch` syncs only at the first sighting of a `jti`, so "removed at the next
  resolution" is in practice "at the next epoch" — the inherited `R-2` consequence, unchanged by this
  story and not newly verified by it.
