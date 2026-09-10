# CPM-APP-S16: Wide content scrolls itself, not the page

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Raised by
> the product owner with a screenshot. See the epic entry.

## Story

As any of the three roles,
I want a table wider than my screen to scroll inside itself,
so that I can still see where I am while I read it.

## Acceptance Criteria

1. **Given** a table wider than the viewport
   **When** the page is rendered
   **Then** the table scrolls within its own container

2. **Given** the same page
   **When** it is rendered
   **Then** the page body does not scroll horizontally, and the navigation and
   heading stay where they are

3. **Given** a container that holds content wider than a laptop
   **When** the stylesheet is read
   **Then** it declares both halves — the container may shrink, and it scrolls what
   does not fit

4. **Given** the health table at a narrow width
   **When** it is rendered
   **Then** its columns scroll rather than being crushed to unreadability

## Tasks / Subtasks

- [x] `static/css/conda-sentinel.css` — `.main-pane`, `.tbl`, `.freshbar`, `.app-body`.
- [x] `tests/unit/django_apps/test_stylesheet_overflow.py`.

## Dev Notes

### `min-width: 0` is the load-bearing half

A grid or flex item defaults to `min-width: auto`, which is its *content's* minimum.
Such an item does not shrink — it pushes its parent instead, and the page grows.
`overflow-x` alone does nothing to an item that never became smaller than its content,
which is why the pair is the rule and either alone is not.

`.main-pane` had `min-width: 0` and no `overflow-x`. `.panel`, which holds every other
table in the product, has had both since the mockups.

### The table needs a minimum too

`width: 100%` alone crushes columns rather than producing a scrollbar. Eleven columns
of status chips squeezed beside the facet rail is a table that is technically visible
and not readable — `advisories_matched` wrapped over four lines in a ninety-pixel
cell. The minimum is what turns that into a scroll.

### The freshbar was a second cause

Its children are flex items holding the policy version map — eight `domain@version`
pairs — and a flex child will not shrink below its content without `min-width: 0`. It
was contributing to the same overflow.

## Dev Agent Record

### Completion Notes

**The screenshot showed more than a wide table.** The page had scrolled: the
navigation and the heading were off-screen to the left, and the visible left edge read
"alth". The width was never the defect — eleven columns of status chips do not fit a
laptop beside the facet rail and never will. What went wrong is how that failed.

**Files changed:** `static/css/conda-sentinel.css`.
**Files added:** `tests/unit/django_apps/test_stylesheet_overflow.py`.
**No template, no view, no model.**

**Three rules, one cause.** `.main-pane` gained `overflow-x: auto` to match the
`min-width: 0` it already had; `.tbl` gained a minimum so its columns scroll rather
than crush; `.freshbar`'s flex children gained `min-width: 0` so the version map wraps
instead of widening the bar.

**A limit worth stating.** The audit reads the stylesheet, not a rendered page — this
suite has no browser, and an attempt to check it through the Chrome tooling failed
because the extension is not connected. So the test proves the rules are *declared*,
which is what prevents the specific regression: a container holding a wide table that
declares half the pair, exactly the state `.main-pane` was in. Whether the result
looks right is a human check, and it was asked for rather than assumed.

**Why the case is parameterised over the pair** rather than asserting both together: a
failure then says *which* half is missing, which is the difference between "this rule
is wrong" and "this rule is half of what it needs" — and only the second tells you
what to add.
