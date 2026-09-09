# CPM-APP-S10: A home that dates the picture

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

> **Added to the epic after it was written, and the acceptance criteria were drafted
> by the implementing agent rather than derived from the PRD.**
>
> It closes design gap `G-9`. Navigational rather than functional: no FR is expected
> to commission it. Previously part of the invented `CPM-APP-X01`, split out so each
> screen has a story of its own.

## Story

As any of the three roles,
I want the first screen to tell me how current the product's picture is,
so that I do not act on a conclusion that stopped being true last week.

## Acceptance Criteria — drafted by the implementing agent

1. **Given** no policy run has completed
   **When** the home view is opened
   **Then** it says so, rather than showing counts that read as conclusions

2. **Given** a completed policy run
   **When** the home view is opened
   **Then** it shows when the rollup was computed and the evidence cut-off it used

3. **Given** a counter on the home view
   **When** it is displayed
   **Then** it links to the surface that shows the packages it counted

## What is deliberately not built

**"Top of my queue."** The mockup's home leads with it and there is no queue:
`CPM-AD-22`'s workflow application arrives with `CPM-APP-S04`. A placeholder would
mean inventing the product's central abstraction on a screen no requirement asks for.
It is the natural content of this screen once `CPM-APP-S05` exists.

## Tasks / Subtasks

- [x] `surface/views.py` — `HomeView`; `surface/urls.py` — the route.
- [x] Template `conda_sentinel/home.html`; the nav entry stops being inert.
- [x] Cases in `tests/integration/django_apps/test_coverage_view.py`.

## Dev Notes

**Satisfies:** nothing directly.

**Governed by:** `CPM-AD-10`, `CPM-AD-11`, `CPM-AD-13`

## Dev Agent Record

### Completion Notes

**It shows the two things that are real**: how current the rollup is, and the size of
what the monitor cannot see. Every counter links into a filtered health view rather
than sitting in a box — a dashboard whose counters lead nowhere is one people read
once.

**With no completed policy run it says so.** That is the state every fresh deployment
starts in, and the one a dashboard is most likely to render as a confident row of
zeroes.

It shares `surface/coverage.py` with `CPM-APP-S09` and was delivered in the same pull
request.
