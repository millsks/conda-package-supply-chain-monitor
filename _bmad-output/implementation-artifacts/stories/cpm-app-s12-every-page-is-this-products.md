# CPM-APP-S12: Every page a person sees is this product's

Status: done

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

- [x] `templates/conda_sentinel/_chrome.html` — the top bar, extracted for three callers.
- [x] `config/urls.py` + `surface/urls.py` — the root is `conda_sentinel:home`.
- [x] `templates/base.html` — the product's head, tokens and chrome; Bootstrap kept.
- [x] `allauth/layouts/entrance.html` — it overrides `body`, so the chrome is included.
- [x] The eleven inherited templates, by inheritance; 403/404/500 verified rendered.
- [x] `tests/integration/test_every_page_is_this_products.py`.
- [x] Four accelerator test modules repointed, not deleted.

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

## Dev Agent Record

### Completion Notes

**Eleven templates extended the accelerator's shell**, and they were exactly the pages
somebody reaches when they are *not* on one of this product's screens. The fix is one
shell and one chrome partial rather than eleven edits — `403.html`, `404.html`,
`500.html`, `403_csrf.html`, `pages/about.html`, `users/user_detail.html`,
`users/user_form.html`, `allauth/layouts/manage.html` and
`local_dev/persona_index.html` all changed by inheriting, and were verified rendered
rather than assumed.

**Files added:** `templates/conda_sentinel/_chrome.html`,
`tests/integration/test_every_page_is_this_products.py`.

**Files changed:** `config/urls.py`, `surface/urls.py`, `templates/base.html`,
`templates/conda_sentinel/base.html`, `allauth/layouts/entrance.html`, and four
accelerator test modules. **No model, no migration, no view logic.**

**Each acceptance criterion:**

- **AC 1 (the root).** `conda_sentinel:home` moved from `/home/` to `/`, and `/home/`
  was **not** kept as an alias. Two addresses for one page is what makes a link
  somebody pastes into a ticket disagree with the one in the navigation, and the
  disagreement is invisible until somebody compares them.
- **AC 2 (every page a person reaches).** The accelerator's shell now carries the
  product's head, tokens and chrome. It keeps Bootstrap deliberately: the allauth and
  users templates are written against it, and restyling them is a different piece of
  work from telling a reader which product they are in.
- **AC 3 (renders for somebody signed out).** The navigation is hidden for anonymous
  readers, and that is legibility rather than security — every entry behind it
  redirects them to sign in anyway, so hiding it protects nothing. What it avoids is
  offering somebody five links that all go to the same page, which reads as a broken
  product rather than a locked one.
- **AC 4 (no route serves another product's name).** Swept over *rendered responses*
  rather than template files, which is the criterion's own wording — a grep of
  `templates/` would flag a file nothing routes and would miss a name arriving from a
  setting, a context processor or a third-party form.

**Three decisions worth recording.**

*The chrome became a partial.* It was inline in the product's shell, which was fine
while the product's screens were its only wearer. Three callers now — the product's
shell, the accelerator's, and the allauth entrance layout, which overrides `body`
wholesale — and three copies of a navigation bar is how one comes to list a queue the
others do not.

*The sign-in page is the one that mattered most to get right.* It is where somebody
meets this product, and it was the last page able to leave them unsure what they were
signing in to. It is also why `CPM-APP-S11` left `ThemeView` ungated: the control is
on that page, before anybody holds a role.

*A path prefix was considered and is still deferred.* The product owner raised it
twice, the second time with the stronger argument — that a prefix says which
application a page belongs to if the platform ever hosts more than one. Recorded on
the epic as deferred rather than rejected, on one measured fact: **every product page
is mounted by a single line in `config/urls.py`, and nothing anywhere reverses by
path** — all nine template references go through the `conda_sentinel:` namespace. So
the change is one line whenever a second product actually arrives, which is the
cheapest possible thing to defer.

**Two things found by running it.**

1. **`pages/home.html` is now unreachable.** Nothing routes it since the root became
   this product's. It is left in place rather than deleted — that is the product
   owner's call, not the implementing agent's — and the AC 4 sweep is written over
   served routes, so it does not flag a file nobody can reach. Worth a follow-up.
2. **A fourth test module referenced the retired route name.** The completeness check
   for it was piped through `head`, which showed three files and hid the fourth; the
   suite found it. The count is now asserted rather than eyeballed, and every one of
   the four names its page in a single constant with the reason — those modules are
   about logging, tracing and the ASGI path, not about which page they drive.

**Coverage:** unchanged at 99.10%; this story adds no branches.
