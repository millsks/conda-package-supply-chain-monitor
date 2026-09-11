# CPM-APP-S20: Every screen reads in sentence case

Status: done

Epic: `CPM-EP-APP` — The screens somebody works from

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Asked for
> by the product owner with five screenshots: go through each view, identify which text
> is just the label or id of something, and give it a sentence-case label. See the epic
> entry.

## Story

As anybody reading any screen,
I want what I read to be written the way somebody would say it,
so that I am reading a product rather than its database.

## Acceptance Criteria

1. **Given** any view a person reads
   **When** it is rendered
   **Then** no stored value reaches them spelled with the slug separator

2. **Given** a value carrying an acronym, a name or a version number
   **When** it is labelled
   **Then** it is spelled out rather than derived

3. **Given** any other value
   **When** it is labelled
   **Then** it derives from the value, in sentence case and not title case

4. **Given** the JSON API and the CSV export
   **When** the same status appears there
   **Then** it is the value, unchanged

5. **Given** a template rendering a status chip
   **When** it picks a tone and prints a label
   **Then** it takes both from the value and derives neither from the other

## Tasks / Subtasks

- [x] `surface/labels.py` — `display_label`, `SPELLED_OUT`.
- [x] `surface/templatetags/health.py` — the `label` filter, beside `tone`.
- [x] `surface/coverage.py` — `freshness_label`, because a `timedelta` printed is a repr.
- [x] `surface/reports.py` — `readable_rows()`, status columns only; `rows` unchanged.
- [x] Six templates, sixteen render sites.
- [x] `tests/unit/django_apps/test_display_vocabulary.py` — fourteen cases.
- [x] `tests/integration/django_apps/test_no_slug_reaches_a_reader.py` — the sweep.
- [x] `ARCHITECTURE-SPINE.md` — `CPM-AD-24` clarified.

## Dev Notes

**Governed by:** `CPM-AD-24`, clarified here. Its rule names "API, export, and governed
view" — all three machine-read. The screen was never among them; it rendered values
because a template prints what it is handed.

**The product owner chose this shape** from three offered: label on screen, verbatim in
CSV and API. The alternative of labelling everywhere would have broken every integrator
parsing a status, and leaving statuses alone would have fixed a third of the problem.

## Dev Agent Record

### Completion Notes

**Files added:** `tests/integration/django_apps/test_no_slug_reaches_a_reader.py`.
**Files changed:** `surface/labels.py`, `surface/coverage.py`, `surface/reports.py`,
`surface/templatetags/health.py`, six templates,
`tests/unit/django_apps/test_display_vocabulary.py`, the architecture spine.

### The survey, before any change

Rendering all eleven views and extracting the slug-shaped visible text found **47
distinct slugs**. Classified rather than counted, because they were not one problem:

| Kind | Examples | Verdict |
|---|---|---|
| Collector names | `conda_package`, `py314_verification` | Unlabelled. The product owner's own examples. |
| Evidence tables | `vulnerability_findings`, `kev_findings` | Unlabelled, on "produced from". |
| Mapping kinds | `source_repository`, `cross_ecosystem` | Unlabelled. |
| Work types, buckets | `fix_vulnerability`, `p1` | Unlabelled. |
| Queue names | `compliance_review` on the detail page | `queue_label` existed; that template did not use it. |
| Derived statuses | `advisories_matched`, `manual_review` | **Bound by `CPM-AD-24`** — asked before changing. |
| A raw `timedelta` | `2 days, 0:00:00` | A repr, in a column whose other rows read the same way. |

After: **9 remain, and five of those are the Django Debug Toolbar** — its Templates and
History panels naming `conda_sentinel/package_detail.html` and the request URL. Not
product output, and absent under test settings where `DEBUG` is off.

### One entry point, four sources

`display_label` is what every template calls, so no template author has to know which
vocabulary a value came from: queue labels, then role labels, then `SPELLED_OUT`, then
derivation. Specific before general.

**The label derives from the value**, which is what keeps the two from drifting. A
hand-written map of forty labels is forty chances to disagree and a file the next
person to add a status has to find. `SPELLED_OUT` holds only what cannot derive — an
initialism (`kev`), a name spelled two ways (`pypi`, which is not `Pypi`), a version
with the dot taken out (`py314`), and `ok`, which derives to `Ok`.

**Sentence case, not Django's title case.** Every vocabulary here is a `TextChoices`
and already carries a generated label — but it is `Not Listed`, a heading rather than
something anybody says.

Hyphens are left alone: `inventory-derived` is *inventory-derived*, while an underscore
is always this product's separator standing in for a space.

### The export keeps the value

`ReportPage.rows` is untouched — it is what the CSV writes. `readable_rows()` is the
HTML's view of the same rows, and pairs each cell with its column so that **only
`is_status` columns are labelled**: the other cells are package names and timestamps,
and sentence-casing those would turn `django` into `Django`.

Asserted from both sides. `test_the_machine_surfaces_still_speak_in_values` fails if a
later change relabels everything everywhere — which would satisfy the sweep and break
every integrator.

### The sweep passed while the defect was reintroduced

The part worth recording. The first version of
`test_no_slug_reaches_a_reader.py` ran against an **empty database**: every page
rendered its "nothing matches" row, no status cell was produced, and reverting
`{{ cell.status|label }}` to `{{ cell.status }}` failed nothing at all.

It is the failure this repository names most often — a sweep over an empty page reports
no violations rather than no coverage — and it was in the module written to prevent
exactly that class.

Fixed by seeding a rollup row with **determinate** statuses (a table of `unknown` would
exercise the one word that needs no label) and a queue item per queue. Then a second
gap: the items were `open`, which is one word, so the queue's state column was still
covered by a value that cannot fail. They are `in_progress` now — which the database
refused until they named a claimant, `workflow_claimed_only_while_in_progress` being
right that an item nobody holds cannot be in progress.

Re-verified afterwards: reverting the packages label fails the packages view, and
reverting the queue label fails all three queues.

### Out of scope, recorded rather than missed

`finding_facts` — `advisory_id=CVE-2026-48588 affected_range=>=6.0.0,<6.0.7` — is one
stored string whose *values* may contain spaces, since a licence expression is
`Apache-2.0 OR BSD-3-Clause`. It cannot be split reliably at render time, so making it
readable means changing what is stored. That is a story, not a labelling pass, and the
sweep's exception list says so.

`license_rules` is permitted for a different reason: it appears inside a sentence
explaining that a policy version records none, and it is the name of a key in a TOML
file. Labelling it would break a reader's ability to go and find it.
