# The policy parameters

The versioned rule data a policy pass applies (`CPM-AD-8`, `CPM-FR-40`). One
reviewed TOML file, `policy-parameters.toml`, read by `policies/parameters.py`
and keyed by the **policy version the run declares**.

It ships inside the wheel, beside the module that reads it, exactly as
`collectors/data/`'s watchlist does — and for the same reason: a path computed
from `BASE_DIR` works in a checkout and fails in a container.

The contract cannot live in the file itself, because an unrecognised key is a
refused file rather than a comment. It lives here.

## Why a file

A **setting** would be per-deployment rather than per-version, so two components
running the same policy version could disagree about what that version means. A
**database table** would be a write path nothing audits: a verdict would change
because somebody ran an `UPDATE`, with no diff and no reviewer. `CPM-AD-14` makes
reviewed reference data in the repository this product's governed shape for
exactly this, and a change here is a pull request.

## The shape

```toml
[versions."<policy version>"]
feedstock_inactivity_days = <positive whole number>
```

`versions` is the only top-level table, and each entry under it is one policy
version's complete parameter set.

| Key | Required | Meaning |
|---|---|---|
| `feedstock_inactivity_days` | yes | How long a feedstock may go without a push to its repository before `CPM-FR-40`'s policy calls it **inactive**. A positive whole number of days. A feedstock pushed to *exactly* this long before the run's evidence cut-off is still `present_and_maintained`; inactivity begins strictly after it. |

What counts as recipe activity is **not** a parameter. `CPM-CURRENCY-S03` fixed
it — a push to the feedstock repository — and the collector records the instant.
This file only says how long a gap has to be.

**A version's policy version string is the operator's, not this component's.**
`CPM-AD-8` makes the version the identity of the *rule data*, so the strings here
are whatever review calls its rule sets. The shipped entry uses a year-month
form; nothing enforces that.

## Editing

The whole file is validated at the first read in a process, and every refusal
raises `ImproperlyConfigured` naming this file and the fault.

**Changing a threshold means adding a version entry, not editing a number.**
That is the rule, and it has one exception: a version no run has ever recorded
may be edited in place, because there is nothing to keep replayable. Once a run
has been recorded at a version, that version's entry has to keep saying what it
said — `CPM-FR-22`'s replay reproduces a recorded run's output, and it can only
do that while the rules it applied are still readable. Editing in place does not
fail loudly; it silently rewrites what every past run at that version meant.

Either way it is a change to *this file* and nothing else. No code changes, no
constant moves, and no test asserts the number.

* **An unrecognised key is refused, not ignored** — a top-level key other than
  `versions`, or a parameter this table does not define. A silently dropped key
  is a reviewer who believes they changed a verdict.
* **A missing, non-integer, boolean, non-positive or absurdly large threshold is
  refused.** No value is repaired and none is defaulted.
* **A version key that names nothing, or that carries surrounding whitespace, is
  refused.** The lookup is exact and the run ledger refuses a version naming
  nothing, so such an entry could never be reached by any run.
* **A policy version with no entry here is refused.** There is no fallback, and
  there must not be one: a defaulted verdict is indistinguishable from a reviewed
  one in every report that reads it.
* Save as UTF-8. TOML is UTF-8 by specification.

## Two things a change does not do by itself

**It does not take effect in a running process.** The file is read once per
process, on purpose: `CPM-AD-8` makes one policy version mean one rule set, and a
file re-read per package would let an edit part-way through a run judge half the
inventory under one threshold and half under another. So a corrected file takes
effect at the next process start — which shipping a new artifact already is. This
is deliberately unlike `collectors/data/`'s watchlist, which is re-read on every
sweep because an operator corrects it between them.

**It does not update the suite's own version constant.** Adding or renaming a
version here obliges an edit to `tests/passes.py`'s `A_RECORDED_POLICY_VERSION`
**only if you removed or renamed the version that constant names**. Three
integration modules execute real policy runs at it, and each of them would fail
every package if it stopped being recorded. Adding a *new* version beside it
needs no test change at all — which is the ordinary case, and the one this file's
editing rule above asks for.

## The operational consequence, stated plainly

**A policy run must name a version this file records, or every package fails.**
`CPM-AD-23` contains the refusal to one package at a time, so the run finalizes
`partial` or `failed` and the ledger says how many — but a run at an unrecorded
version accomplishes nothing. Check this file before enqueuing `cpm.policy.run`
with a new version string.

## The shipped threshold is provisional

PRD Open Question 10 asks what the inactivity threshold should be, and this
component has not answered it. The value in the file is a starting point with its
reasoning written beside it — the file is the only place the number appears, so
this document does not repeat it — and it is changeable by review **without a
code change**, which is the whole point of the mechanism.

Nothing in the codebase depends on it: the pass reads whatever this file records,
each derived row stores the threshold it applied, and both test tiers
deliberately use a different number so that a pass which had gone back to reading
a constant would fail.
