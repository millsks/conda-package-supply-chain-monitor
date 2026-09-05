"""The rows the database has to enforce, and the mapping cardinality it has to allow.

What `tests/unit/django_apps/test_identity_models.py` cannot show. That module
proves the *declaration* -- `unique=True` on `canonical_name`, a
`UniqueConstraint` over `(package, name)` -- and it proves it without a database
because a declaration is in `_meta`. The other half is that the declaration
reaches a table: a constraint that was declared and never migrated satisfies
every introspection assertion and refuses nothing at all, and the failure surfaces
as a duplicate package appearing months later rather than as a test.

So every case here writes and reads. `@pytest.mark.django_db` wraps each in a
transaction that rolls back, which is what leaves the database as it was found.

**Refusals are asserted inside `transaction.atomic()`.** A statement that raises
`IntegrityError` marks the surrounding transaction broken, and pytest-django's
per-test transaction *is* the surrounding one -- so an unwrapped
`pytest.raises(IntegrityError)` passes and then fails the teardown of a case that
had nothing wrong with it. The inner atomic block is a savepoint the failure
rolls back to, leaving the outer transaction usable.

**No `connection.vendor` branch, and no assertion on a constraint's message.**
The suite runs on the sqlite fallback and `pixi run gate-postgres` runs the same
cases against `postgres:17`; the two spell a unique violation differently in
prose -- SQLite names the columns, PostgreSQL names the constraint -- so
asserting on the message would either fail on one backend or would need the
branch. `IntegrityError` is what both raise, and it is the whole claim: the
second write is refused by the database rather than by application code.
"""

from __future__ import annotations

from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction

from conda_package_supply_chain_monitor.identity.models import Feedstock
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import Package
from tests.clocks import FIXED_INSTANT

#: The package the cases resolve, and the second one the per-package constraint
#: is measured against. Real conda-forge names rather than `foo` and `bar`: the
#: pair below is exactly the shape `CPM-FR-1`'s "zero or more" exists for.
A_PACKAGE_NAME: Final[str] = "numpy"
ANOTHER_PACKAGE_NAME: Final[str] = "scipy"

#: Two feedstocks one package legitimately maps to.
A_FEEDSTOCK_NAME: Final[str] = "numpy"
ANOTHER_FEEDSTOCK_NAME: Final[str] = "numpy-base"

#: How many packages map to a feedstock of one name when the per-package
#: constraint is doing its job. Named rather than spelled at the assertion,
#: because the number is the claim: a constraint narrowed to `name` alone would
#: make it one.
SHARED_FEEDSTOCK_NAME_MAPPINGS: Final[int] = 2


def _resolve(name: str, **fields: object) -> Package:
    """Create a package row the way resolution will.

    Args:
        name: The canonical name for the row.
        fields: Any further identity fields to set.

    Returns:
        The saved `Package`. `resolved_at` comes from `tests.clocks.FIXED_INSTANT`
        rather than from the wall clock, which is what the injected clock
        (`CPM-AD-26`) makes possible and what `CPM-AD-25` says every creator of a
        package row must supply.

    """
    return Package.objects.create(canonical_name=name, resolved_at=FIXED_INSTANT, **fields)


@pytest.mark.django_db
def test_a_shell_persists_at_unmapped_confidence_with_every_mapping_absent() -> None:
    """`CPM-AD-25`: ingestion creates the shell, and the shell asserts nothing.

    A canonical name and a resolution instant are the whole of what a first
    sighting establishes. Every mapping is blank -- which Appendix A.1's data
    rules make *missing* rather than empty -- and the confidence is `unmapped`,
    which is what `CPM-AD-4` then uses to refuse every outward claim about the
    package. Read back from the database rather than asserted on the instance in
    memory, because the defaults that matter are the ones the column holds.
    """
    created = _resolve(A_PACKAGE_NAME)

    package = Package.objects.get(pk=created.pk)

    assert package.confidence == IdentityConfidence.UNMAPPED
    assert package.resolved_at == FIXED_INSTANT
    assert package.display_name == ""
    assert package.source_repository_url == ""
    assert package.primary_purl == ""
    assert package.primary_type == ""
    assert package.conda_purl == ""
    assert package.identity_source == ""
    assert package.associator_key == ""
    assert package.alternative_purls == []
    assert package.cpes == []


@pytest.mark.django_db
def test_the_multi_valued_mappings_round_trip_as_lists() -> None:
    """`CPM-FR-1`: cross-ecosystem identifiers are recorded when derivable.

    The empty list and a populated one are both values, and the column is NOT
    NULL, so "no identifiers" and "these identifiers" are the only two states --
    there is no third that means neither.
    """
    purls = ["pkg:pypi/numpy", "pkg:github/numpy/numpy"]
    cpes = ["cpe:2.3:a:numpy:numpy:*:*:*:*:*:*:*:*"]

    created = _resolve(A_PACKAGE_NAME, alternative_purls=purls, cpes=cpes)

    package = Package.objects.get(pk=created.pk)

    assert package.alternative_purls == purls
    assert package.cpes == cpes


@pytest.mark.django_db
def test_a_second_package_with_the_same_canonical_name_is_refused() -> None:
    """`CPM-AD-3`: one row per canonical name, guaranteed by the database.

    The refusal has to come from the table. An application-level check is a
    check-then-act, and two workers resolving the same package name concurrently
    are exactly the case that defeats it.
    """
    _resolve(A_PACKAGE_NAME)

    with pytest.raises(IntegrityError), transaction.atomic():
        _resolve(A_PACKAGE_NAME)

    assert Package.objects.filter(canonical_name=A_PACKAGE_NAME).count() == 1


@pytest.mark.django_db
def test_a_package_saved_without_a_resolution_instant_is_refused() -> None:
    """`CPM-FR-2`: the resolution timestamp is recorded, and the column is what enforces it.

    Asserted by attempting the write. `resolved_at` being non-null is otherwise
    proven only in prose and in `_meta`, and neither of those is what refuses a
    caller who forgot the instant -- which is the plausible mistake, because the
    idiomatic spellings that would have supplied one (`auto_now_add`,
    `default=timezone.now`) are exactly what `CPM-AD-26` forbids. So the writer
    must hand in a `Clock`'s instant, and this is what happens when it does not.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        Package.objects.create(canonical_name=A_PACKAGE_NAME)

    assert Package.objects.count() == 0


@pytest.mark.django_db
def test_a_package_with_a_blank_canonical_name_is_refused() -> None:
    """`canonical_name_is_present`, enforced by the database rather than by a form.

    `blank=False` is a form rule and nothing in this product runs a form --
    resolution calls the manager directly (`CPM-AD-25`). Without the check
    constraint the empty string is a canonical name the table accepts, and it is
    accepted exactly once: `unique=True` refuses the second one, so the failure
    presents as a duplicate rather than as the nameless row it is. A package with
    no name cannot be corrected, exported or found again.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        _resolve("")

    assert Package.objects.count() == 0


@pytest.mark.django_db
def test_a_feedstock_with_a_blank_name_is_refused() -> None:
    """`feedstock_name_is_present`, and the count that would otherwise have lied.

    A nameless feedstock is worse than a missing one, because it is *counted*:
    `package.feedstocks` returns it, so "this package has a feedstock" reads true
    for a row naming nothing -- which is the claim `CPM-FR-5` forbids making
    about a package whose identity is unresolved.
    """
    package = _resolve(A_PACKAGE_NAME)

    with pytest.raises(IntegrityError), transaction.atomic():
        Feedstock.objects.create(package=package, name="")

    assert package.feedstocks.count() == 0


@pytest.mark.django_db
def test_the_inventory_derived_confidence_stores_the_prds_hyphenated_spelling() -> None:
    """The one deliberate spelling decision in this story, read back off the column.

    `inventory-derived` carries a hyphen because `CPM-AD-4`'s table and the PRD
    glossary spell it that way, and `CPM-AD-5`'s fixed-lowercase rule binds
    derived-status vocabularies rather than identity provenance. Proving that
    against `_meta.choices` alone proves only what was declared: a value that
    round-tripped as anything else -- coerced by the enum, truncated by the
    column -- would ship, and `CPM-IDENTITY-S03`'s gate would then be translating
    between two spellings of one value.

    Read through `values_list` rather than off the model instance, because that
    is the column's own string rather than the `TextChoices` member Django
    rebuilds from it.
    """
    package = _resolve(A_PACKAGE_NAME, confidence=IdentityConfidence.INVENTORY_DERIVED)

    stored = Package.objects.filter(pk=package.pk).values_list("confidence", flat=True).get()

    assert stored == "inventory-derived"
    assert Package.objects.get(pk=package.pk).confidence == IdentityConfidence.INVENTORY_DERIVED


@pytest.mark.django_db
def test_a_package_with_no_feedstock_has_an_empty_mapping_rather_than_an_error() -> None:
    """`CPM-FR-1` says "zero or more", and zero is the ordinary case at `unmapped`.

    The distinction this preserves is `CPM-FR-5`'s: "no feedstock recorded" is
    not "no feedstock exists". An empty queryset is what the row holds; whether
    that means absence is `CPM-CURRENCY-S07`'s policy question, answered from
    evidence and gated on confidence.
    """
    package = _resolve(A_PACKAGE_NAME)

    assert list(package.feedstocks.all()) == []


@pytest.mark.django_db
def test_one_package_maps_to_two_feedstocks() -> None:
    """The cardinality the child table exists for.

    A single `feedstock_url` column on `Package` could not hold both, and the
    packages that map to more than one are exactly the ones a reviewer needs to
    see whole. The reporting layer joins these rows into A.1's
    `Conda-Forge_FeedStock_URL`, separated with `;`.
    """
    package = _resolve(A_PACKAGE_NAME)

    Feedstock.objects.create(package=package, name=A_FEEDSTOCK_NAME)
    Feedstock.objects.create(package=package, name=ANOTHER_FEEDSTOCK_NAME)

    assert sorted(feedstock.name for feedstock in package.feedstocks.all()) == [
        A_FEEDSTOCK_NAME,
        ANOTHER_FEEDSTOCK_NAME,
    ]


@pytest.mark.django_db
def test_the_same_feedstock_cannot_be_mapped_to_one_package_twice() -> None:
    """`one_feedstock_name_per_package`, refused by the database rather than by review.

    A duplicate mapping is not a second mapping: it would make
    `package.feedstocks` answer "how many feedstocks does this package have"
    wrongly, and every count and export built on that answer would inherit the
    error.
    """
    package = _resolve(A_PACKAGE_NAME)
    Feedstock.objects.create(package=package, name=A_FEEDSTOCK_NAME)

    with pytest.raises(IntegrityError), transaction.atomic():
        Feedstock.objects.create(package=package, name=A_FEEDSTOCK_NAME)

    assert package.feedstocks.count() == 1


@pytest.mark.django_db
def test_two_packages_may_map_to_a_feedstock_of_the_same_name() -> None:
    """The constraint is per package, not global, and that is the point of the pair.

    A global unique on `name` would refuse this, and it would be wrong: which
    feedstocks a package maps to is a property of the package. Asserted because a
    constraint narrowed to one column is the plausible mistake, and it passes the
    duplicate-mapping case above unchanged.
    """
    first = _resolve(A_PACKAGE_NAME)
    second = _resolve(ANOTHER_PACKAGE_NAME)

    Feedstock.objects.create(package=first, name=A_FEEDSTOCK_NAME)
    Feedstock.objects.create(package=second, name=A_FEEDSTOCK_NAME)

    assert Feedstock.objects.filter(name=A_FEEDSTOCK_NAME).count() == SHARED_FEEDSTOCK_NAME_MAPPINGS


@pytest.mark.django_db
def test_correcting_a_canonical_name_changes_nothing_else() -> None:
    """`CPM-AD-3`: the name is correctable because nothing references it.

    The mapped rows are reached by the surrogate key, so a rename is an update to
    one column. The assertion is on the *child rows' identity* rather than only
    on their count: a cascade that had rewritten them would leave the count
    intact.
    """
    package = _resolve(A_PACKAGE_NAME)
    feedstock = Feedstock.objects.create(package=package, name=A_FEEDSTOCK_NAME, url="https://example.invalid/numpy")
    before = Feedstock.objects.get(pk=feedstock.pk)

    package.canonical_name = "numpy-corrected"
    package.save()

    after = Feedstock.objects.get(pk=feedstock.pk)

    assert Package.objects.get(pk=package.pk).canonical_name == "numpy-corrected"
    assert after.package_id == before.package_id
    assert after.name == before.name
    assert after.url == before.url
    assert Feedstock.objects.filter(package=package).count() == 1


@pytest.mark.django_db
def test_a_package_row_is_mutable_and_carries_no_history_of_its_own() -> None:
    """`CPM-AD-1`: one *mutable* row per package, which is why nothing volatile belongs on it.

    Resolution upgrades a shell in place -- `unmapped` to `verified`, with the
    mappings it established -- and the prior values are gone. That is correct for
    an identity and catastrophic for an observation, which is the whole reason
    the field set stops where it does. Asserted rather than assumed, because
    `AppendOnlyModel` would have refused this save and a `Package` that had
    quietly acquired it would fail here rather than at the first re-resolution.
    """
    package = _resolve(A_PACKAGE_NAME)

    package.confidence = IdentityConfidence.VERIFIED
    package.primary_purl = "pkg:pypi/numpy"
    package.identity_source = "pypi-associator"
    package.save()

    stored = Package.objects.get(pk=package.pk)

    assert stored.confidence == IdentityConfidence.VERIFIED
    assert stored.primary_purl == "pkg:pypi/numpy"
    assert stored.identity_source == "pypi-associator"
    assert Package.objects.count() == 1
