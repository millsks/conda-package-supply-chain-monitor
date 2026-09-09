"""`CPM-APP-S02`'s AC 3: filtering the health table by anything the policy engine decided.

"Filtering by any derived status, confidence, priority bucket and work type is
supported" names nine facets across two shapes, and the two shapes are why this is a
module rather than a few `filter()` calls in a view.

**Four statuses are columns of the rollup and five are not.** `CPM-AD-21` lets a pass
contribute only a *status* to `package_health`, so currency, feedstock presence,
priority bucket and work type are columns there and can be filtered directly.
Vulnerability, KEV membership, licence and Python readiness live in their own derived
tables keyed `(package, policy_run)`, and identity confidence is a column of the
rollup again. A facet therefore knows how to build its own condition, and the view
knows only that facets exist.

**A derived-table facet is an `Exists` subquery correlated on the pair**, never a
join. Three reasons and the first is correctness: a join to a table with one row per
package *per run* would match a row from a different run, and the health row's run is
the only one it may be read at. The second is that a join multiplies rows and a
paginator counting them would report a page count that is not the number of packages.
The third is `CPM-AD-11`'s requirement that current health stay "ORM-filterable
without raw SQL" -- this is, and a filter that reached for `RawSQL` to express a
correlated condition would be the first crack in that.

**An unknown facet value is refused rather than ignored**, which is a decision about
what a wrong URL should do. Silently dropping `?vuln=criticl` returns the unfiltered
inventory under a URL that claims to be filtered, and the reader has no way to tell
that from a genuinely empty filter. `CPM-AD-24`'s vocabularies are closed, so a value
outside one is a typo or a stale bookmark, and both are better answered than
absorbed.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Final

from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q

from conda_sentinel.identity.confidence import IdentityConfidence
from conda_sentinel.policies.models import PackageLicense
from conda_sentinel.policies.models import PackagePythonReadiness
from conda_sentinel.policies.models import PackageVulnerability
from conda_sentinel.policies.outcomes import CurrencyOutcome
from conda_sentinel.policies.outcomes import FeedstockOutcome
from conda_sentinel.policies.outcomes import KevMembership
from conda_sentinel.policies.outcomes import PackageLicenseOutcome
from conda_sentinel.policies.outcomes import PackagePythonReadinessOutcome
from conda_sentinel.policies.outcomes import PackageVulnerabilityOutcome
from conda_sentinel.policies.outcomes import PriorityBucket
from conda_sentinel.policies.outcomes import WorkType

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    from django.db import models

__all__ = [
    "FACETS",
    "FACETS_BY_PARAM",
    "Facet",
    "UnknownFacetValueError",
    "applied_filters",
    "filter_condition",
]


class UnknownFacetValueError(ValueError):
    """A query string named a value no vocabulary holds.

    Named rather than left as a bare `ValueError` so the view can turn it into a 400
    and nothing else can: a `ValueError` out of a template render or a paginator
    would be caught by the same `except` and reported as a bad filter, which is the
    wrong answer to the wrong question.
    """


@dataclass(frozen=True, slots=True)
class Facet:
    """One thing the health table can be narrowed by.

    A value object rather than a function, because a facet is three things at once
    and a view needs all three: a query-string parameter to read, a vocabulary to
    validate against and to render as checkboxes, and a condition to apply.
    """

    #: The query-string parameter, short because it is typed and shared.
    param: str

    #: What the facet's heading says.
    label: str

    #: The closed vocabulary, as `(value, label)` pairs in declaration order. Read
    #: off the `TextChoices` type the column itself uses -- never restated -- so a
    #: value added to a vocabulary is filterable the day it exists.
    choices: tuple[tuple[str, str], ...]

    #: The rollup column this facet filters, for the eight of nine that have one.
    column: str = ""

    #: The derived model and its status column, for the ones that do not. Empty for
    #: a rollup facet; exactly one of `column` and this is set, which
    #: `tests/unit/django_apps/test_health_filters.py` asserts of every entry.
    derived: tuple[type[models.Model], str] | None = field(default=None)

    def values(self) -> frozenset[str]:
        """Return the vocabulary this facet accepts.

        Returns:
            Every value in `choices`.

        """
        return frozenset(value for value, _label in self.choices)

    def condition(self, selected: Sequence[str]) -> Q:
        """Return the condition narrowing the rollup to the selected values.

        Args:
            selected: The values chosen, already validated.

        Returns:
            A `Q` matching a rollup row whose status is any of them. An empty
            selection returns an empty `Q`, which `filter()` treats as no condition
            -- so "nothing ticked" means "everything", the same as no parameter at
            all.

        Raises:
            UnknownFacetValueError: When a value is outside the vocabulary. Raised
                here rather than at the boundary so a facet cannot be applied
                unvalidated by a caller that forgot.

        """
        if not selected:
            return Q()
        unknown = sorted(set(selected) - self.values())
        if unknown:
            message = (
                f"{self.param}={unknown} names no value {self.label.lower()} can hold. The vocabulary is "
                f"{sorted(self.values())}; a filter that ignored this would return the whole inventory under "
                f"a URL claiming to be filtered."
            )
            raise UnknownFacetValueError(message)
        if self.derived is not None:
            model, status_column = self.derived
            return Q(
                Exists(
                    model._default_manager.filter(  # noqa: SLF001 - the manager a type-annotated model has
                        package_id=OuterRef("package_id"),
                        policy_run_id=OuterRef("policy_run_id"),
                        **{f"{status_column}__in": list(selected)},
                    ),
                ),
            )
        return Q(**{f"{self.column}__in": list(selected)})


#: Every facet the health view offers, in the order the sidebar renders them.
#:
#: The order follows the mockup and puts the two a reviewer opens the screen for --
#: vulnerability and identity confidence -- above the rest. `WorkType` and
#: `PriorityBucket` come next because they are how a queue is found, and currency,
#: licence, readiness and feedstock last because they are how a question is answered
#: rather than how work is chosen.
#:
#: **Every vocabulary is read off the type the column declares.** Restating one here
#: would be a second declaration of a closed set, and the failure is quiet: a value
#: added to `WorkType` and missing here is simply not filterable, on a screen whose
#: facet counts would still add up.
FACETS: Final[tuple[Facet, ...]] = (
    Facet(
        param="vuln",
        label="Vulnerability status",
        choices=tuple(PackageVulnerabilityOutcome.choices),
        derived=(PackageVulnerability, "vulnerability_status"),
    ),
    Facet(
        param="kev",
        label="KEV membership",
        choices=tuple(KevMembership.choices),
        derived=(PackageVulnerability, "kev_membership"),
    ),
    Facet(
        param="confidence",
        label="Identity confidence",
        choices=tuple(IdentityConfidence.choices),
        column="confidence",
    ),
    Facet(
        param="priority",
        label="Priority bucket",
        choices=tuple(PriorityBucket.choices),
        column="priority_status",
    ),
    Facet(
        param="work",
        label="Work type",
        choices=tuple(WorkType.choices),
        column="work_type_status",
    ),
    Facet(
        param="currency",
        label="Currency",
        choices=tuple(CurrencyOutcome.choices),
        column="currency_status",
    ),
    Facet(
        param="licence",
        label="Licence",
        choices=tuple(PackageLicenseOutcome.choices),
        derived=(PackageLicense, "license_outcome"),
    ),
    Facet(
        param="py314",
        label="Python 3.14 readiness",
        choices=tuple(PackagePythonReadinessOutcome.choices),
        derived=(PackagePythonReadiness, "readiness"),
    ),
    Facet(
        param="feedstock",
        label="Feedstock presence",
        choices=tuple(FeedstockOutcome.choices),
        column="feedstock_presence_status",
    ),
)

#: The same roster keyed by parameter, for reading a query string.
FACETS_BY_PARAM: Final[dict[str, Facet]] = {facet.param: facet for facet in FACETS}


def applied_filters(query: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """Return which facet values a request selected.

    Args:
        query: The request's query parameters, as a mapping from parameter to the
            list of values given for it. `QueryDict.lists()` produces exactly this,
            and taking the mapping rather than the request keeps this callable from
            a test with no request at all.

    Returns:
        One entry per facet the request named, keyed by parameter. Parameters that
        are not facets are ignored rather than refused -- `page` and `sort` are
        legitimately there, and so is whatever an analytics tool appends.

    """
    return {
        param: [value for value in values if value]
        for param, values in query.items()
        if param in FACETS_BY_PARAM and any(values)
    }


def filter_condition(selected: Mapping[str, Sequence[str]]) -> Q:
    """Return the one condition narrowing the rollup by every selected facet.

    Facets combine with AND and values within a facet with OR, which is the
    convention a faceted search establishes and the only one that makes the counts
    beside each checkbox mean anything: ticking a second vulnerability status widens
    the result, ticking a licence as well narrows it.

    Args:
        selected: What `applied_filters` returned.

    Returns:
        The conjunction, empty when nothing is selected.

    Raises:
        UnknownFacetValueError: When any value is outside its facet's vocabulary.

    """
    condition = Q()
    for param, values in selected.items():
        condition &= FACETS_BY_PARAM[param].condition(values)
    return condition
