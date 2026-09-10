# CPM-APP-S11: A reader chooses light, dark, or the machine's answer

Status: ready-for-dev

Epic: `CPM-EP-APP` — The surface the three roles actually work in

> **Acceptance criteria invented.** No functional requirement commissions a theme
> control. They were drafted by the implementing agent against the design spine's own
> palette and confirmed with the product owner. See the epic entry.

## Story

As any of the three roles,
I want to choose whether this product is light, dark, or follows my machine,
so that I can read it on the screen I am actually sitting at.

## Acceptance Criteria

1. **Given** any page in the product
   **When** it is rendered
   **Then** the control is present and marks which of the three is in force

2. **Given** a reader who has chosen nothing
   **When** a page is rendered
   **Then** it follows the operating system, and no explicit theme is asserted

3. **Given** a reader who chooses light or dark
   **When** the next page is rendered
   **Then** the choice is honoured on the **first paint**, with no flash of the other

4. **Given** a reader who chooses "auto" again
   **When** a page is rendered
   **Then** it returns to following the machine — auto is a choice, not the absence of one

5. **Given** a stored preference
   **When** it is read
   **Then** a value outside the three is discarded rather than rendered

## Tasks / Subtasks

- [ ] `surface/theming.py` — the three states, the cookie, and the read.
- [ ] `surface/context_processors.py` — the current choice, on every page.
- [ ] `surface/views.py` + `urls.py` — the form post that records it.
- [ ] `templates/conda_sentinel/base.html` — `data-theme` and the control.
- [ ] `static/css/conda-sentinel.css` — the control's own styling.
- [ ] Tests: the three states, the first-paint claim, and the rejected value.

## Dev Notes

**Satisfies:** nothing directly. Serves the design spine's own three-state palette.

**Governed by:**

- `CPM-AD-24` — every read surface projects the same values. A status renders as its
  own `OutcomeState` value under every theme; the theme changes tone tokens and never
  a status.

### Why there is no JavaScript

The product ships none, and here that constraint is what makes AC 3 satisfiable
rather than a cost. A client-side toggle cannot know the choice before the document
loads, so it paints the default and corrects it — the flash of the wrong theme that
every `localStorage` implementation has. A cookie is on the request, so the server
renders the right attribute the first time.

### Why not on the `User`

A theme is a property of the screen somebody is looking at, not of who they are: the
same person on a bright monitor and a dark laptop wants different answers, and a
column on `User` would make those the same person's one answer. It also has to work
before anybody signs in, because the sign-in page is a screen too.

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- Unit tests touch no database, network or filesystem; integration tests live under
  `tests/integration/` and are marked by directory.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a 90% floor.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
