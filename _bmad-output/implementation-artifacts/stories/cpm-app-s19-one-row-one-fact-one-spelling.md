# CPM-APP-S19: One row, one fact, one spelling

Status: done

Epic: `CPM-EP-APP` — The screens somebody works from

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Raised by
> the product owner with a screenshot: *Last finished* says `never run`, *Status* says
> `never_run` — shouldn't they both be "never run"? See the epic entry.

## Story

As anybody reading the coverage screen,
I want one fact to be spelled one way,
so that I am not left wondering whether two columns disagree.

## Acceptance Criteria

1. **Given** a collector nothing has run
   **When** its row is rendered
   **Then** both columns say the same thing, the way a person says it

2. **Given** the status value
   **When** the row picks its tone
   **Then** it still uses the value

3. **Given** a collector status this product declares
   **When** it is rendered anywhere
   **Then** it carries no slug separator

4. **Given** one of the five outcome states
   **When** it appears on the coverage screen
   **Then** it is emitted verbatim

## Tasks / Subtasks

- [x] `surface/labels.py` — `COLLECTOR_STATUS_LABELS` and `collector_status_label`.
- [x] `surface/coverage.py` — a `status_label` property beside `last_status`.
- [x] `templates/conda_sentinel/coverage.html` — print the label, keep the value.
- [x] `tests/unit/django_apps/test_display_vocabulary.py` — four cases.
- [x] `tests/integration/django_apps/test_coverage_view.py` — two, over the rendered page.
- [x] `docs/conda-sentinel/asynchronous-work.md` — how to make the collectors run.

## Dev Notes

**Governed by:** `CPM-AD-24`, and the work is deciding which half applies. The five
outcome states survive verbatim to every surface so a reader who has learned them can
carry them between a screen, a CSV and a JSON response. A **collector's health** is a
different vocabulary and carries no such guarantee.

### The rule was already written down

`surface/labels.py` opens by rejecting "labels everywhere" and states the actual rule:

> a value a person reads is either a status this product asserts, or it has a label

and names the tell:

> An underscore is the tell: it is how this product spells a multi-word *value*, and
> nothing a person reads is spelled that way.

`never_run` is not an `OutcomeState` — the five are `error`, `unknown`, `not_found`,
`not_applicable`, `ok`, and `surface/coverage.py` argues at length that `never_run` is
deliberately *not* `unknown`, because `unknown` is an answer about a package and this
is a statement about a collector. So it was a slug being read by a person, which the
rule already covered.

### Why this one was worse than the navigation

`CPM-APP-S15` fixed the same class in the nav bar. There the value appeared alone, and
a reader had nothing to compare it against. Here the two spellings are **adjacent
columns of one row**, and on a component nothing has collected with, *every* row is
that row — so the screen shows ten instances of one fact spelled two ways to the one
person most likely to be reading it: somebody wondering why nothing has run.

## Dev Agent Record

### Completion Notes

**Files changed:** `src/django_apps/conda_sentinel/surface/labels.py`,
`src/django_apps/conda_sentinel/surface/coverage.py`,
`src/django_service/templates/conda_sentinel/coverage.html`,
`tests/unit/django_apps/test_display_vocabulary.py`,
`tests/integration/django_apps/test_coverage_view.py`,
`docs/conda-sentinel/asynchronous-work.md`.

### The value and the label, both

The template keeps `last_status` for the tone and prints `status_label` — which is what
`test_the_navigation_gets_the_value_and_the_label` already required of the nav, for the
same reason:

> Both, because the URL needs one and the reader needs the other. A template deriving
> either from the other is exactly what broke.

### One entry in the map, and that is the design

`ok` and `failing` are already what a person would say and are **not** given labels. A
map spelling them out would look like a translation table for a vocabulary that mostly
does not need one, which is how a later reader concludes every value must have a label
and gives one to a status — undoing `test_no_outcome_state_acquires_a_label` from the
other direction.

`ok` is the live risk there, being both a collector status and an `OutcomeState`, so it
has a case of its own.

### Asserted over the rendered page

The projection was never wrong. `last_status` is correct, and a test of
`collector_health()` would have passed before and after. What was wrong was **what got
printed**, which is the one thing a test of the projection cannot see — so the two
integration cases fetch the page and read the HTML.

Verified by reintroducing the defect: reverting the template to `{{ collector.last_status }}`
failed exactly those two and nothing else.

### The question underneath the screenshot

"How do I get the collectors to run so they don't show never run?" — answered in
`asynchronous-work.md` rather than by changing anything, because the screen was right.

Against a **real** watchlist, enqueue `cpm.collect.sweep` per collector. Against the
**demo** inventory it is mostly not what you want, and the table now says why per
collector, measured rather than assumed:

| Collector | Against the demo inventory |
|---|---|
| `inventory` | Fails — `watchlist.csv` ships with no rows, on purpose |
| `source_release` | Records `not_found` for all — the demo's repository URLs are fixtures |
| `pypi_release`, `python_readiness` | Genuinely work — the demo's purls are real |
| `feedstock` | Mostly works — the demo follows conda-forge's real naming |
| `conda_package`, `license` | Inert — both need `CPM_MONITORED_CHANNELS`, which is `()` |
| `vulnerability`, `kev`, `py314_verification` | Inert — each needs a source you declare |

With the danger stated plainly: every one of those rows writes **real observations into
an append-only log**, on top of the demo evidence. `CPM-AD-2` means none of it can be
taken back. To prove the worker is alive without that cost, send `cpm.policy.run` — it
computes and writes no evidence at all.
