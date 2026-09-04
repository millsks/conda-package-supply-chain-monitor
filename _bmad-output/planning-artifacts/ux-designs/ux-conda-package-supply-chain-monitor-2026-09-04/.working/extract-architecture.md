# Extraction: ARCHITECTURE-SPINE.md — surface invariants

Spine's own scope line (L712): `CPM-EP-APP | django_apps/reporting, workflow, config/api_router.py | CPM-AD-9-CPM-AD-14, CPM-AD-22, CPM-AD-24`

## The two write verbs — the whole interaction budget

**CPM-AD-10 (L290-297):** "the application layer holds no write path to a derived status or to evidence. Its only writes are workflow state (CPM-AD-22) and the package-identity override (CPM-AD-14). Serializers over derived models are explicitly read-only."

So the entire app surface has exactly **two write verbs**:
1. Advance a workflow item through a declared transition.
2. Override a package identity, with a reason.

Everything else is a read, or an enqueue that returns an in-progress state.

## CPM-AD-9 — the request/task boundary (L262-274)

A web request MAY: read derived state, read evidence, write workflow state, write an identity override.
A web request MAY NOT: make an outbound call, run a collector, run a policy pass, or build an export beyond `settings.CPM_SYNC_EXPORT_MAX_ROWS`.
Everything else is a Celery task and **the request returns an in-progress state**.
Celery inherited limits: 5-minute time limit, 60-second soft limit; work exceeding them is chunked per package, never raised.

## CPM-AD-11 — the read model (L299-309)

Current package health is a **Django-managed table**, one row per package, written by the orchestrating policy run. Explicitly **not** a materialized view — "it stays inside the migration graph and is ORM-filterable without raw SQL".

- **Exactly one row per inventory package, always**, including `unmapped` ones.
- Carries `computed_at`, the run's cut-off, and the **per-domain version map**.
- **"every view and export displays them"** — this is a UX requirement stated as an architecture invariant. Provenance is not a disclosure detail; it is mandatory chrome on every list, every detail page, every export.
- Only the rollup writer writes it. No policy pass writes the rollup.

**UX guarantee this buys us:** counts across filters sum to the inventory. No package can vanish from a filtered list because policy skipped it.

## What can be filtered and sorted — with cost

**Cheap (rollup columns, ORM-filterable directly):** every derived status, `computed_at`, cut-off, per-domain version map, `priority_bucket`, `rank`, `score`, `work_type`, `vulnerability_rollup`, `risk_level`, `latest_vuln_count`, `priority_description`/`priority_source`/`priority_reason`.

**Expensive (a join away):**
- `local_build_status`, `verified_at` — projected from **evidence**.
- `platforms`, `apps`, `downloads`, `versions`, `internal_component_count`, `internal_lob_count` — from **`inventory_snapshots`**, an append-only log where the correct read is "the latest snapshot at or before the cut-off".

**The spine does not settle how to filter/sort the expensive set.** Do not assume parity with rollup columns. Flag as an open question.

Note CPM-AD-1: none of the Appendix A.1 columns is a field on `Package`. `reporting` performs the projection **at read time**. The reporting projection maps **names only — never values, never formatting** (CPM-AD-24).

## CPM-AD-24 — every read surface projects the same values (L376-389)

Prevents "the export rendering `unknown` as a blank cell — destroying the five states in the one artifact that leaves the system."

- A derived status is emitted **verbatim as its `OutcomeState` value** on every surface: API, export, governed view.
- **Blank is reserved for a field with no value and is never used for a status.**
- PRD Appendix A.1's "blank means missing" applies to **identity fields only**.
- Every derived-status column in the rollup appears in the governed views, enforced by a test diffing the two column sets.

## CPM-AD-5 / CPM-AD-4 — what the UI renders

`core` defines one `OutcomeState` TextChoices with fixed lowercase values: `not_applicable`, `unknown`, `not_found`, `error`, plus determinate values. One total precedence order, defined once. The UI **may not invent a sixth state, may not collapse the five, may not re-label them at the value level.**

Confidence treatment (L165-181):
| `verified` | comparisons and recommendations shown normally |
| `inventory-derived` | **shown, with a confidence label. The value is not degraded** |
| `unmapped` | every gated status written as `unknown`; never current, never clean, never "no feedstock"; routed to review |

"`inventory-derived` sets a label the view renders; it never turns a determinate result into `unknown`." — an explicit UI mandate. Show the row, label it; do not hide or grey it out.

## ⚠⚠ CONTRADICTION: are queues role-exclusive?

**PRD CPM-FR-31 (prd.md:547-554):** "Read access to evidence is available to all three roles; **queues are role-exclusive**."
**epics CPM-APP-S05 / APP.05-API-004 (L1483-1486):** "**Given** a role **When** it opens a queue that is not its own **Then** access is refused, and the refusal is logged."
**spine CPM-AD-13 (L349-351):** "Read access to evidence is granted to all three roles; **queue write access is role-scoped per transition** (CPM-AD-22), **not per queue**, so **one item can legitimately be advanced by two roles in sequence**."

The spine explicitly rejects the one-role-per-queue reading. The PRD and epics assert it.

**Consequence if the spine wins:** the UI must compute *available actions* from the `(from_state, to_state, required_role)` transition table for the current user's role against the item's current state — NOT from "which queue am I in" and NOT from "which role am I". That is a materially different interaction model than a role-exclusive queue.

**This must be resolved before CPM-APP-S05 is written.** It is exactly the class of thing a UX contract exists to catch.

## CPM-AD-22 — the workflow app (L311-332)

One `workflow` app owns **all three queues** — identity review, remediation, compliance review — as **filtered views over one table, not three models**. The identity review queue lives here, not in `identity`, so it ranks by the same bucket-then-score rule.

- Keyed on a **finding key**: a re-observation-stable natural key declared alongside each evidence table. For a vulnerability: `package + advisory_id + affected_range`. **Never an evidence row id.**
- Transitions declared once as data — `(from_state, to_state, required_role)` — applied by one service function that locks with `select_for_update`, checks expected prior state, refuses on mismatch, appends the audit row in the same transaction.
- **Routing between queues changes the item's queue field. It never creates a second item.**
- Ranking is bucket then score for every queue; usage breadth is the score input for identity items.

**UX consequence:** a "sent to compliance review" item is the *same object* the remediation reviewer was looking at, carrying its history. An accepted finding stays accepted across re-observation.

## CPM-AD-23 — no optimistic UI

"Every privileged write and its audit row are one atomic unit written by one service function — never `transaction.on_commit`, never a follow-up task." `ATOMIC_REQUESTS=True` covers requests only.

→ **No optimistic UI that reports success before the audit lands.**

## CPM-AD-14 — the override path

Requires the override permission, requires a **non-empty reason**, writes an `identity_overrides` row (actor, timestamp, prior value, new value, reason) in the same transaction. An override is never downgraded by automated resolution.

## Layering

| Layer | Path | Depends on |
|---|---|---|
| Workflow | `src/django_apps/workflow/` | policies, identity |
| Application + API | `src/django_apps/reporting/` | policies, workflow (read-only) |

Dependency direction downward only. **Nothing imports `reporting`.**

"The application reads derived state and never computes it."

## CPM-AD-19 — where view code lives (L456-467)

Each domain is one Django app under `src/django_apps/`: `models.py`, `migrations/`, `tasks.py`, `apps.py`, an app-level `urls.py` with `app_name` **for any HTML views**, and an `api/` subpackage with `serializers.py` and `views.py`. The `api/` subpackage has **no** `urls.py` — DRF routing registered centrally in `config/api_router.py`.

**Templates and static stay at the `django_service/` package level** — NOT in the domain app.

## THE NAVIGATION_REGISTRY — a hard constraint on IA

Mentioned once in the spine (L114) as a contributable key. Real contract is the platform docstring at `src/config/startup/allowlist.py:324-345`:

> it is the one contributable key rendered on every page, and it is permitted where `MIDDLEWARE` and `AUTHENTICATION_BACKENDS` are refused because **it confers presentation and never authorization**. An entry is data, never markup — a label, a URL *name*, and an optional permission the renderer filters on — labels are auto-escaped, and no entry carries raw HTML. It is contributed to append-only in adopted-app-list order.

Consequences for the IA:
1. An entry is a triple: label string (auto-escaped), **URL name** (not a path), optional permission for filtering.
2. **No markup.** No icons-as-HTML, no nested submenus. **A queue-count badge in the nav ("Remediation (14)") is impossible** — the registry carries a label string and nothing computes into it.
3. **Presentation only, never authorization.** The optional permission only hides the link. A hidden entry whose URL is typed directly must still be refused by the view. Nav filtering is not a security boundary — state both halves.
4. **Append-only, in adopted-app-list order.** Nav order is a function of `adopted_apps` order. `reporting` and `workflow` each contribute; neither can reorder the other's or itself relative to Home/About/Profile. **We cannot specify arbitrary nav ordering** — only entries and within-app order.
5. Not enforced yet, and `base.html` today renders a hand-written navbar, not a registry loop.

**Reachability:** every screen is reached from a flat, order-inherited, label-only top nav, or by in-page links from a screen that is. **There is no side nav, no tab bar, no breadcrumb mechanism in the platform.** Anything richer is in-page navigation we design from scratch inside the content area.

## THE FRONTEND STACK — the spine is nearly silent

Exhaustive sweep for htmx/alpine/react/vue/tailwind/spa/frontend/design system found only:
- Stack table: `djangorestframework >=3.17,<4`, `drf-spectacular >=0.30,<0.31`, `django-crispy-forms >=2.6,<3` / `crispy-bootstrap5 >=2026.3,<2027`
- CPM-AD-19's "an app-level `urls.py` with `app_name` for any HTML views"
- Source tree comment: `django_service/  # the reference application, users, templates, static`

**The spine never says HTMX. No mention of HTMX, Alpine, React, Vue, or any JS framework anywhere.**

Ground truth in the repo: `src/django_service/templates/base.html` is a **Bootstrap 5.2.3** layout from cdnjs with SRI, plus `static/css/project.css`, `static/js/project.js`, a `{% block javascript %}`/`{% block inline_javascript %}` pair, Bootstrap JS for navbar collapse and alert dismissal, a hand-written `<ul class="navbar-nav">`. **No HTMX, no JS framework, no build step.** Allauth element overrides (`badge`, `button`, `fields`, `alert`, `field`) are the closest thing to an existing component vocabulary.

**Bottom line:** server-rendered Django templates on Bootstrap 5 with crispy-forms, plus a DRF + drf-spectacular API. The spine states only the DRF half; the template half is **inherited convention, not an invariant**. Any client-side interaction technique is a NEW decision the spine neither authorizes nor forbids — and therefore does not protect.

## Values the spine deliberately does not set

- `PAGE_SIZE` — required to be global, **no number given**.
- p95 latency budget — Deferred (L723-725), PRD OQ 5.
- `CPM_SYNC_EXPORT_MAX_ROWS` — Deferred. Yet CPM-AD-9 makes it the boundary between a synchronous export and a task, which is a **visible UX branch**: download now vs "we'll tell you when it's ready".
- **The three role names are never stated in the spine.**

## Silences — unconstrained AND unprotected

1. All frontend interaction technology.
2. No screen inventory, no page list, no URL scheme.
3. **Nothing on empty states, error presentation, or the shape of the in-progress state.** CPM-AD-9 requires "the request returns an in-progress state" but never says what that is or how the client learns it completed. The spine's own note: this "is the one place where the absence of a stated interaction technology bites hardest."
4. Nothing on accessibility, i18n beyond inherited `{% translate %}`, or responsive breakpoints.

## Terminology collision (again)
Celery queues `collect` / `policy` / `verify` (CPM-AD-20) vs the three **workflow** queues (CPM-AD-22). The spine uses "queue" for both.
