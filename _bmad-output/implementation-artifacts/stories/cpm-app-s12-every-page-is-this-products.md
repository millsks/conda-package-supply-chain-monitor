# CPM-APP-S12: Every page a person sees is this product's

Status: ready-for-dev

Epic: `CPM-EP-APP` — The surface the three roles actually work in

> **Acceptance criteria invented.** Raised by the product owner; no functional
> requirement commissions them. They finish what `CPM-RENAME-S02` started. See the
> epic entry.

## Story

As any of the three roles,
I want every page this deployment serves to be recognisably Conda-Sentinel,
so that I can tell I am in the right product, especially when something has gone wrong.

## Acceptance Criteria

1. **Given** the root URL
   **When** it is opened
   **Then** it is this product's home, not the accelerator's landing page

2. **Given** any page a person can reach without knowing a product URL — sign-in,
   account management, `/about/`, and the 403, 404 and 500 pages
   **When** it is rendered
   **Then** it carries this product's name and shell

3. **Given** the product's shell
   **When** it is rendered for somebody who is not signed in
   **Then** it does not offer navigation they cannot use, and does not fail to render

4. **Given** the accelerator's own routes
   **When** they are enumerated
   **Then** none of them serves a page naming a different product

## Tasks / Subtasks

- [ ] `config/urls.py` — the root serves this product.
- [ ] `templates/base.html` — the accelerator shell carries this product's name.
- [ ] The eleven inherited templates that extend it, including 403/404/500.
- [ ] `templates/conda_sentinel/base.html` — renders for an anonymous reader.
- [ ] A sweep asserting no served page names another product.
- [ ] The accelerator tests that assert the old root; updated, not deleted.

## Dev Notes

**Satisfies:** nothing directly. Completes `CPM-RENAME-S02`.

**Governed by:**

- `CPM-AD-13` — authorization is declared per surface and enforced centrally. The
  shell is shared by signed-in and anonymous readers; role scoping stays below the
  navigation, which is why the nav lists every entry to everybody.

### The eleven templates

`403.html`, `403_csrf.html`, `404.html`, `500.html`, `pages/home.html`,
`pages/about.html`, `users/user_detail.html`, `users/user_form.html`,
`allauth/layouts/entrance.html`, `allauth/layouts/manage.html`, and
`local_dev/persona_index.html` — every one of them extends `base.html`, whose
`<title>` and navbar brand still name the accelerator.

The error pages are the ones that matter most. A reviewer who mistypes a package name
is shown a 404 branded for a different product, at the moment they are least able to
tell whether they are in the right place.

### Why not a path prefix

Considered and rejected. Mounting the product's pages under `/conda-sentinel/` moves
`/packages/` and its siblings and leaves `/`, `/about/`, `/accounts/` and every error
page exactly where they are — the product would live in two places and the accelerator
would still own the front door. `FORCE_SCRIPT_NAME` is the mechanism for a deployment
that genuinely needs a prefix, and it moves every route together, including `/api/`,
with no code change.

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
