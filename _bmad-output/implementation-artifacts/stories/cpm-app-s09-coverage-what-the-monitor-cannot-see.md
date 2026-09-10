# CPM-APP-S09: Coverage — what the monitor cannot see

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

> **Added to the epic after it was written, and the acceptance criteria were drafted
> by the implementing agent rather than derived from the PRD.**
>
> No functional requirement commissions this screen. It closes design gap `G-8`, and
> its subject is the aggregate of what `CPM-FR-5` requires per package: that nothing
> is presented as clean without evidence. Whether that deserves an FR of its own is
> recorded as an open question under the epic, not decided here.
>
> This story previously carried the invented identifier `CPM-APP-X01` and covered
> both this screen and the home view. It was split and renumbered so the planning
> record names what was built, rather than the code referring to a story the epic had
> never heard of.

## Story

As any of the three roles,
I want to see how much of the estate the product has formed no opinion about,
so that I do not read a partial picture as a complete one.

## Acceptance Criteria — drafted by the implementing agent

1. **Given** the inventory
   **When** the coverage view is opened
   **Then** it states how many packages have no established identity
   **And** how many carry no verdict in each rollup status column, with a denominator

2. **Given** a status of `not_found` or `not_applicable`
   **When** coverage is counted
   **Then** it is reported as an answer and never as a gap — a gap is `unknown` or `error`

3. **Given** the adopted collectors
   **When** collector health is displayed
   **Then** every **registered** collector appears, including one that has never run
   **And** each is judged against the freshness target it declares for itself

4. **Given** a collector that has never completed a run
   **When** it is displayed
   **Then** it says so, and never renders as blank or as healthy

## Tasks / Subtasks

- [x] `surface/coverage.py` — the counts and the collector roster.
- [x] `surface/views.py` — `CoverageView`; `surface/urls.py` — the route.
- [x] Template `conda_sentinel/coverage.html`; the nav entry stops being inert.
- [x] `tests/integration/django_apps/test_coverage_view.py`.
- [x] `docs/development.md`.

## Dev Notes

**Serves:** `CPM-FR-5` (its aggregate). **Satisfies no FR directly.**

**Governed by:** `CPM-AD-10`, `CPM-AD-11`, `CPM-AD-13`, `CPM-AD-24`, `CPM-AD-26`

## Dev Agent Record

### Completion Notes

**The screen counts absence, not health.** A coverage view built the obvious way
reports a percentage healthy and tells an operator the product is working. What they
need is the opposite: how many packages nothing has identified, how many statuses are
sentinels rather than verdicts, and which collector has not completed a run inside the
window it declared.

**A gap is `unknown` or `error`, and narrowing it to those two was a review outcome.**
The first version counted all four of `CPM-FR-5`'s sentinels. That was wrong on two of
them: "we looked and there is no feedstock" and "this native library has no Python
metadata" are things the product **does** know. Counting them as gaps inflates the
number with answers — so it would rise as the product learned more, which is the same
defect as counting adverse verdicts and is harder to notice because these two look
like failures. They are shown beside the gap instead: an operator reading "1,204
packages have no feedstock" is reading a finding, and one reading "217 packages
nothing has looked at" is reading a hole in the monitoring.

**The collector roster is `core/registry.py`'s, never a list written in the view.** A
hand-written roster gives a clean bill of health to a collector somebody forgot to add
to it, which is the failure mode of every monitoring dashboard ever written and the one
this screen exists to be the opposite of. Each collector is judged against the
`freshness_target` it declares for itself — two days for an advisory sweep, thirty for
a Python 3.14 build — so a single threshold would call one stale while it was on time.

**`never_run` is spelled apart from `unknown`.** `unknown` is an `OutcomeState` value
meaning a lookup that concluded nothing; a collector nobody asked is a different thing.

**Coverage:** the module at 100%. **No migration and no model change.**
