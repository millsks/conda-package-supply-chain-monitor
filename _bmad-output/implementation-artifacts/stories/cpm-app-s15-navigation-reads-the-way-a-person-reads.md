# CPM-APP-S15: The navigation reads the way a person reads

Status: done

Epic: `CPM-EP-APP` — The surface the three roles actually work in

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Raised by
> the product owner from the screen. See the epic entry.

## Story

As any of the three roles,
I want the screens to name things the way I would say them,
so that I can read the product without translating its database columns.

## Acceptance Criteria

1. **Given** the navigation
   **When** it is rendered
   **Then** Home is its first entry

2. **Given** a queue anywhere a person reads it
   **When** it is rendered
   **Then** it is the queue's label, never its stored value

3. **Given** a role anywhere a person reads it
   **When** it is rendered
   **Then** it is the role's label, never its slot

4. **Given** a derived status
   **When** it is rendered
   **Then** it is still emitted verbatim, and has acquired no label

## Tasks / Subtasks

- [x] `surface/labels.py` — the display vocabulary, and where the line is drawn.
- [x] `workflow/states.py` — the labels read as labels; migration `0002_queue_labels`.
- [x] `surface/context_processors.py` + `_chrome.html` — order, and value *and* label.
- [x] `surface/views.py` + `queue.html` — the title, heading and "owned by" line.
- [x] `tests/unit/django_apps/test_display_vocabulary.py`.

## Dev Notes

**Satisfies:** nothing directly.

**Governed by:** `CPM-AD-24`, which this story is careful not to break.

### The rule, and why it is not "labels everywhere"

A derived status is emitted verbatim on every surface so the five states mean the same
thing wherever a reader meets them, and `CPM-APP-S07`'s `StatusField` refuses anything
else. A label for `unknown` would be a well-meant improvement that quietly made a
screen disagree with the CSV exported from it.

A queue name and a role name are storage. Nobody says `identity_review` aloud.

So the rule is: **a value a person reads is a status this product asserts, or it has a
label**, and the audit asserts both halves.

## Dev Agent Record

### Completion Notes

**Both of the product owner's observations were defects, and there were two more
behind them.** The nav order and the queue names were what was visible; the queue
page's `<title>`, its heading and its "owned by" line were rendering stored values
too. Four places, one cause: the templates rendered the value where a label existed or
should have.

**Files added:** `surface/labels.py`, `tests/unit/django_apps/test_display_vocabulary.py`,
migration `workflow/0002_queue_labels.py`.

**Files changed:** `workflow/states.py`, `surface/context_processors.py`,
`surface/views.py`, `templates/conda_sentinel/_chrome.html`,
`templates/conda_sentinel/queue.html`.

**A migration, for labels.** Changing a `TextChoices` label changes `choices` on every
field using it, and Django generates an `AlterField`. No column changes and no row
moves — `choices` is validation and display metadata — but
`test_migration_completeness.py` insists it be written down rather than left as a
silent divergence between the models and the graph. That test found it.

**Two decisions worth recording.**

*The labels are spelled out, not derived.* `leadership.title()` is "Leadership" and
the role is called "Platform and engineering leadership". A derived label is one
nobody can correct without first replacing the mechanism, and the correction is always
needed.

*The context processor hands over value **and** label.* The URL needs one and the
reader needs the other, and a template deriving either from the other is precisely
what broke — the nav had the value, needed a label, and rendered what it had.

**Where the labels lived.** A queue's is `Queue`'s own, because that is what a
`TextChoices` label is for. Roles have none anywhere: `core/roles.py` is imported at
settings time and holds the slots and almost nothing else on purpose, so the role
labels are in the presentation layer. Two sources, one module the templates see.

**Coverage:** the new module at 100%.
