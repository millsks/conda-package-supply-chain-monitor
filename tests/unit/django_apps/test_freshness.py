"""Staleness derived from an instant that was handed in, and reported beside a status.

`core/freshness.py` is the one place this product decides that evidence is old.
Every row of `CPM-EVIDENCE-S06`'s I/O matrix that does not need a table is here:
evidence inside the target, evidence past it, evidence exactly on the boundary,
a package never observed, a determinate status past its target, and the two
naive instants that are refused rather than compared.

**The boundary case is the one worth writing out.** A target is the age evidence
*may reach*, so evidence observed exactly `target` ago is fresh and the first
instant past it is stale. The opposite convention is equally spellable, only one
of them can be asserted, and the difference is invisible in every other case --
which is exactly the kind of decision that gets reversed by accident during a
refactor unless something fails.

**Nothing here reads a wall clock.** Every instant is a constant derived from
`tests/clocks.py`'s `FIXED_INSTANT`, which is what makes "this evidence is two
days old" a statement about the rule rather than about when the suite ran
(`CPM-AD-26`). A staleness test written against `timezone.now()` either waits or
freezes time process-wide, and `R-03` has no credible mitigation with either.

**`latest_observation`'s query is not here, and its refusal is.** The query needs
a real table and is proved in
`tests/integration/django_apps/test_collector_health.py`; the refusal it makes
first -- an evidence model with no package reference cannot answer a per-package
question -- is decided from `_meta` before anything is asked of a database, so it
belongs in the fast tier where the defect it names would actually be introduced.

This is a unit test: it builds a model in an isolated registry and compares
datetimes. No database, no network.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest
from django.db import models
from django.test.utils import isolate_apps

from conda_package_supply_chain_monitor.core.freshness import UNOBSERVED_STATUS
from conda_package_supply_chain_monitor.core.freshness import FreshnessError
from conda_package_supply_chain_monitor.core.freshness import FreshnessReport
from conda_package_supply_chain_monitor.core.freshness import freshness_of
from conda_package_supply_chain_monitor.core.freshness import is_stale
from conda_package_supply_chain_monitor.core.freshness import latest_observation
from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from tests.clocks import FIXED_INSTANT
from tests.collectors import A_NAIVE_INSTANT
from tests.collectors import DETERMINATE_VALUE
from tests.model_registry import FIXTURE_APP
from tests.model_registry import FIXTURE_LABEL

#: The freshness target every case here measures against. A day, so that "half a
#: target ago" and "twice a target ago" are both expressible as fractions of one
#: declaration rather than as intervals written at each call site.
A_TARGET: Final[timedelta] = timedelta(days=1)

#: A margin either side of the boundary. Long enough that no column precision
#: could round it away, short enough that it is unmistakably about the boundary
#: rather than about being obviously old.
A_MARGIN: Final[timedelta] = timedelta(minutes=1)


def test_evidence_inside_the_target_is_not_stale() -> None:
    """The ordinary case: an observation younger than the target is current."""
    observed_at = FIXED_INSTANT - (A_TARGET / 2)

    assert is_stale(observed_at=observed_at, target=A_TARGET, now=FIXED_INSTANT) is False


def test_evidence_past_the_target_is_stale() -> None:
    """The failure `CPM-AD-28` exists to make visible, in its smallest form."""
    observed_at = FIXED_INSTANT - A_TARGET - A_MARGIN

    assert is_stale(observed_at=observed_at, target=A_TARGET, now=FIXED_INSTANT) is True


def test_evidence_exactly_on_the_boundary_is_not_stale() -> None:
    """The decision written out, because the opposite one is equally spellable.

    A target is the age evidence *may reach*. Evidence observed exactly `target`
    ago has reached it and no more, so it is fresh; the first instant past it is
    stale. `Collector._inside_window` already had to make the mirror-image call
    for an inclusive `finished_at__gte`, and the two would drift apart in
    opposite directions with nothing failing.
    """
    exactly = FIXED_INSTANT - A_TARGET

    assert is_stale(observed_at=exactly, target=A_TARGET, now=FIXED_INSTANT) is False
    assert is_stale(observed_at=exactly - A_MARGIN, target=A_TARGET, now=FIXED_INSTANT) is True


@pytest.mark.parametrize(
    ("observed_at", "now"),
    [
        (A_NAIVE_INSTANT, FIXED_INSTANT),
        (FIXED_INSTANT, A_NAIVE_INSTANT),
    ],
    ids=["naive-observation", "naive-now"],
)
def test_a_naive_instant_is_refused_rather_than_compared(observed_at: object, now: object) -> None:
    """Both sides, because either one alone would make the comparison meaningless.

    `USE_TZ` is on, so a naive value is not rejected by the comparison -- it is
    silently read as whatever offset the process happens to be in, and the answer
    is wrong by that offset rather than absent. `core/ledger.py`'s `_require_aware`
    and `core/rate_limit.py`'s `window_key` refuse one for the same class of
    reason, and this is the third.
    """
    with pytest.raises(FreshnessError, match="naive"):
        is_stale(observed_at=observed_at, target=A_TARGET, now=now)  # type: ignore[arg-type]


def test_the_refusal_is_a_value_error() -> None:
    """One family of declaration defects, so a caller catching one catches them all.

    `RateLimitError`, `OutcomeVocabularyError` and `CollectorConfigurationError`
    are all `ValueError` subclasses, and this is the fourth.
    """
    assert issubclass(FreshnessError, ValueError)


def test_a_determinate_status_past_its_target_keeps_its_status() -> None:
    """The matrix row the whole design rests on: `stale` is not a status.

    The visible label stays the bare `OutcomeState` value and staleness travels
    beside it. A sixth `OutcomeState` member, or a report that collapsed the two
    into one field, would put a fifth axis back into the channel `CPM-FR-6`
    exists to keep un-collapsed -- so the assertion is that `ok` is still `ok`
    *and* that the report says stale, not one or the other.
    """
    report = freshness_of(
        observed_at=FIXED_INSTANT - A_TARGET - A_MARGIN,
        target=A_TARGET,
        now=FIXED_INSTANT,
        status=DETERMINATE_VALUE,
    )

    assert report.status == DETERMINATE_VALUE
    assert report.stale is True


def test_a_report_carries_the_observation_instant_beside_the_verdict() -> None:
    """Stale is not enough on its own: a surface has to be able to say how old.

    The `<domain>_observed_at` companion the UX design contract specifies is this
    field, and a report that answered only "stale" would leave every surface
    reconstructing the instant from a second query.
    """
    observed_at = FIXED_INSTANT - (A_TARGET / 2)

    report = freshness_of(observed_at=observed_at, target=A_TARGET, now=FIXED_INSTANT, status=DETERMINATE_VALUE)

    assert report == FreshnessReport(status=DETERMINATE_VALUE, stale=False, observed_at=observed_at)


def test_a_package_never_observed_reads_unknown_and_not_stale() -> None:
    """An absence of observation is not an old observation.

    Reporting it as stale would tell an operator that something nobody ever
    looked at has gone out of date; reporting it as clean is the fold `CPM-FR-6`
    forbids outright. `unknown` is the third answer, and it is the same one
    `EMPTY_AGGREGATE` gives for the same reason.
    """
    report = freshness_of(observed_at=None, target=A_TARGET, now=FIXED_INSTANT)

    assert report == FreshnessReport(status=OutcomeState.UNKNOWN.value, stale=False, observed_at=None)
    assert OutcomeState.UNKNOWN.value == UNOBSERVED_STATUS


def test_a_naive_now_is_refused_even_when_nothing_was_ever_observed() -> None:
    """The refusal must not depend on whether a row happens to exist.

    `freshness_of` returns early for a package with no observation, and the
    awareness check used to live only in `is_stale` -- past that return. So the
    same naive clock was refused for a package with evidence and accepted for one
    without, which is the worst shape a guard can have: every test written
    against the populated case passes, and production meets it through the empty
    one. A sweep over ten thousand packages meets the empty case first and most
    often.
    """
    with pytest.raises(FreshnessError, match="now"):
        freshness_of(observed_at=None, target=A_TARGET, now=A_NAIVE_INSTANT)


def test_a_report_is_a_frozen_record() -> None:
    """A report rather than a workspace, exactly as `CollectionResult` is.

    A surface that could rewrite the verdict it was handed is a surface where the
    derivation happening in one place buys nothing.
    """
    report = freshness_of(observed_at=FIXED_INSTANT, target=A_TARGET, now=FIXED_INSTANT)

    with pytest.raises((AttributeError, TypeError)):
        report.stale = True  # type: ignore[misc]


def test_an_evidence_model_with_no_package_reference_is_refused() -> None:
    """A model that cannot be asked about one package says so where it is declared.

    Without this the caller meets Django's own `FieldError` from inside a policy
    pass, naming a column rather than the rule -- `CPM-AD-3` fixes every evidence
    row's reference to its package, and a model that dropped it is a defect in
    the model.

    The refusal is made from `_meta` before any query is composed, which is what
    keeps this case in the fast tier: the model built here has no table and needs
    none.
    """
    with isolate_apps(FIXTURE_APP):

        class Unscoped(AppendOnlyModel):
            fact = models.TextField()

            class Meta:
                app_label = FIXTURE_LABEL

    with pytest.raises(FreshnessError, match="package_id"):
        latest_observation(Unscoped, package_id=1)
