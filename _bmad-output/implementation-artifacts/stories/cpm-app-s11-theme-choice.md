# CPM-APP-S11: A reader chooses light, dark, or the machine's answer

Status: done

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
   **Then** it is light, whatever the operating system says

3. **Given** a reader who chooses light or dark
   **When** the next page is rendered
   **Then** the choice is honoured on the **first paint**, with no flash of the other

4. **Given** a reader who chooses "auto"
   **When** a page is rendered
   **Then** it follows the machine — auto is a choice a reader makes, not the state
   they are left in by making none

5. **Given** a stored preference
   **When** it is read
   **Then** a value outside the three is discarded rather than rendered

## Tasks / Subtasks

- [x] `surface/theming.py` — the three states, the default, the cookie, the read.
- [x] `surface/context_processors.py` + `config/settings/base.py` — on every page.
- [x] `surface/views.py` + `urls.py` — the form post that records it.
- [x] `templates/conda_sentinel/base.html` — `data-theme` and the control.
- [x] `static/css/conda-sentinel.css` — the control's own styling.
- [x] `tests/integration/django_apps/test_theme_choice.py`.
- [x] `docs/development.md`.

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

## Dev Agent Record

### Completion Notes

**The stylesheet already had three states; nothing had ever set one.**
`static/css/conda-sentinel.css` has carried light tokens on bare `:root`, a
`prefers-color-scheme: dark` block guarded by `:root:not([data-theme="light"])`, and
`:root[data-theme="dark"]` since the mockups landed. This story is the half that was
missing, and most of it is nine lines of template.

**Files added:** `surface/theming.py`,
`tests/integration/django_apps/test_theme_choice.py`.

**Files changed:** `surface/context_processors.py`, `surface/views.py`,
`surface/urls.py`, `config/settings/base.py`, `templates/conda_sentinel/base.html`,
`static/css/conda-sentinel.css`, `docs/development.md`. **No model, no migration.**

**AC 2 changed mid-implementation, at the product owner's direction.** It read "it
follows the operating system"; it now reads "it is light, whatever the operating
system says". The epic entry and this story were both updated rather than only the
code, and the reasoning is recorded on the epic: the product is read beside other
operator tooling and in screenshots pasted into tickets, and a reader who has not
chosen should see the same screen as whoever is describing it to them.

**The half of that change which is easy to get wrong** is that the default has to
*assert itself*. The dark block is guarded by `:root:not([data-theme="light"])`, so a
default of light that rendered no attribute would still hand a dark-desktop reader the
dark palette — "we default to light" and "we default to light on machines that are
already light" are different products, and only one of them is what was asked for.
`test_a_reader_who_has_chosen_nothing_gets_light` is the case that tells them apart.

**Each acceptance criterion:**

- **AC 1 (on every page, marking what is in force).** A context processor, so "every
  page" is structural rather than remembered — a view that had to provide this would
  eventually be one that did not, and the symptom is a single page in the wrong theme.
  The test walks real pages rather than asserting the base template contains a form.
- **AC 3 (first paint).** The whole reason for a cookie. A test cannot observe the
  absence of a flash; it can observe that the attribute is in the document the server
  delivered rather than applied afterwards, which is the thing that causes one.
- **AC 4 (auto returns the decision).** `auto` is the only state rendering *no*
  attribute. Reached from `dark` in the test, so it shows the attribute being removed
  rather than never having been set.
- **AC 5 (a value outside the three).** Tested on both paths — what is written and
  what is already in the jar — because a cookie set by an older version of this
  product is a value the renderer has to survive rather than trust.

**Three decisions worth recording.**

*The order is light, dark, auto.* The first entry is what a reader who has not chosen
is already looking at; a control whose first entry is not the current state reads as
though something has been changed.

*`THEME_LABELS` is a mapping rather than a template filter.* A template titling raw
values would render whatever it was given, so a fourth state could reach the page with
no name. The mapping is what makes adding one a deliberate act.

*The view is the one surface in this product with no role check.* `CPM-AD-13` scopes
access to evidence, and a theme is not evidence. `CPM-APP-S12` brings the sign-in page
into this product's shell and the control goes with it — a reader meets this product
there, before they hold any role.

**One thing found by rendering it.** The `ThemeView` docstring claimed the control was
already on the sign-in page, which it is not — that page still wears the accelerator's
shell until `CPM-APP-S12`. The justification was written before the thing it justified
existed. Corrected to say what is true and what `S12` will change, which is the same
class of defect as the mixin docstring that claimed `LoginRequiredMiddleware` existed.

**Coverage:** the new module at 100%.
