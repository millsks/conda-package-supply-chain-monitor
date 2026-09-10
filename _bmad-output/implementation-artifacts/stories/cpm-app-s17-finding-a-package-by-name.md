# CPM-APP-S17: Finding a package by name

Status: done

Epic: `CPM-EP-APP` — The screens somebody works from

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Raised by
> the product owner as a question — should the views be searchable by package? — and
> written up after agreeing the health table and the API come first. See the epic
> entry.

## Story

As any of the three roles,
I want to find a package by typing part of its name,
so that I can reach it without knowing which page it is on.

## Acceptance Criteria

1. **Given** the health table
   **When** a name fragment is submitted
   **Then** the rows are narrowed to packages whose canonical name contains it,
   matched without regard to case

2. **Given** the same fragment
   **When** it is sent to the JSON API instead
   **Then** the parameter is spelled the same and means the same thing

3. **Given** a fragment no package matches
   **When** it is submitted
   **Then** the result is empty and not a refusal — unlike a facet value outside its
   vocabulary, which stays a 400

4. **Given** a search and a set of facets together
   **When** both are submitted
   **Then** they narrow the same result rather than replacing one another

5. **Given** a search is in force
   **When** the reader clears it
   **Then** the facets they had ticked survive, and the reverse also holds

## Tasks / Subtasks

- [x] `surface/search.py` — the parameter, the normalisations, the condition.
- [x] `surface/listing.py` — read `?q=` inside `health_queryset`, so both surfaces get it.
- [x] `surface/views.py` — the normalised term and the length bound in the context.
- [x] `templates/conda_sentinel/package_health.html` — the box, inside the facet form.
- [x] `static/css/conda-sentinel.css` — the mockups' unused `.searchbox`, finished.
- [x] `tests/unit/django_apps/test_health_search.py` (14 cases).
- [x] `tests/integration/django_apps/test_package_health_view.py` (12 cases added).

## Dev Notes

**Governed by:** `CPM-AD-12` — the search narrows the queryset the paginator counts,
so the page count is the number of matches. `CPM-AD-24` — one queryset builder feeds
the screen and the API.

### A search is not a tenth facet

The decision the story turns on, and it is a decision about what a URL nobody
recognises should do.

`surface/filters.py` **refuses** a value outside its vocabulary, and argues it at
length: `CPM-AD-24`'s vocabularies are closed, so `?vuln=criticl` is a typo or a stale
bookmark, and returning the unfiltered inventory under a URL claiming to be filtered
turns that bookmark into a false all-clear.

A package name is not a closed vocabulary. `?q=djangoo` is a search that matched
nothing, which is a **result** — and refusing it would be exactly as wrong as
absorbing the other. The two rules point in opposite directions and both are right.

Written down in three places on purpose: the module docstring, `health_queryset`'s
`Raises:` section, and a test that asserts **both halves in one case** so that
reconciling them in either direction fails.

### Read from the params, unlike `sort`

`health_queryset` takes `sort` as a keyword because the view needs the resolved
ordering for the template and resolves it once. Nothing needs `?q=` before the query
runs — so it is read inside the builder, and both surfaces get it from the one line
that builds the queryset. There is no way for the screen and the API to disagree about
whether a request was a search.

### Two one-sided normalisations

Surrounding whitespace goes, because a pasted fragment carries it and `" django "`
matching nothing reads as a broken search rather than a stray space.

Underscores become hyphens, because conda-forge canonical names use hyphens —
`scikit-learn`, `umap-learn`, `imbalanced-learn` — while the PyPI import name a reader
has in their head often uses underscores. **The reverse is deliberately not done**: no
canonical name in the roster contains an underscore, and doing it to the *column*
instead would wrap it in a database function and put every index out of reach.

Case is left alone. `icontains` is what makes it not matter, and folding here would
put a second invisible rule between the query string and the result.

## Dev Agent Record

### Completion Notes

**Files added:** `src/django_apps/conda_sentinel/surface/search.py`,
`tests/unit/django_apps/test_health_search.py`.
**Files changed:** `surface/listing.py`, `surface/views.py`,
`templates/conda_sentinel/package_health.html`, `static/css/conda-sentinel.css`,
`tests/integration/django_apps/test_package_health_view.py`.

### The stylesheet already had the rule

`.searchbox` has been in `conda-sentinel.css` since the mockups and **nothing used
it** — grepped across templates, views and tests before writing a new class. So the
box wears the branding it was drawn with rather than a second one invented beside it.

Finished rather than left as found: `appearance:none` (Safari's inset search styling
otherwise ignores the border and the radius, and this one control ends up looking like
it belongs to a different product), a focus ring on the accent, and `box-sizing` so
the 100% width does not overflow the rail.

### Inside the facet form, which is what makes AC 5 true with no JavaScript

The box is a plain `<input>` in the `<form method="get">` the facets already live in.
Applying a facet submits the search with it; clearing the search submits the ticked
facets with it. Neither has to be re-entered to change the other, and the assertion
for it looks at the *facet* form specifically — the chrome carries the theme
control's own form, and a box that landed in that one would submit the theme and lose
the query.

### One duplication caught before it shipped

The template hard-coded `maxlength="128"` beside `MAX_TERM_LENGTH` in Python. Written
twice they drift, and the drift is silent in the worse direction: a box that accepts
more than `search_term` will keep turns a long paste into "no search at all" — the
whole inventory comes back, under an input still showing the reader's text. The bound
is rendered from the constant now, and a case asserts it.

### Verified by opening it

Against the seeded hundred, as `operations-persona`:

```
/packages/                            200   100 packages match   box=            filtered=False
/packages/?q=django                   200   1 package match      box=django      filtered=True
/packages/?q=learn                    200   3 packages match     box=learn       filtered=True
/packages/?q=scikit_learn             200   1 package match      box=scikit-learn
/packages/?q=DJANGO                   200   1 package match      box=DJANGO
/packages/?q=djangoo                  200   0 packages match     box=djangoo
/packages/?q=  git                    200   1 package match      box=git
/packages/?q=a&vuln=advisories_matched 200  19 packages match    (53 without the facet)
/packages/?vuln=criticl               400
/api/v1/packages/?q=learn             200   count=3
/api/v1/packages/?q=djangoo           200   count=0
/api/v1/packages/?vuln=criticl        400
```

The contrast in AC 3 holds on both surfaces. The sort links and the pager carry the
search — measured, not assumed: on `?q=a&sort=rank` the page's links are
`q=a&sort=name` and `q=a&sort=rank&page=2`.

The empty state says what was searched for rather than "No package matches these
filters", which on a search would name the wrong thing.
