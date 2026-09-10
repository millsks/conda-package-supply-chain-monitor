# CPM-DOCS-S02: The site wears the product's own skin

Status: ready-for-dev

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

- [ ] `docs/stylesheets/conda-sentinel.css` — the palette, mapped onto Material's.
- [ ] `mkdocs.yml` — `extra_css`, the fonts, the palette toggle in both schemes.
- [ ] `docs/index.md` — rewritten for this product.
- [ ] A state vocabulary usable in prose.

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
