---
title: 'CPM-IDENTITY-S07: The watchlist is the inventory source'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_revision: '40ce5f9ec85e3dccd9c2210d005dd3e24579b87b'
context:
  - _bmad-output/planning-artifacts/epics.md
  - _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md
  - _bmad-output/implementation-artifacts/stories/cpm-identity-s06-inventory-arrives-arrives-as-evidence.md
warnings: ['oversized']
deferred:
  - summary: >-
      Amending the production watchlist requires a code change, a build and a redeploy, because
      the file is read from inside the wheel and its path is derived solely from locality.
    evidence: |-
      `INVENTORY_WATCHLIST_PATH` is `watchlist_path(local=is_local())` and nothing else, and the
      adapter reads that path relative to its own module -- which in a deployed component is
      inside the installed distribution. So populating the production watchlist, or adding one
      package to it, is a release. That is defensible while the file is governed reference data
      changed by review (`CPM-AD-14`, `CPM-AD-29`): review and release are the same gate. It stops
      being defensible the moment the inventory changes faster than the product ships. The
      mitigations -- an override path setting, a mounted file, or a second adapter reading from
      object storage -- are each a design decision `CPM-AD-29` anticipates ("a second adapter
      behind the same contract") and none is this story's to choose.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/watchlist.py -- watchlist_path
    severity: medium
  - summary: >-
      `(identity_source, associator_key)` is now the lookup key for a package shell and still
      carries no uniqueness constraint.
    evidence: |-
      This story moved `resolve_package_shell`'s `get_or_create` onto that pair, which is what
      makes the source key rather than the correctable name the stable join. Nothing yet enforces
      that the pair is unique, so two concurrent sweeps could race two rows into existence before
      either sees the other. Ingestion is a single sweep task today, so the race has no way to
      happen in practice. `CPM-IDENTITY-S02`'s story already carries the constraint as one of the
      five things that close this trap, and `Package` is not evidence so a `UniqueConstraint` on
      it is permitted -- it lands there rather than here because S02 owns what a resolution
      establishes.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/identity/services.py -- resolve_package_shell
    severity: medium
  - summary: >-
      The story's first criterion says the collector "carries no branch on which source is
      active", and nothing asserts it.
    evidence: |-
      It holds by construction: `CPM-IDENTITY-S06` gave the collector one opaque locator and one
      declared slot, and this story added an adapter behind that slot without touching the
      collector's sweep. So the claim is true and would stay true through an ordinary change --
      but it is a source-level property of the kind this repository normally pins with an audit,
      and the mechanical-verification effort in this story went to the `AD-4` import rule instead.
      The natural home is the collector-base audit, beside the other tree-wide sweeps.
    location: >-
      src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py -- InventoryIngestionCollector
    severity: low
---

<intent-contract>

## Intent

**Problem:** `CPM-IDENTITY-S06` built the ingestion collector and left the adapter slot empty.
Nothing in `src/` calls `declare_inventory_adapter`, so `cpm.collect.inventory` refuses on every
invocation and the product has no inventory. `CPM-AD-29` says the source is a **declared adapter**
reading a **versioned watchlist**, with **locality selecting the file and failing closed toward
production** — because a deployed component that read the development subset would record every
package outside it as absent, permanently, in a log nothing may correct.

**Approach:** Ship the watchlist column contract, a CSV adapter that turns a reviewed file into the
record document S06's collector already consumes, the locality selection rule, the refusals, and
two files — a development subset a developer can actually run against, and a production watchlist
carrying its header and awaiting review. The read of locality happens where locality is legible,
on the `config` side; the app owns the contract and the selection function and imports no `config`.

## Boundaries & Constraints

**Always:**

- The adapter is a `Transport` substitution at the collector base's seam and nothing else
  (`CPM-AD-29`, `CPM-AD-27`). It implements `fetch(source, *, headers=None) -> Payload` and returns
  `Payload(source=<the locator it was handed>, found=True, body=<the record document>,
  status_code=None)`. `status_code=None` is what "this source does not speak HTTP" means.
- The adapter **ignores the locator it is handed**. `INVENTORY_SOURCE` is
  `"inventory://declared-adapter"` — deliberately opaque, naming the run rather than addressing a
  resource. The file it reads comes from its own construction, never from `source`.
- The adapter accepts and ignores `headers`; the parameter exists for exactly this case.
- **Nothing under `src/django_apps/` imports `config`** (inherited `AD-4`). The app owns the
  column contract, the file names and a pure selection function taking a boolean; the read of
  `config.locality.is_local()` happens in `src/config/settings/base.py`, in the shape
  `core/roles.py` and `base.py:282`'s `ROLE_CONTRACT = load_role_contract(env)` already establish.
- **Selection fails closed toward production.** Only `COMPONENT_RUNTIME` equal to `local`, after
  stripping and lowercasing, selects the development subset. Absent, empty and unrecognized all
  read the production watchlist (`CPM-AD-29`).
- Adapters are **declared, never discovered** (inherited `AD-8`): no entry point, no module scan,
  no import walk. The declaration is one call in `CollectorsConfig.ready()`, guarded for
  idempotence the way the collector registration beside it already is — `declare_inventory_adapter`
  refuses a second declaration, and a `ready()` that ran twice would otherwise abort boot.
- **The watchlist files live under `src/django_apps/conda_package_supply_chain_monitor/collectors/`**
  and are read at a path relative to that package's `__file__`. `pyproject.toml`'s
  `only-include = ["src"]` means a file anywhere else is absent from the wheel while
  `pixi run build` still succeeds — the failure would arrive only in a deployed container. Never
  compute the path from `BASE_DIR`: the `src/` segment does not exist in the wheel layout.
- Every refusal names the file and, where a row is at fault, the line number.
- `pixi` is the only runner. The task names here are `test`, `test-integration`, `test-cov`,
  `typecheck`, `lint`, `ci`, `gate-postgres`.

**Block If:**

- Satisfying the selection rule appears to require importing `config` from a domain app, or
  reading `django.conf.settings` at module scope in one.
- The watchlist contract cannot carry a package name without changing something outside this
  story's reach beyond `InventoryRecord`, `RECORD_FIELDS` and `resolve_package_shell`'s shell
  creation.

**Never:**

- Do **not** change the ingestion collector's sweep, its declarations, its per-package transaction
  or its absence handling. Those are `CPM-IDENTITY-S06`'s and are settled.
- Do **not** let the watchlist assert a mapping. A column naming a repository URL, a feedstock, a
  purl or a confidence is refused, not ignored — ingestion never asserts a mapping
  (`CPM-FR-42`, `CPM-FR-1`).
- Do **not** invent watchlist *content* beyond the development subset. Which packages are tracked,
  and their breadth counts, is an organizational decision. The production watchlist ships with its
  header and no rows.
- Do **not** add a management command, a runnable entry point or a second ingestion path.
  `CPM-EVIDENCE-S05`'s manual recollection already bypasses the observation window.
- Do **not** add a startup refusal in `src/config/startup/`. That would pull in
  `forbidden_states.py`, `UNCONDITIONAL_STATE_COUNT`, `UNCONDITIONAL_CONDITIONS` and
  `test_no_softening.py`'s `REFUSALS` table, and this story's refusals are the adapter's, at run
  time, not the platform's, at boot.
- Do **not** add a dependency. `csv` is in the standard library.
- Do **not** add a `pragma`, a coverage omit entry, a `pytest.skip`, or `databases=` on `django_db`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| A well-formed row | a row carrying all eight columns populated | one record with the key, the name, both counts and all four optional signals | No error expected |
| Blank optional signals | a row whose `apps`, `platforms`, `downloads`, `versions` cells are empty | the record yields those four as missing, distinguishable from zero | No error expected |
| A zero optional signal | a row whose `downloads` cell is `0` | the record yields `0`, which does not read as missing | No error expected |
| An undefined column | a header carrying `feedstock_url` alongside the eight | the run is refused before any record is yielded, and the message names the column | `ImproperlyConfigured` |
| A missing required column | a header with no `internal_lob_count` | refused, naming the column | `ImproperlyConfigured` |
| A non-numeric count | a row whose `internal_component_count` is `many` | refused, naming the file, the line and the column | `ImproperlyConfigured` |
| A repeated key | two rows sharing a `source_package_key` | refused, naming the key | `ImproperlyConfigured` |
| An unreadable file | the selected file does not exist | refused, naming the path it looked for | `ImproperlyConfigured` |
| A header-only file | the production watchlist as shipped, no rows | refused — an inventory naming nothing is a misconfiguration, not an empty inventory | `ImproperlyConfigured` |
| Locality is local | `COMPONENT_RUNTIME=local` | the development subset is selected | No error expected |
| Runtime absent | `COMPONENT_RUNTIME` unset | the production watchlist is selected | No error expected |
| Runtime empty | `COMPONENT_RUNTIME=""` | the production watchlist is selected | No error expected |
| Runtime unrecognized | `COMPONENT_RUNTIME=dev` | the production watchlist is selected | No error expected |
| The development subset ingests | the shipped subset against an empty database | every row becomes a `Package` at `unmapped` confidence with a snapshot carrying both required signals | No error expected |

</intent-contract>

## Code Map

- `src/django_apps/conda_package_supply_chain_monitor/collectors/tasks.py:283` `declare_inventory_adapter`,
  `:320` `withdraw_inventory_adapter`, `:344` `inventory_adapter` — the slot. `:146`
  `INVENTORY_SOURCE`, the opaque locator. `:152-166` `SOURCE_PACKAGE_KEY`, `REQUIRED_SIGNALS`,
  `OPTIONAL_SIGNALS`, `RECORD_FIELDS`. `:250` `InventoryRecord` — **no name field today**. `:368`
  `records_in` and its refusals at `:393`, `:400`, `:412` (empty array), `:447`, `:453`, `:461`,
  `:472`, `:522`, `:581`, `:615`.
- `core/transport.py:359` `Transport` — one method, `fetch(source, *, headers=None) -> Payload`,
  `runtime_checkable` so the declaration check only sees the method name. `:299` `Payload`:
  `source`, `found`, `body` required; `status_code=None` documented as meaning the source does not
  speak HTTP, naming this adapter as the first such case.
- `src/config/locality.py:84` `is_local()` — reads `os.environ` at call time, `LOCAL = "local"` is
  the one recognized value, everything else is deployed. `:68` `RUNTIME_ENV_VAR`.
- `src/django_apps/conda_package_supply_chain_monitor/core/roles.py:69,:94,:140` and
  `src/config/settings/base.py:13,:282` — the template: the app owns the shape and the pure
  function, settings owns the read. `base.py:265-281` states the rule in prose.
- `collectors/apps.py:47-79` `CollectorsConfig.ready()` — function-scope imports to dodge
  `AppRegistryNotReady`, and an existing idempotence guard on the collector registration. The
  declaration goes here.
- `identity/services.py:144` `resolve_package_shell(*, source_package_key, identity_source, clock)`
  and `:183`, which sets `canonical_name=source_package_key.strip()`. `:115`
  `CANONICAL_NAME_LENGTH`, read off the model.
- `src/config/component/loader.py` — the repository's one precedent for reading a reviewed data
  file at a `__file__`-relative path and turning every malformed input into `ImproperlyConfigured`
  naming the file and the offending key. `:91` shows the path idiom.
- `pyproject.toml:237-244` — `only-include = ["src"]`, `dev-mode-exact`, and the `sources` mapping
  that strips `src/django_apps` so a file under `collectors/` lands in the wheel beside its module.
- `tests/collectors.py:282` `RecordedTransport` — the double an adapter is measured against.
- **Read-only:** `src/config/startup/` — no condition is added there. `tests/unit/startup/` and its
  `forbidden_states.py` roster are untouched; the startup audits scan only `src/config/startup/`,
  so a domain-app refusal is outside them.

## Tasks & Acceptance

**Execution:**

- `collectors/watchlist.py` — new. The column contract, `watchlist_path(*, local: bool) -> Path`
  (pure, no `config` import, no environment read), the CSV adapter implementing `Transport`, and
  every refusal.
- `collectors/tasks.py` — widen `InventoryRecord` and `RECORD_FIELDS` with the package name the
  epic's contract carries, and let `records_in` require it. This is the one change to S06's
  contract, and it is this story's to make: the epic puts the record's shape on S07's side.
- `identity/services.py` — `resolve_package_shell` takes the name for `canonical_name` and keeps
  the source key for `associator_key`, so the two stop being the same value.
- `collectors/data/watchlist.csv` and `collectors/data/watchlist-development.csv` — new. The
  production file carries its header and no rows; the development subset carries of the order of a
  hundred real conda-forge package names with plausible breadth counts.
- `collectors/apps.py` — declare the adapter in `ready()`, idempotently, reading the selected path
  from settings.
- `src/config/settings/base.py` — `INVENTORY_WATCHLIST_PATH = watchlist_path(local=is_local())`,
  in the `ROLE_CONTRACT` shape, with the `config.locality` import.
- `tests/unit/django_apps/test_watchlist.py` — new. The column contract, every refusal, and the
  selection rule under `monkeypatch.setenv`/`delenv`. No database, no filesystem beyond `tmp_path`.
- `tests/integration/django_apps/test_watchlist_ingestion.py` — new. The shipped development
  subset ingested end to end.

**Acceptance Criteria:**

1. Given the ingestion task with the adapter declared, when it runs, then it resolves exactly one
   adapter and calls it, and the collector's source code contains no branch on which source is
   active.
2. Given `collectors/watchlist.py` and `collectors/apps.py`, when their imports are swept, then
   neither names `config`, and no module under `src/django_apps/` imports it at module scope.
3. Given `watchlist_path`, when it is called with `local=True` and `local=False`, then it returns
   the development subset and the production watchlist respectively — and composed with
   `is_local()` under `COMPONENT_RUNTIME` absent, empty and set to an unrecognized value, all three
   return the production watchlist, each asserted separately.
4. Given the built wheel, when its contents are listed, then both watchlist files are present
   under `conda_package_supply_chain_monitor/collectors/data/`.
5. Given the development subset, when it is ingested into an empty database, then every row becomes
   a `Package` at `unmapped` confidence carrying one snapshot with both required signals, and the
   package's `canonical_name` is the row's name while its `associator_key` is the row's source key.

## Spec Change Log

## Review Triage Log

### 2026-09-05 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 25: (high 3, medium 10, low 12)
- defer: 3: (high 0, medium 2, low 1)
- reject: 8: (high 0, medium 1, low 7)
- addressed_findings:
  - `[high]` `[patch]` The shell lookup was keyed on `canonical_name`, and this story created the
    exposure. Before it, the lookup was on `source_package_key`, which the adapter and the record
    contract both guarantee unique per document; `package_name` carries no such guarantee, so two
    rows with distinct keys and one name silently merged into a single package, the second key was
    discarded, and the run reported success. Three of the four review layers found it
    independently. `get_or_create` now keys on `(identity_source, associator_key)` with the name in
    create-only `defaults`, so a duplicate name reaches the `create` and `canonical_name`'s unique
    constraint refuses it — one record fails, the sweep carries on, the run is `partial`. A
    name-change case asserts the same row is found by key and is not silently rewritten.
  - `[high]` `[patch]` An integration test documented a mechanism that could not occur — it claimed
    a unique-constraint `IntegrityError` for duplicate names, which a name-keyed `get_or_create`
    never raises. The fix above makes the claim true, and the case now exercises it.
  - `[high]` `[patch]` A header carrying whitespace after its commas — what hand-editing a CSV
    produces — passed validation and then raised an unhandled `KeyError` out of the Celery task,
    because the header was validated stripped and the rows were keyed raw. `sweep` catches only
    `TransportError`, so nothing turned it into the `ImproperlyConfigured` this module promises.
    The parser now reads with `csv.reader` and keys rows positionally against the stripped header.
  - `[medium]` `[patch]` `csv.Error` escaped as a crash; now wrapped and named.
  - `[medium]` `[patch]` A UTF-8 BOM — what Excel produces on a reviewed CSV — was refused as one
    undefined and one missing column whose names print almost identically. Now `utf-8-sig`.
  - `[medium]` `[patch]` `splitlines()` stripped newlines inside quoted cells, defeating the
    module's own reasoning about cells spanning physical lines. Now read with `newline=""`, which
    also keeps `line_num` accurate.
  - `[medium]` `[patch]` Counts above the column ceiling, and over-long keys and names, slipped past
    the adapter and were refused later without naming the file or the line — against this story's
    own rule. All three are now refused at the row that caused them. The key's bound was also
    unfused from `canonical_name`'s: it lands in the wider `associator_key` now.
  - `[medium]` `[patch]` No test drove a malformed *file* through an actual run, though that is the
    exact path a component deployed with the shipped header-only watchlist takes on its first
    sweep — and `WatchlistError` is an `ImproperlyConfigured`, not a `TransportError`, so it takes
    a different route out. Two integration cases now assert the run fails leaving no package and no
    snapshot.
  - `[medium]` `[patch]` `ready()`'s guard could be weakened from `isinstance` to `is None` without
    failing anything, though its docstring called the discrimination the point. It now compares
    kind and path, with cases for a foreign adapter and for a watchlist adapter on another path.
  - `[medium]` `[patch]` `settings.INVENTORY_WATCHLIST_PATH` was read unguarded, so a settings
    module without it aborted boot with a bare `AttributeError`.
  - `[medium]` `[patch]` The chain this story is about was never composed: nothing observed
    `COMPONENT_RUNTIME` → `is_local()` → settings → declared adapter → a real run. One integration
    case now composes it, plus the fail-closed half.
  - `[medium]` `[patch]` The unit tier read shipped files off disk and called `ready()`, against the
    standard that parsing and refusal are unit tests over in-memory content. Parsing is now split
    from IO — `records_from(text, *, watchlist)` is pure — and the shipped-content assertions moved
    to the integration tier.
  - `[low]` `[patch]` Twelve smaller ones: the task's `Raises:` completed for the new escape route;
    a fixture annotated `Iterator[None]` with no `yield`; an unguarded `finally` that masked the
    real failure; a raw `OSError` from the module-path resolve; permuted-header and
    same-header-in-both-files cases; a re-read-on-every-fetch case; blank lines refused explicitly
    rather than silently skipped; a `README.md` beside the data documenting the column contract and
    stating the subset's counts are illustrative, with the magnitudes corrected; the repo-wide
    `AD-4` sweep moved to sit with the other tree-wide audits; a directory guard before `iterdir()`;
    AC-numbering made consistent; and a `docs/deployment.md` section on the unpopulated production
    watchlist.

## Design Notes

**The locality read, and why it is split in two.** `CPM-AD-29` says `config.locality.is_local()`
selects the file; inherited `AD-4` forbids a domain app importing `config`. `core/roles.py` already
resolves exactly this shape: the app declares the contract and a pure function, and
`config/settings/base.py` performs the read and assigns the result. So `watchlist_path(*, local)`
takes a boolean and knows nothing about the environment, and `base.py` calls
`watchlist_path(local=is_local())`.

The tension the story's own Testing Standards raise is real and is resolved by that split rather
than around it. `is_local()` reads `os.environ` at call time by design, and a settings-time read
freezes at import — so an integration test that toggles `COMPONENT_RUNTIME` afterwards would not
re-select. It does not need to: AC 3 composes the two in the test itself, asserting
`watchlist_path(local=is_local())` under each of the three fail-closed environment states. That
exercises the real `is_local()` under `monkeypatch.setenv`/`delenv` with nothing mocked, which is
what the standard asks for, and it does it without reloading settings.

**The package name is added to the contract, and that is this story's to do.** The epic says each
row yields "the source package key, **the package name**, `internal_component_count` and
`internal_lob_count`", and S06's `InventoryRecord` has neither the field nor a way to get one —
`resolve_package_shell` writes the source key straight into `canonical_name`. The epic puts the
record contract on S07's side ("S07 owns the adapter contract"), so widening it here is the story
working as designed rather than reaching into S06. It also pays down something real: S06's review
recorded that once `CPM-IDENTITY-S02` corrects a canonical name, a lookup keyed on that name creates
a duplicate shell. Separating the name from the stable key does not close that trap — S02 still
has to join on `(identity_source, associator_key)` — but it stops the two values being identical,
which is what made the trap invisible.

**Why CSV, and why the header is exact.** `CPM-AD-29` says a delimited file changed by review, and
a CSV header is the most legible thing to review in a pull-request diff. `csv.DictReader` gives two
of the four required refusals almost directly: `fieldnames` is the whole column set, so a missing
required column and an undefined column are both a set comparison. The header must be **exactly**
the declared columns, in any order — that is stricter than "no undefined columns" and makes both
refusals one rule. `csv` is standard library and the first use in `src/`; the repository's existing
data-file reads are all `read_text().splitlines()`, none of them delimited.

**The refusals are `ImproperlyConfigured`, and the boundary is deliberate.** AC 4 says so, and the
watchlist is governed reference data under `CPM-AD-14` — a malformed one is a misconfigured
deployment rather than a misbehaving remote source. That differs from S06's `InventoryRecordError`
for the wire document, and the split is the point: the adapter refuses a bad *file* before it ever
produces a document, and `records_in` refuses a bad *document* whoever produced it. The overlap on
duplicate keys is deliberate too — the adapter's message can name the line, and the wire contract
still refuses a duplicate from any future adapter. Note the startup audits
(`forbidden_states.py`, `test_no_softening.py`, `test_refusal_coverage_audit.py`) scan only
`src/config/startup/`, so raising `ImproperlyConfigured` from a domain app adds no roster entry —
verified, not assumed.

**A header-only production watchlist fails the run, and that is correct.** The story ships the
production file unpopulated because its content is an organizational decision. `records_in` already
refuses an empty document, for the reason S06's review made vivid: an inventory that names nothing
is indistinguishable from a source that has broken, and treating it as a clean sweep would mark
every package absent. So a component deployed before the watchlist is reviewed fails ingestion
loudly rather than corrupting the evidence log quietly. The adapter refuses it earlier and more
specifically, naming the file.

## Verification

**Commands:**

- `pixi run test` -- expected: exits 0.
- `pixi run test-integration` -- expected: exits 0, no new skips.
- `pixi run ci` -- expected: exits 0, coverage at or above 90%.
- `pixi run gate-postgres` -- expected: exits 0 with nothing newly skipped.
- `pixi run build` then list the wheel's contents -- expected: both watchlist files appear under
  `conda_package_supply_chain_monitor/collectors/data/`. This is the check that cannot be replaced
  by a unit test: the packaging failure is invisible to every other gate.

## Auto Run Result

Status: done

**What was implemented.** The inventory has a source. `CPM-IDENTITY-S06` built the ingestion
collector and left the adapter slot empty, so `cpm.collect.inventory` refused on every invocation;
this story fills it with the versioned watchlist `CPM-AD-29` names. A new `collectors/watchlist.py`
holds the eight-column contract, a pure `watchlist_path(*, local: bool)`, and `WatchlistAdapter` —
a `Transport` substitution at the collector base's seam that turns a reviewed CSV into the record
document S06's collector already consumes. Two files ship under `collectors/data/`: a development
subset of real conda-forge packages, and a production watchlist carrying its header and awaiting
review.

**Files changed.**

- `collectors/watchlist.py` — new. The column contract, the selection function, the adapter, and
  every refusal, each naming the file and — where a row is at fault — the line.
- `collectors/data/watchlist.csv`, `watchlist-development.csv`, `README.md` — new. The README is
  where the column contract lives for the reviewers who edit these files, since the exact-header
  rule leaves no room for a comment inside the data.
- `collectors/tasks.py` — the record contract gains the package name the epic's contract carries,
  plus `declared_inventory_adapter()`, the non-refusing slot read the boot guard needs.
- `identity/services.py` — `resolve_package_shell` takes the name for `canonical_name` and keys its
  lookup on `(identity_source, associator_key)`, so the join is on the stable value rather than the
  correctable one.
- `collectors/apps.py` — the adapter is declared once in `ready()`, guarded on kind and path.
- `src/config/settings/base.py` — `INVENTORY_WATCHLIST_PATH = watchlist_path(local=is_local())`,
  in the shape `ROLE_CONTRACT` already occupies.
- `docs/deployment.md` — the production watchlist ships empty, and ingestion fails until it is
  reviewed in.
- `tests/unit/django_apps/test_watchlist.py`, `tests/integration/django_apps/test_watchlist_ingestion.py`
  — new. Plus the wheel-contents assertion, the `AD-4` import sweep moved to the tree-wide audits,
  and mechanical updates where the record widened.

**Review findings:** 25 patched (3 high, 10 medium, 12 low), 3 deferred, 8 rejected. Four review
layers ran in parallel over the full 3,022-line diff.

**Follow-up review recommended:** true. Three high-severity patches.

**The finding that mattered most was one this story introduced.** Separating the package name from
the source key was meant to make a known trap *visible*: `CPM-IDENTITY-S06`'s review recorded that a
lookup keyed on the correctable `canonical_name` creates a duplicate shell the moment
`CPM-IDENTITY-S02` corrects a name. But the first implementation moved the name into
`canonical_name` and left the lookup keyed on it — so two watchlist rows with distinct keys and the
same name merged into one package, the second key was discarded, and the run reported success.
Making the trap visible had made it easier to hit. Three of the four review layers found it
independently, one of them by reading which uniqueness guarantees actually exist: the key is
guaranteed unique by two separate checks, the name by none. The lookup now keys on
`(identity_source, associator_key)`, which turns a duplicate name into an honest constraint
violation and a `partial` run.

**Verification.** `pixi run ci` exits 0 — 3728 passed, 2 pre-existing skips, coverage 98.29%, 100%
on every module this story touches. `pixi run gate-postgres` exits 0 against a throwaway
`postgres:17`. `pixi run build` followed by a listing of the wheel shows all three data files
present at `conda_package_supply_chain_monitor/collectors/data/` — the one check no test can
replace, because `only-include = ["src"]` means a misplaced data file is absent from the wheel while
every gate stays green. All fourteen I/O matrix rows have a covering test that ran and passed.

**Residual risks.** Three `deferred` entries, two of which matter. Amending the production watchlist
requires a code change, a build and a redeploy, because the file is read from inside the wheel and
its path derives solely from locality — defensible while review and release are the same gate, and
not once the inventory changes faster than the product ships. And `(identity_source,
associator_key)` is now the lookup key with no uniqueness constraint behind it; `CPM-IDENTITY-S02`
already carries that constraint as one of the five things closing this trap, and it belongs there
because S02 owns what a resolution establishes.
