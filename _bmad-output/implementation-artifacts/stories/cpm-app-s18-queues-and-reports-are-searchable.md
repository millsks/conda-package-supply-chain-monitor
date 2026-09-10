# CPM-APP-S18: The queues and the reports are searchable too

Status: done

Epic: `CPM-EP-APP` — The screens somebody works from

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. The second
> half of the product owner's question, separated from `CPM-APP-S17` because the health
> table shares a queryset builder with the API and these surfaces share nothing.

## Story

As any of the three roles,
I want to narrow a queue or a report to one package,
so that I can answer a question about that package without reading a list.

## Acceptance Criteria

1. **Given** any of the three queues
   **When** a name fragment is submitted
   **Then** the open items are narrowed to those about matching packages, and their
   rank order is unchanged

2. **Given** any of the six reports
   **When** a name fragment is submitted
   **Then** its rows are narrowed the same way

3. **Given** a narrowed queue or report
   **When** the count is displayed
   **Then** it is the number of matches, and the pagination follows the matches

4. **Given** the parameter
   **When** it is read on any of these surfaces
   **Then** it is spelled exactly as `CPM-APP-S17` spells it on the health table

## Tasks / Subtasks

- [x] `surface/queues.py` — `queue_items(..., search=)`, applied after the queue filter.
- [x] `surface/reports.py` — `report_values(..., search=)`, which every reader goes through.
- [x] `surface/exports.py` — `over_the_cap`, `export_csv`, and the job runner.
- [x] `surface/search.py` — `search_context`, so three templates get three keys as one.
- [x] `surface/views.py` — the queue view, the report view, both export methods.
- [x] `templates/conda_sentinel/_searchbox.html` — the control, declared once.
- [x] `templates/` — `queue.html`, `report.html`, and `package_health.html` now including.
- [x] `static/css/conda-sentinel.css` — `.findbar`.
- [x] `tests/unit/django_apps/test_search_parameter_audit.py` (the static half of AC 4).
- [x] `tests/integration/django_apps/test_search_across_surfaces.py` (the behavioural half).
- [x] Cases added to `test_queue_views.py`, `test_reports.py`, `test_background_exports.py`.

## Dev Notes

**Governed by:** `CPM-AD-12` (the search narrows what the paginator counts),
`CPM-AD-13` (it narrows what a role may already see and never widens it),
`CPM-AD-24` (one projection per surface, and the export is the page's rows).

### The export was the interesting half

`ReportExportView`'s docstring states the principle the module is written around:

> **The same rows as the page**, from the same projection with a different bound — not
> a second query with its own filters, which is how an export comes to disagree with
> the screen somebody exported it from. That disagreement is the one nobody notices
> until it is in a board pack.

So a search the page honoured and the export did not would be exactly that failure, in
the artifact `CPM-AD-24` singles out as the one that leaves the system. The search
therefore goes into `report_values`, which the page, the synchronous export and the
background job all read through — rather than into the view, where two of the three
would have missed it.

Three consequences, each of which needed doing:

- **The synchronous export** reads `?q=` off the request and passes it down.
- **The link and the form on the page** carry the fragment. The `<a>` appends it to
  the query string; the POST needs a hidden field, because a form does not inherit
  one. A module that is right and a template that does not send it is a feature that
  works in tests.
- **The background job** carries it in `parameters`, which is what that `JSONField`
  is for. Read directly rather than through `job_parameters`, and the difference is
  deliberate: that helper *refuses* a missing parameter, because a runner reading
  `None` for the slug would produce an artifact for the wrong report. A search is
  genuinely optional, so absent means "the whole report" — which is also what every
  job enqueued before this story carries, and a runner that refused would have failed
  all of them the moment this shipped.

### The cap is measured against the searched rows

`over_the_cap` takes the search too. A narrowed report is genuinely smaller, so
`?q=learn` on a four-thousand-row report should get the direct download.

The half that makes it necessary rather than nice: the page and the export must agree
about which control is on offer. Measured against the whole report, the page would
show the background form for a file a request could produce — and, in the other
direction, offer a link that then refuses the reader it was just offered to.

### AC 4 is asserted twice, statically and behaviourally

Neither alone is enough, and the pair is the point.

`test_search_parameter_audit.py` reads source and templates: **no module but
`search.py` may spell the parameter, and no template but `_searchbox.html` may declare
the input.** Ten surfaces means ten chances to spell it differently, and the symptom is
quiet — a bookmarked URL stops narrowing on one page whose heading says nothing is
filtered.

`test_search_across_surfaces.py` opens all ten and asserts each answers a search,
renders the box, and puts the fragment back in it. A view can import `SEARCH_PARAM`
faithfully and never pass it to a queryset, which is a page with a search box that does
nothing — and the audit above cannot see that.

Both read the roster off `REPORTS` and `Queue` rather than a written list, so a report
or a queue added later is covered the day it exists.

## Dev Agent Record

### Completion Notes

**Files added:** `templates/conda_sentinel/_searchbox.html`,
`tests/unit/django_apps/test_search_parameter_audit.py`,
`tests/integration/django_apps/test_search_across_surfaces.py`.
**Files changed:** `surface/queues.py`, `surface/reports.py`, `surface/exports.py`,
`surface/search.py`, `surface/views.py`, `templates/queue.html`,
`templates/report.html`, `templates/package_health.html`,
`static/css/conda-sentinel.css`, and three integration test modules.

### The search cannot cross a role boundary

`queue_items` selects the queue first and applies the fragment to what that returned.
`CPM-AD-13` scopes each queue to one role, so a search that built its own queryset —
or that ORed rather than ANDed — would be a role boundary crossed by a query string,
which is the one failure mode a per-surface authorization model has.
`test_a_search_cannot_reach_another_queues_items` is written against that specifically,
and it opens an item in `compliance_review` and searches for it from `remediation`.

Applied *before* the ranking annotations, so the paginator counts matches and the rank
order of what is left is unchanged. A search that re-sorted — by relevance, say — would
put the item a reviewer should do next somewhere other than the top, on the one screen
whose entire contract is that the top is what to do next.

### One control, three shapes of wrapper

`_searchbox.html` is the field alone. The health table includes it *inside* the facet
form, which is what makes `CPM-APP-S17`'s AC 5 true with no JavaScript. A queue or a
report gives it a `.findbar` form of its own, because neither has another — and a GET,
so the fragment lands in the URL and a reviewer who has narrowed a queue to one package
can send that link to whoever asked them about it.

`package_health.html` was refactored to include the partial rather than keep the copy
`CPM-APP-S17` gave it. Three copies would drift, and the field that drifts is
`maxlength`.

### Verified by opening all ten

Against the seeded hundred, as `operations-persona`. Every surface, four fragments
each — none, one matching many, one matching one, one matching nothing:

```
                                     none    q=a   q=aiohttp   q=nothing-like-this
queues/remediation/                    28     19       1              0
queues/compliance_review/              50     46       1              0
queues/identity_review/                 2      2       0              0
reports/kev/                            1      0       0              0
reports/feedstock-lag/                 55     30       1              0
reports/python-314/                     8      6       0              0
reports/licence-exceptions/            90     46       1              0
reports/unmapped-identities/            2      2       0              0
reports/stale-evidence/                 2      2       0              0
```

`reports/kev/?q=a` is zero because the only KEV row is `git`, which contains no `a`.

The export, end to end on a narrowed report:

```
export control: /conda-sentinel/reports/licence-exceptions/export/?q=learn
exported rows:  2 -> ['imbalanced-learn', 'scikit-learn']
```

The link carries the fragment and the file holds the rows the screen was showing.

### The coverage screen is still excluded

Recorded so it is not later "completed": it has one row per collector rather than per
package, so a box that looked like the others would answer a different question. The
cross-surface sweep enumerates ten URLs and coverage is deliberately not among them.
