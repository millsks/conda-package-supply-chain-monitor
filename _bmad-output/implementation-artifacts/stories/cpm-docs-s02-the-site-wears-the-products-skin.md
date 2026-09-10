# CPM-DOCS-S02: The site wears the product's own skin

Status: done

Epic: `CPM-EP-DOCS` — Documentation that says which product it is about

> **Acceptance criteria invented.** No functional requirement commissions
> documentation. They were drafted by the implementing agent and confirmed with the
> product owner, on the terms `CPM-APP-S09` established. See the epic entry.

## Story

As any reader,
I want the documentation to look like the product it documents,
so that I can tell at a glance which system I am reading about.

## Acceptance Criteria

1. **Given** the documentation site
   **When** any page is rendered
   **Then** it uses the product's palette, type and brand mark

2. **Given** the site's front page
   **When** it is opened
   **Then** it describes Conda-Sentinel and not the accelerator this component was
   built from

3. **Given** a reader's light or dark preference
   **When** a page is rendered
   **Then** the site honours it, in both schemes

4. **Given** an outcome state named in prose
   **When** it is rendered
   **Then** it is distinguishable as a state rather than set as ordinary words

## Tasks / Subtasks

- [x] `docs/stylesheets/conda-sentinel.css` — the palette, mapped onto Material's.
- [x] `mkdocs.yml` — `extra_css`, the fonts, `attr_list`, both palette entries.
- [x] `docs/index.md` — rewritten for this product.
- [x] `.cs-state` — the five states, usable in prose.
- [x] `tests/unit/test_documentation_branding.py`.

## Dev Notes

### Mapped, not restated

Every value is assigned to one of Material's own `--md-*` variables, so the theme
keeps doing its job and only the colours are this product's. A stylesheet that
restyled Material's components directly would break on its next minor release.

The palette itself is the third copy — `docs/ux/ui-mockups.html` is the contract,
`static/css/conda-sentinel.css` serves the application, and this serves the site.
Three copies exist because they serve three runtimes; what keeps them honest is that
this one maps rather than redefines.

### Two scheme attributes, deliberately unreconciled

Material owns light and dark through `[data-md-color-scheme]`. The application uses
`[data-theme]` (`CPM-APP-S11`). They are not the same attribute and should not be
made so: the documentation is read in a browser tab beside the product, not inside
it, and a reader who wants one dark and the other light is not confused about
anything.

### `unknown` in prose

`CPM-FR-5` makes five states distinguishable and `CPM-AD-24` requires each be emitted
verbatim. Documentation that set `unknown` as an ordinary word would make, in prose,
the mistake the export rule forbids in a file — so a state written in the
documentation reads the way it reads on a screen.

### Testing Standards

- `pixi` is the only Python runner. Never `uv`, never bare `python`, never `pip`.
- `pixi run docs` (`mkdocs build --strict`) must succeed: a broken internal link is a
  build failure rather than a page a reader finds later.
- `pixi run ci` must exit 0 — precommit, build, typecheck, lint, then coverage at a
  90% floor.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Dev Agent Record

### Completion Notes

**The front page opened with another product's name.** *"Django 15-Factor Base — A
Django application accelerator template"*, on a site titled Conda-Sentinel. That is
the most confusing thing a documentation site can do: a reader concludes they are in
the wrong place and leaves.

**Files added:** `docs/stylesheets/conda-sentinel.css`,
`tests/unit/test_documentation_branding.py`.
**Files changed:** `mkdocs.yml`, `docs/index.md`.

### Mapped, not restyled

Every value is assigned to one of Material's own `--md-*` variables. A stylesheet that
restyled `.md-nav__link` directly would work today and break on Material's next minor
release — and a broken documentation site is one nobody notices, because nobody has it
open when they deploy.

The palette is the third copy: `docs/ux/ui-mockups.html` is the contract,
`static/css/conda-sentinel.css` serves the application, this serves the site. Three
exist because they serve three runtimes. What keeps them honest is that this one maps
rather than redefines.

### `unknown` reads as a state

`.cs-state` gives the five outcomes the same treatment in prose that they have on a
screen. Documentation that set `unknown` as an ordinary word would make, in prose,
exactly the mistake `CPM-AD-24` forbids in an export — and prose is where somebody
*first* learns what the five mean, so getting it wrong here costs more than getting it
wrong once on a screen.

Four classes for five states: `not_found` and `not_applicable` share `unknown`'s
treatment, because all three are the product declining to assert a verdict and a
reader distinguishing them by colour would be reading a distinction the palette cannot
carry. The word distinguishes them, which is the point.

### The front page leads with the idea rather than the features

Most monitoring tools have two answers — a problem, or silence — and silence is the
dangerous one because it looks like health and is usually absence. This product has
five and says which it means. Everything else in the documentation follows from that,
so it is the first thing on the page, shown as chips rather than described.

### Two decisions

*The scheme attributes are not reconciled.* Material owns `[data-md-color-scheme]`,
the application owns `[data-theme]` (`CPM-APP-S11`). The documentation is read in a
tab beside the product, not inside it, and a reader who wants one dark and the other
light is not confused about anything.

*Both schemes are asserted separately.* The failure a single check misses is partial —
a palette defined once looks right in one scheme and reverts to indigo in the other,
and whoever wrote it only ever looked at the one their machine was in.

### One correction

The first version read the **built** site, `site/index.html`, and skipped when it was
absent. `tests/unit/test_suite_policy.py` bans a skip in a test body — a skipped case
reads in a report as a gate that ran. It was also the wrong split of labour:
`pixi run docs` is `mkdocs build --strict` and is already in the gate, so *that* it
renders is proven there. What is proven here is that the declarations exist to render.

Verified by hand against the built site before that change: five chips, a real
`div.grid.cards`, the stylesheet linked, and no occurrence of the accelerator's name.
