"""Staleness, derived in one place, and reported *beside* a status rather than as one.

`CPM-AD-28` says an unset per-collector freshness target behaves as "fresh
forever", so six-month-old evidence reads as current -- the `CPM-SM-C1` failure
this product exists to prevent. `core/collection.py` refuses the unset target and
`config/startup/stage_two.py` refuses a registered collector that declares none;
this module is the other half, the comparison those declarations exist to make
possible.

**`stale` is a property of a status, not a status of its own, and that was
decided rather than inferred.** The UX reconciliation settled it and recorded it
as the user's own decision: `--warn` means determinate amber only, and the
visible chip label stays "the bare `OutcomeState` value; staleness moves to the
mark, the footline and the hidden text". A sixth `OutcomeState` member, or a
`FreshnessState` enum beside it, would put a fifth axis back into the channel
`CPM-FR-6` exists to keep un-collapsed -- and would break the shipped audit in
`tests/unit/django_apps/test_outcome_field_audit.py` that asserts the five fixed
values. So `FreshnessReport` below carries the status *unchanged* and the
verdict beside it, and every export carries the `<domain>_observed_at` and
`<domain>_stale` companions the UX already specified.

**Why it is one function rather than eight.** Eight collectors are coming and
every read surface -- the coverage view, the exports, the generated answers --
asks the same question of them. Written where each is used, "is this old" would
be spelled eight ways and would disagree at the boundary, which is exactly the
class of divergence `CPM-AD-5` puts every shared vocabulary in `core` to
prevent.

**Why the boundary is "not stale".** A target is the age evidence *may reach*.
Evidence observed exactly `target` ago has reached it and no more, so it is
fresh; the first instant past it is stale. Stated out loud because the opposite
convention is equally spellable and only one of them can be asserted -- and
because `Collector._inside_window` already had to make the mirror-image decision
for an inclusive `finished_at__gte`.

**Never observed is not old.** A package with no evidence row for a collector
reports `unknown` and *not* stale: an absence of observation is not an old
observation, and reporting it as stale would tell an operator that something
which was never looked at has gone out of date. It is also emphatically not
clean -- `EMPTY_AGGREGATE` in `core/outcomes.py` makes the same choice for the
same reason.

**Every instant is handed in** (`CPM-AD-26`). Nothing here reads a wall clock:
`now` is a parameter, and a naive `now` or a naive `observed_at` is refused
rather than compared, on the same terms `core/ledger.py`'s `_require_aware` and
`core/rate_limit.py`'s `window_key` refuse one. A naive instant compared against
a value read back from PostgreSQL raises inside a Celery task rather than in a
test, and `USE_TZ` being on means the comparison that does not raise is the one
silently shifted by the writer's offset.

**The target's own validity is not re-checked here.** `core/collection.py`'s
`_require_freshness_target` is the one enforcement point for "absent, mistyped,
zero or negative", and a second copy of that rule in this module would be two
places to keep in step -- the argument `core/collection.py`'s docstring already
makes about where the startup refusal lives.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Final

from django.db import models

from conda_package_supply_chain_monitor.core.clock import is_aware
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState

if TYPE_CHECKING:
    from datetime import datetime
    from datetime import timedelta

    from conda_package_supply_chain_monitor.core.models import AppendOnlyModel

__all__ = [
    "OBSERVED_AT_FIELD",
    "PACKAGE_FIELD",
    "UNOBSERVED_STATUS",
    "FreshnessError",
    "FreshnessReport",
    "freshness_of",
    "is_stale",
    "latest_observation",
]

#: The column every evidence model carries, declared by `AppendOnlyModel` and
#: given its meaning by `CPM-AD-7`: "the moment of *this* observation". Named
#: here because the query below orders on it and a string spelled at the call
#: site is one typo away from ordering on the primary key instead.
OBSERVED_AT_FIELD: Final[str] = "observed_at"

#: The column that scopes an observation to one package, by the integer primary
#: key `CPM-AD-3` fixes. Evidence models declare it themselves -- `core` holds no
#: concrete evidence model (`CPM-AD-7`) -- so its absence is a defect in the
#: model rather than something this module can supply, and it is refused with a
#: message naming the model.
PACKAGE_FIELD: Final[str] = "package_id"

#: What a package with no observation at all reports. `unknown`, from the one
#: outcome vocabulary (`CPM-AD-5`), and never `ok`: we did not look, which is a
#: different fact from having looked and found nothing wrong (`CPM-FR-6`).
UNOBSERVED_STATUS: Final[str] = OutcomeState.UNKNOWN.value


class FreshnessError(ValueError):
    """A freshness question was asked in terms it cannot be answered in.

    A `ValueError` subclass, matching `core/rate_limit.py`'s `RateLimitError`,
    `core/outcomes.py`'s `OutcomeVocabularyError` and `core/collection.py`'s
    `CollectorConfigurationError`: every "this input cannot describe what it
    claims to" in this product is a `ValueError`, so a caller catching one
    catches them all.

    One type rather than a hierarchy, on the same terms as `AppendOnlyError`: a
    naive instant and an evidence model with no package reference are both
    defects at the call site or in a class definition, to be fixed where that
    code is written, and no caller branches on which. The detail is in the
    message.
    """


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    """What one `(package, collector)` pair's evidence says, and how old it is.

    Three fields, and the separation between the first two is the whole point:
    the status is carried through *unchanged* and staleness travels beside it, so
    no surface is ever handed one field it has to decide how to collapse. See the
    module docstring for why a sixth `OutcomeState` member was refused.

    Frozen, because it is a report rather than a workspace -- the same reason
    `core/collection.py`'s `CollectionResult` is.

    Attributes:
        status: The `OutcomeState` value the evidence carries, verbatim
            (`CPM-AD-24`), exactly as it was handed in. `UNOBSERVED_STATUS` when
            nothing was ever observed.
        stale: Whether the observation is older than the collector's declared
            freshness target. Always False when nothing was observed: an absence
            of observation is not an old observation.
        observed_at: When the latest observation was made, so a surface can say
            *how* old rather than only *that* it is old -- which is the
            `<domain>_observed_at` companion the UX design contract specifies.
            None when nothing was ever observed.

    """

    status: str
    stale: bool
    observed_at: datetime | None


def is_stale(*, observed_at: datetime, target: timedelta, now: datetime) -> bool:
    """Report whether one observation has aged past a declared freshness target.

    The single comparison. Every collector and every read surface reduces to this
    call, which is what stops eight of them disagreeing about the boundary.

    Args:
        observed_at: When the observation was made, aware.
        target: The age evidence may reach, as declared by the collector. Its
            own validity is `core/collection.py`'s to enforce -- see the module
            docstring for why it is not re-checked here.
        now: The instant to measure from, from the injected clock
            (`CPM-AD-26`), aware.

    Returns:
        True only once the observation is *past* the target. Evidence observed
        exactly `target` ago has reached the age it may reach and no more, so it
        is fresh; the first instant beyond it is stale.

    Raises:
        FreshnessError: When either instant carries no usable offset. Refused
            rather than converted: there is no offset to convert from, and
            guessing one is how a staleness rule comes to answer differently in
            two deployments.

    """
    _require_aware(observed_at, field="observed_at")
    _require_aware(now, field="now")
    return observed_at < now - target


def freshness_of(
    *,
    observed_at: datetime | None,
    target: timedelta,
    now: datetime,
    status: str = UNOBSERVED_STATUS,
) -> FreshnessReport:
    """Derive one freshness report from a status and the observation behind it.

    The composed answer a read surface asks for: the status it must display, the
    staleness marker it must display *beside* it, and the instant it needs to say
    how old the evidence is.

    Args:
        observed_at: When the latest observation for this package and collector
            was made, or None when there has never been one --
            `latest_observation` answers exactly this.
        target: The collector's declared freshness target.
        now: The instant to measure from, from the injected clock.
        status: The `OutcomeState` value the evidence carries, passed through
            untouched. Defaults to `UNOBSERVED_STATUS`, because a caller with no
            observation has no status to hand over: nothing produced one.

    Returns:
        The report. With no observation it reads `status` -- `unknown` by
        default -- not stale, and carries no instant.

    Raises:
        FreshnessError: When `observed_at` or `now` is naive. `now` is checked
            on **both** paths, and that is the point rather than a formality: the
            check used to live only in `is_stale`, which the never-observed path
            returns before reaching, so the same naive clock was refused for a
            package with evidence and accepted for one without. A refusal that
            depends on whether a row happens to exist is one that passes every
            test written against the populated case and reaches production
            through the empty one -- and a naive instant is read as local time,
            which is how two workers in different zones come to disagree about
            what is stale (`CPM-AD-26`).

    """
    if observed_at is None:
        _require_aware(now, field="now")
        return FreshnessReport(status=status, stale=False, observed_at=None)
    return FreshnessReport(
        status=status,
        stale=is_stale(observed_at=observed_at, target=target, now=now),
        observed_at=observed_at,
    )


def latest_observation(evidence_model: type[AppendOnlyModel], *, package_id: int) -> datetime | None:
    """Return when this collector last observed this package, or None.

    Generic over the model rather than over a collector name, because
    `CPM-AD-7` gives every collector its own evidence table: the table *is* the
    collector, so `(package, collector)` is spelled `(package_id, evidence_model)`
    and no evidence row needs to carry a collector column to be found.

    `Max` rather than an ordered fetch: the question is one instant, and pulling
    a row back to read one column off it would load every field of the widest
    table in the product to answer it.

    Args:
        evidence_model: The collector's append-only evidence model.
        package_id: The package being asked about, by the integer primary key
            `CPM-AD-3` fixes.

    Returns:
        The newest `observed_at` for that package, or None when the collector has
        never observed it. None is the answer `freshness_of` turns into
        `unknown`; it is deliberately not `datetime.min`, which would read as an
        observation made a very long time ago and would report stale.

    Raises:
        FreshnessError: When the model declares no package reference. Such a
            model cannot answer a per-package question at all, and the failure
            belongs where the model is declared rather than as a Django
            `FieldError` from inside a policy pass.

    """
    _require_package_reference(evidence_model)
    newest = evidence_model.objects.filter(**{PACKAGE_FIELD: package_id}).aggregate(
        newest=models.Max(OBSERVED_AT_FIELD),
    )
    found: datetime | None = newest["newest"]
    return found


def _require_aware(instant: datetime, *, field: str) -> None:
    """Refuse an instant a freshness comparison cannot be made against.

    Args:
        instant: The value the caller supplied.
        field: Which argument it was, for the message.

    Raises:
        FreshnessError: When the instant carries no usable offset.

    """
    if not is_aware(instant):
        message = (
            f"staleness cannot be decided from the naive {field} ({instant!r}). Every instant comes from a "
            f"Clock, which always answers in UTC (CPM-AD-26); a naive value has no offset to interpret, so "
            f"the comparison would be silently shifted by whichever offset the writer happened to be in."
        )
        raise FreshnessError(message)


def _require_package_reference(evidence_model: type[AppendOnlyModel]) -> None:
    """Refuse an evidence model that cannot be asked about one package.

    Args:
        evidence_model: The model about to be queried.

    Raises:
        FreshnessError: When it declares no `package_id` column.

            Both `name` and `attname` are accepted, and the difference is a
            dated trap rather than defensiveness. Today every evidence model
            declares a plain `package_id` integer, because `CPM-AD-3`'s package
            table does not exist yet and `core/models.py` records why the column
            is not a `ForeignKey`. When `CPM-EP-IDENTITY` builds that table and
            these become `package = models.ForeignKey(...)`, Django names the
            field `package` and its column `package_id` -- so a check reading
            only `name` would refuse every correctly declared model, at the
            moment the product finally had a package to refer to.

    """
    meta = evidence_model._meta  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    if not any(PACKAGE_FIELD in {field.name, field.attname} for field in meta.concrete_fields):
        message = (
            f"{evidence_model.__name__} declares no {PACKAGE_FIELD} column, so it cannot say when one package "
            f"was last observed. Every evidence row references its package by the integer primary key "
            f"CPM-AD-3 fixes."
        )
        raise FreshnessError(message)
