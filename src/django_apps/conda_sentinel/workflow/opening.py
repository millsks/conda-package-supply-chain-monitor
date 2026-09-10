"""What the policy run opens, once it has decided what it thinks.

`CPM-APP-S04` built the table and left this unwired on purpose: the run has to open
the items, and having `core/policy_run.py` import this module would invert the
orchestration `core` is built on. So `core/after_run.py` declares a seam,
`workflow/apps.py` registers this step into it at `ready()`, and the orchestrator
still has never heard of a queue.

**A step reads what the run concluded, and concludes nothing itself.** It looks at
the derived rows the passes wrote and opens an item where one of them says there is
work. It does not decide *whether* something is a problem -- `CPM-AD-10` gives that
to the policy engine -- and it does not rank anything, because the priority pass
already did.

**Every item is opened by finding key**, so a run that has already opened one finds
it rather than making a second. That is `CPM-APP-S04`'s AC 2 and it is what makes
this step safe to run every night: after the first run, most nights open nothing at
all.

**Three sources, three queues.** A vulnerability the passes matched is remediation
work. A licence the passes could not clear is compliance work. A package the
resolver could not identify is identity work, and it is the one that is not
evidence-backed -- the finding is the *absence* of an identity, so the key is built
from the package rather than from a row.

**The confidence gate decides what is even askable.** An `unmapped` package has no
verdicts worth acting on -- every status on it is `unknown` by `CPM-AD-4` -- so it
opens exactly one item, in the identity queue, and none of the others. Opening a
remediation item for a package nobody has identified would put work in a queue that
cannot be done until different work in a different queue is finished first.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from conda_sentinel.core.finding_keys import finding_key_of
from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.policies.models import PackageLicense
from conda_sentinel.policies.models import PackageVulnerability
from conda_sentinel.workflow.services import open_item
from conda_sentinel.workflow.services import open_keyed_item
from conda_sentinel.workflow.states import Queue

if TYPE_CHECKING:
    from conda_sentinel.core.clock import Clock
    from conda_sentinel.core.models import PolicyRun

__all__ = ["IDENTITY_FINDING_TABLE", "OPENING_STEP_NAME", "open_queue_items"]

#: The name the step is registered under, and the one a failed run reports.
OPENING_STEP_NAME: Final[str] = "workflow.open_queue_items"

#: What an identity finding is keyed against.
#:
#: The packages table rather than an evidence table, because this is the one queue
#: whose finding is not an observation: nothing was *seen*, and what makes it work is
#: that resolution could not establish an identity. `packages` is where that fact
#: lives.
IDENTITY_FINDING_TABLE: Final[str] = "packages"

#: The vulnerability verdict that means there is remediation work.
#:
#: Only this one. `no_advisory_matched` is a clean answer and the four sentinels mean
#: the product formed no opinion -- opening work for those would fill a queue with
#: packages nobody can act on, which is the queue nobody then reads.
ADVISORIES_MATCHED: Final[str] = "advisories_matched"

#: The licence verdicts that mean somebody has to look.
#:
#: `manual_review` is the shipped default at every recorded parameter version, so
#: this is currently most packages -- which is correct and is worth knowing: until an
#: operator records a licence rule set (PRD Open Question 4), the compliance queue is
#: the whole inventory. `forbidden` and `restricted` are the verdicts a rule set
#: produces once there is one.
LICENCE_NEEDS_A_HUMAN: Final[frozenset[str]] = frozenset({"manual_review", "restricted", "forbidden"})


def open_queue_items(*, run: PolicyRun, clock: Clock) -> int:
    """Open a queue item for everything this run concluded is work.

    Args:
        run: The finished policy run whose derived rows this reads.
        clock: The clock the stamps are read from (`CPM-AD-26`).

    Returns:
        How many items this call opened. Zero on a night when nothing changed, which
        is the ordinary case once the first run has been through the inventory.

    """
    return sum(
        (
            _open_identity_items(clock=clock),
            _open_remediation_items(run=run, clock=clock),
            _open_compliance_items(run=run, clock=clock),
        ),
    )


def _open_identity_items(*, clock: Clock) -> int:
    """Open an item for every package the resolver could not identify.

    The one queue whose finding is not evidence-backed: nothing was observed, and
    what makes it work is that `CPM-AD-4`'s gate is blanking every verdict on this
    package until somebody resolves it.

    Read off `packages` rather than off a run, because identity is *current state*
    rather than something a run derived -- a package resolved between two runs stops
    needing the work immediately, and the item it already has is closed by a person
    rather than by the next run.

    Args:
        clock: The clock the stamps are read from.

    Returns:
        How many items this opened.

    """
    opened = 0
    for package in Package.objects.filter(confidence=IdentityConfidence.UNMAPPED):
        key, facts = finding_key_of(
            IDENTITY_FINDING_TABLE,
            package.pk,
            [("confidence", IdentityConfidence.UNMAPPED.value)],
        )
        opened += open_keyed_item(
            finding_key=key,
            finding_facts=facts,
            package=package,
            queue=Queue.IDENTITY_REVIEW.value,
            clock=clock,
        ).created
    return opened


def _open_remediation_items(*, run: PolicyRun, clock: Clock) -> int:
    """Open an item for every advisory this run matched to a package.

    Skips `unmapped` packages: every verdict on one is `unknown`, so a remediation
    item would be work that cannot be done until the identity queue is worked first.

    Args:
        run: The finished run.
        clock: The clock the stamps are read from.

    Returns:
        How many items this opened.

    """
    verdicts = (
        PackageVulnerability.objects.filter(policy_run=run, vulnerability_status=ADVISORIES_MATCHED)
        .exclude(package__confidence=IdentityConfidence.UNMAPPED)
        .select_related("package", "vulnerability_finding")
    )
    opened = 0
    for verdict in verdicts:
        finding = verdict.vulnerability_finding
        if finding is None:
            # A determinate verdict names its finding by constraint, so this is
            # unreachable through the passes -- and it is checked rather than
            # assumed, because the alternative is an `AttributeError` inside a
            # nightly run that then reports the whole run failed.
            continue
        opened += open_item(
            evidence=finding,
            package=verdict.package,
            queue=Queue.REMEDIATION.value,
            clock=clock,
        ).created
    return opened


def _open_compliance_items(*, run: PolicyRun, clock: Clock) -> int:
    """Open an item for every licence this run could not clear.

    Args:
        run: The finished run.
        clock: The clock the stamps are read from.

    Returns:
        How many items this opened.

    """
    verdicts = (
        PackageLicense.objects.filter(policy_run=run, license_outcome__in=LICENCE_NEEDS_A_HUMAN)
        .exclude(package__confidence=IdentityConfidence.UNMAPPED)
        .select_related("package", "license_finding")
    )
    opened = 0
    for verdict in verdicts:
        finding = verdict.license_finding
        if finding is None:
            continue
        opened += open_item(
            evidence=finding,
            package=verdict.package,
            queue=Queue.COMPLIANCE_REVIEW.value,
            clock=clock,
        ).created
    return opened
