# CPM-APP-X01: Coverage, and a home that says how fresh the picture is

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

> **⚠ INVENTED. This story has no PRD requirement and no epic entry.**
>
> `CPM-EP-APP` commissions eight stories and none of them is these two screens. The
> UX mockups carry both — `S2` (reviewer home) and `S8` (coverage and collector
> health) — and the design work records them as gaps `G-8` and `G-9`.
>
> **Every acceptance criterion below was written by the implementing agent**, not
> derived from `prd.md` or `epics.md`. The `X` in the identifier marks that: it is
> not a number the epic assigns. Treat the criteria, the metric definitions and the
> screens as a proposal to review, not as satisfied requirements.
>
> Built at the user's explicit direction, recorded in the session: *"Build Home and
> Coverage too."*

## Story

As any of the three roles,
I want to see how current the product's picture is and what it cannot see,
so that I do not read an out-of-date or incomplete answer as a confident one.

## Acceptance Criteria — INVENTED

1. **Given** the inventory
   **When** the coverage view is opened
   **Then** it states how many packages have no established identity
   **And** how many carry no verdict in each rollup status column, with a denominator
   **And** a *gap* means `unknown` or `error` only — `not_found` and `not_applicable`
   are answers, counted separately

2. **Given** the adopted collectors
   **When** collector health is displayed
   **Then** every **registered** collector appears, including one that has never run
   **And** each is judged against the freshness target it declares for itself

3. **Given** a collector that has never completed a run
   **When** it is displayed
   **Then** it says so, and never renders as blank or as healthy

4. **Given** no policy run has completed
   **When** the home view is opened
   **Then** it says so, rather than showing counts that read as conclusions

5. **Given** a counter on the home view
   **When** it is displayed
   **Then** it links to the surface that shows the packages it counted

## What is deliberately not built

- **"Top of my queue."** The mockup's home leads with it and there is no queue:
  `CPM-AD-22`'s workflow application arrives with `CPM-APP-S04`. A placeholder would
  mean inventing the product's central abstraction on a screen nobody commissioned.
- **Per-domain freshness for the four statuses the rollup does not carry.** Counting
  them means a query per domain over the whole inventory; `CPM-APP-S06`'s recurring
  reports are where a full scan belongs.

## Dev Notes

**Satisfies:** nothing. See the warning above.

**Governed by:**

- `CPM-AD-10` — Derived state is read-only to the application
- `CPM-AD-11` — Current health is a refreshed rollup table
- `CPM-AD-13` — Authorization is declared per surface, enforced centrally
- `CPM-AD-24` — Every read surface projects the same values
- `CPM-AD-26` — Time comes from the injected clock

## Dev Agent Record

### Completion Notes

**A gap is `unknown` or `error`, and narrowing it to those two was a review
outcome.** The first version counted all four of `CPM-FR-5`'s sentinels. That was
wrong on two of them: "we looked and there is no feedstock" and "this native library
has no Python metadata" are things the product **does** know, and counting them as
gaps inflates the number with answers — so it would rise as the product learned more,
which is the same defect as counting adverse verdicts and is harder to notice. They
are shown beside the gap instead, because there is a different thing to do about each.

**The screen counts absence, and that is the design rather than a detail.** A
coverage screen built the obvious way — percentage healthy, percentage current —
reports a product that is working. `CPM-FR-5` forbids presenting a package as clean
without evidence, and this is where the aggregate of that is visible: how many
packages nothing has identified, how many statuses are sentinels rather than
verdicts, and which collector has not completed a run inside the window it declared.

**The collector roster is `core/registry.py`'s, never a list written in the view.**
Every adopted collector declares its own `freshness_target`; a screen with a
hand-written roster would give a clean bill of health to a collector somebody forgot
to add to it, which is the failure mode of every monitoring dashboard ever written
and the one this screen exists to be the opposite of. AC 2 and AC 3 exist to hold
that.

**`never_run` is spelled apart from `unknown` on purpose.** `unknown` is an
`OutcomeState` value and means a lookup that concluded nothing; a collector that was
never asked is a different thing, and `tests/unit/django_apps/test_tone.py` would
have no tone for it either way.

**Files added:** `surface/coverage.py`, `templates/conda_sentinel/coverage.html`,
`templates/conda_sentinel/home.html`, and two test modules.

**Files changed:** `surface/views.py`, `surface/urls.py`, the base template's nav
(Home and Coverage stop being inert), `docs/development.md`.

**Coverage:** the new module at 100%. **No migration and no model change.**
