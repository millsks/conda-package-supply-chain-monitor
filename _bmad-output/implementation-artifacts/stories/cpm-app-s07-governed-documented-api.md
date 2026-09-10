# CPM-APP-S07: A governed, documented API

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

## Story

As a integrator,
I want the same reads available over HTTP with a published schema,
so that automation uses the product's own contract rather than the database.

## Acceptance Criteria

1. **Given** the API
   **When** it is exposed
   **Then** current-health, package-detail and report reads are available
   **And** the schema is generated from the implementation, not maintained by hand

2. **Given** any collection endpoint
   **When** it is called
   **Then** it is paginated with a maximum page size

3. **Given** the API in v1
   **When** its writes are enumerated
   **Then** the only writes are the package-identity override and queue actions
   **And** no endpoint writes evidence or a derived status

4. **Given** an API request
   **When** authorization is evaluated
   **Then** the same role scoping as the application applies

5. **Given** a derived status on any API response
   **When** it is serialized
   **Then** it is emitted verbatim as its `OutcomeState` value, and never maps to `null`,
   `""` or a boolean (`APP.07-API-001`)

## Tasks / Subtasks

- [x] `core/serializer_fields.py` — `StatusField`, where AC 5 lives.
- [x] `surface/listing.py` — the one health queryset, shared with the screen.
- [x] `surface/api/` — the four reads; `surface/reports.py` split for pagination.
- [x] `identity/api/`, `workflow/api/` — the two writes; typed refusals in the services.
- [x] `config/api_router.py` — every route, in one file.
- [x] `config/settings/base.py` — the schema names this product; enum override.
- [x] `tests/unit/django_apps/test_api_contract_audit.py` and `test_report_projection.py`.
- [x] `tests/integration/django_apps/test_api.py`.
- [x] `docs/development.md`.

## Dev Notes

**Satisfies:** `CPM-FR-27`

**Governed by:**

- `CPM-AD-9` — The request/task boundary
- `CPM-AD-10` — Derived state is read-only to the application
- `CPM-AD-12` — Pagination is structural  *(net-new: no pagination is configured today)*
- `CPM-AD-13` — Authorization is declared per surface, enforced centrally
- `CPM-AD-24` — Every read surface projects the same values

**Test design.** Bound by the TEA system-level test design:

- Test IDs: `APP.07-API-001`
- Risks this story closes: `R-01`

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

- [Source: _bmad-output/planning-artifacts/epics.md#CPM-APP-S07]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-9]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-10]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-12]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-13]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-conda-package-supply-chain-monitor-2026-09-02/ARCHITECTURE-SPINE.md#CPM-AD-24]
- [Source: _bmad-output/planning-artifacts/prds/prd-conda-package-supply-chain-monitor-2026-09-02/prd.md#CPM-FR-27]
- [Source: _bmad-output/test-artifacts/test-design/conda-package-supply-chain-monitor-handoff.md]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**Four of the five criteria are claims about the API as a whole**, and a claim about a
whole is not tested by testing one endpoint. "The only writes are two" is false the
moment a third arrives, and the third arrives in a module nobody thought to add a
test to. So `tests/unit/django_apps/test_api_contract_audit.py` reads its subject off
the URL resolver, the serializer registry and the settings — not off a roster
somebody maintains.

**Files added:** `core/serializer_fields.py`, `surface/listing.py`, `surface/api/`
(serializers, views), `identity/api/`, `workflow/api/` (serializers, views,
permissions), and three test modules.

**Files changed:** `config/api_router.py` (rewritten), `config/settings/base.py`,
`surface/views.py`, `surface/reports.py`, `identity/services.py`,
`tests/unit/django_apps/test_permission_audit.py`, `test_identity_app.py`.
**No migration and no model change.**

**Each acceptance criterion:**

- **AC 1 (three reads, schema generated).** Four endpoints, not three — the report
  *roster* is published as data so a seventh report reaches an integrator without a
  client release. The schema is drf-spectacular's, and the case asserts this story's
  own paths appear in the generated document rather than that it parses.
- **AC 2 (paginated, with a maximum).** The endpoints assert this by **declaring
  nothing**: `CPM-AD-12` puts the bound in `REST_FRAMEWORK` and a generic view
  inherits it. The audit checks the other half — that every product read *is* a
  generic view, because a hand-rolled `APIView` returning a list is how a global
  pagination setting stops reaching anything.
- **AC 3 (two writes).** Enumerated in `config/api_router.py` as two named lists, and
  swept off the resolver. The platform's `/api/users/{username}/` is **recorded**
  rather than filtered away: it writes, it is not this product's, and what matters
  about it — that it reaches no evidence and no derived table — is asserted.
- **AC 4 (the same role scoping).** The same `RolePermission` classes the screens
  use. The queues resolve theirs from `QUEUE_OWNERS` per request, and the audit calls
  that resolution for each of the three rather than accepting the override as proof.
- **AC 5 / `APP.07-API-001`.** `StatusField` — a `CharField` that refuses
  `allow_null`, `allow_blank` and `required=False` as `TypeError` at class-build
  time, and **raises** rather than emitting a falsy value. The sweep asserts every
  status-named field in every serializer is one.

**Three decisions worth recording.**

*`surface/listing.py` exists because the API was about to be a second queryset.* The
health list needed the same filters, annotations and ordering as the screen. Written
twice they agree on the day they are written and drift on the first day somebody
changes one — which is `CPM-AD-24`'s named failure with extra steps. The API also
serializes the *dataclasses* `health_rows` and `traces_for` produce, not models, so
there is nothing for it to project differently.

*Two refusals in `identity/services.py` acquired types.* Its docstring said there was
no hierarchy because no caller branched, which was true while the only caller was a
management command. An HTTP surface has to: an actor the product will not accept is
403, a package id naming nothing is 404, and a correction it will not accept is 400.
Matching on the message would have worked and would have broken the first time
somebody improved the wording.

*`test_permission_audit.py` learned the DRF seam.* It already accepted
`roles_required` on a Django view; `get_permissions` is the same seam for a DRF one.
A static sweep can only see the override, so the rule itself — that each queue's
permission requires that queue's owner — is a named case.

**Three things found by running it, and one by a test.**

1. **`/api/schema/` answered 404 for the whole document.** `queue_permission` raised
   `NotFound` from inside `get_permissions`, which drf-spectacular calls during schema
   generation with no URL kwargs. Introspection is not a request. The refusal moved to
   `initial()`; the permission now returns a deny-all for an unknown queue, so it fails
   closed if the 404 in front of it is ever removed. Caught by the platform's own
   schema test.
2. **A JSON API returned an HTML error page.** `?vuln=nonsense` correctly answered
   400 — as a Django debug page, because `health_queryset` raises Django's
   `BadRequest` and DRF does not handle it. The *status* was never wrong, which is
   exactly why no assertion about the status would have found it.
3. **A stale package id answered 400 saying the reason was bad.** The URL pointed at
   nothing; that is a 404.
4. **The write sweep would have missed a `ModelViewSet`.** It asked
   `hasattr(view, "post")`, and a viewset defines `create`/`update`/`destroy` — the
   router maps them. So the audit would have reported a registered `ModelViewSet` as
   read-only, which is precisely the one-line diff it exists to catch. Found because
   the platform's user endpoint did not appear where it was expected.

**Coverage:** every new module at 100%.
