# CPM-DOCS-S06: A path through it, not a pile of it

Status: done

Epic: `CPM-EP-DOCS` — Documentation that says which product it is about

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. The second
> half of the product owner's request: a primer taking somebody from novice to
> professional, onboarding to maintain both the code and the running system. See the
> epic entry.

## Story

As a maintainer in my first week,
I want a sequence to work through with a terminal open,
so that I learn this product by using it rather than by reading about it.

## Acceptance Criteria

1. **Given** somebody who has never seen this codebase
   **When** they follow the primer from the top
   **Then** each part ends with something to run and a result to compare against

2. **Given** the primer
   **When** it covers a subsystem
   **Then** it distils enough to act on and links to the page that holds the detail,
   rather than restating it

3. **Given** every other page about this product
   **When** the primer is read
   **Then** it links to all of them

4. **Given** the tables the primer carries
   **When** the code they describe changes
   **Then** a test fails

5. **Given** a reader who finishes it
   **When** they check themselves against its closing list
   **Then** the list is about what they can *do*, not what they have read

## Tasks / Subtasks

- [x] `docs/conda-sentinel/onboarding.md` — ten parts and a graduation checklist.
- [x] `mkdocs.yml` and `index.md` — first under the product, not last.
- [x] `tests/unit/django_apps/test_documented_subsystems.py` — ten primer cases.
- [x] `tests/unit/test_documentation_commands.py` — seven instructional pages, not two.

## Dev Notes

### What was actually missing

After `CPM-DOCS-S05` there are eleven pages about this product and they are good
pages. What there was no such thing as is an **order to read them in**.

The failure is specific and it is not "there are no docs". Every page is a reference;
references assume you know what you are looking for; somebody in their first week does
not. A new maintainer met a navigation menu and had to guess whether architecture or
operations came first — and the honest answer, that they should run the thing before
reading either, was written nowhere.

### A curriculum, not a twelfth reference

The temptation with a page like this is to make it complete, at which point it is the
site again with a different table of contents. It stays a *path*: what to run, what to
look at, what the thing you are looking at means, and where the full answer lives.

Ten parts. Every one ends with something to run and a result to compare against,
because a reader who has not opened a terminal has learned the vocabulary and none of
the product — and the vocabulary is the easy half.

The closing checklist is deliberately about **doing**: trace a person from an OIDC
claim to a refused queue, name the two tasks nothing fires, move a queue item and name
every step. A checklist of things read is a checklist nobody fails.

## Dev Agent Record

### Completion Notes

**Files added:** `docs/conda-sentinel/onboarding.md`.
**Files changed:** `mkdocs.yml`, `docs/conda-sentinel/index.md`,
`tests/unit/django_apps/test_documented_subsystems.py`,
`tests/unit/test_documentation_commands.py`.

### The command sweep was covering two pages out of seven

`INSTRUCTIONAL_PAGES` held `running-it.md` and `maintaining-it.md`. Four of
`CPM-DOCS-S05`'s pages give commands or send somebody to a URL and none of them was
swept, and the primer — **the page a person reads with a terminal open, where a wrong
command costs the most** — would have been the fifth.

That audit exists because a first draft of `running-it.md` said
`python manage.py run_policy_now`, which does not exist. Widening it from two pages to
seven is the same fix applied to the same failure a second time.

### Ten cases on the primer's own tables

The collector roster is swept against `registered_collectors()` — **name and evidence
table both**. A collector missing from it matters more than usual here: three of the
ten ship with no source declared and observe nothing until configured, so somebody who
never learned a collector exists never learns theirs is inert. The page is also
asserted to *say* that about them.

The precedence order is compared against `OutcomeState`'s own declaration. The first
version of that case searched for each state's first occurrence on the page and failed
— `ok` appears in the vocabulary table well above the precedence line, so it was
measuring the order of the prose rather than the order the page states. It parses the
arrow line itself now, which is the claim.

`test_the_primer_links_to_every_page_it_is_the_path_through` enumerates the sibling
pages from the directory rather than a list, so a page added later and not linked from
the primer fails here — which is the failure a curriculum has: a page reachable only by
scrolling a menu is one a new maintainer meets by accident.

### Verified by reintroducing the errors

The precedence line was reversed and one collector renamed in the roster. Exactly those
two cases failed. Restored, and all forty in the module pass.

Every relative link and anchor in `docs/` was resolved by script again after the primer
landed — `mkdocs build` reports neither at this configuration, and the primer is almost
entirely cross-references.
