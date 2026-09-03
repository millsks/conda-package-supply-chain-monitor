"""Group provisioning against a real database.

What the unit tests cannot show: that the rows appear, that the permissions
resolve, and that running the mechanism again converges rather than duplicating.
The first test in this file is the one that carries AC #1 -- it asserts what the
*migration* left behind, before anything in the test calls the mechanism, which
is the only way to prove the ordering trap in `0003_provision_designated_groups`
is actually handled: permissions are created by `post_migrate`, so a data
migration that did not create them first would attach nothing and report
success.

Every test here rolls back. `@pytest.mark.django_db` wraps each in a transaction,
which is enough -- nothing here needs committed state, and
`django_db(transaction=True)` would truncate the tables the migration seeded and
take the first test's evidence with it.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

import pytest
from django.apps import apps as global_apps
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission

from config.authorization.claims import ClaimsContract
from django_service.users import provisioning
from django_service.users.provisioning import DESIGNATED_GROUP_PERMISSIONS
from django_service.users.provisioning import STAFF_ROLE
from django_service.users.provisioning import SUPERUSER_ROLE
from django_service.users.provisioning import provision_designated_groups

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

# Names chosen to look nothing like the ones the suite is configured with, so
# that a test passing on them cannot be passing on a literal in the source.
ARBITRARY_STAFF_GROUP = "shipping-desk-operators"
ARBITRARY_SUPERUSER_GROUP = "shipping-desk-owners"


def _permission_labels(group: Group) -> set[str]:
    """Return a group's permissions as `app_label.codename` strings."""
    return {
        f"{app_label}.{codename}"
        for app_label, codename in group.permissions.values_list("content_type__app_label", "codename")
    }


@pytest.mark.django_db
def test_the_migration_provisions_the_designated_groups() -> None:
    """AC #1: the rows exist because the component migrated, not because a test made them.

    Nothing is called here. The test database is built by running the migrations,
    so what is asserted is the state `0003_provision_designated_groups` left --
    the groups the contract names, carrying resolved permission rows.

    The permissions are the load-bearing half. `auth_permission` is populated by
    the `post_migrate` signal, which fires after the whole `migrate` run, so a
    data migration that did not create the permissions for `users` itself would
    find nothing to attach, attach nothing, and raise nothing.

    A stale reused test database predates this migration and will fail here;
    re-run with `--create-db`.
    """
    contract = settings.CLAIMS_CONTRACT
    staff = Group.objects.get(name=contract.staff_group)
    superuser = Group.objects.get(name=contract.superuser_group)

    assert _permission_labels(staff) == set(DESIGNATED_GROUP_PERMISSIONS[STAFF_ROLE])
    assert _permission_labels(superuser) == set(DESIGNATED_GROUP_PERMISSIONS[SUPERUSER_ROLE])


@pytest.mark.django_db
def test_provisioning_twice_leaves_one_row_per_group() -> None:
    """AC #2: idempotent, creating no duplicates.

    Run twice on top of the migration's own pass, so this is the third
    application of the same mechanism to the same database. The permission set is
    checked after the second call as well: `set` converges, but an
    implementation that switched to `add` would still pass a row count and quietly
    accumulate.
    """
    contract = settings.CLAIMS_CONTRACT

    provision_designated_groups()
    second = provision_designated_groups()

    for name in (contract.staff_group, contract.superuser_group):
        assert Group.objects.filter(name=name).count() == 1

    assert second.created == ()
    assert set(second.existing) == {contract.staff_group, contract.superuser_group}
    assert _permission_labels(Group.objects.get(name=contract.staff_group)) == set(
        DESIGNATED_GROUP_PERMISSIONS[STAFF_ROLE],
    )


@pytest.mark.django_db
def test_the_groups_created_are_the_ones_the_contract_names(settings: SettingsWrapper) -> None:
    """AC #1: seeded from the contract, not from any name in the source.

    The contract is pointed at names that appear nowhere in this product. Exactly
    those rows appear, carrying the declared permissions -- so the declaration is
    doing the work and the names are doing none of it.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim="sub",
        group_claim="groups",
        staff_group=ARBITRARY_STAFF_GROUP,
        superuser_group=ARBITRARY_SUPERUSER_GROUP,
    )

    result = provision_designated_groups()

    assert set(result.created) == {ARBITRARY_STAFF_GROUP, ARBITRARY_SUPERUSER_GROUP}
    assert result.permissions_attached == len(DESIGNATED_GROUP_PERMISSIONS[STAFF_ROLE]) + len(
        DESIGNATED_GROUP_PERMISSIONS[SUPERUSER_ROLE],
    )
    assert _permission_labels(Group.objects.get(name=ARBITRARY_STAFF_GROUP)) == set(
        DESIGNATED_GROUP_PERMISSIONS[STAFF_ROLE],
    )
    assert _permission_labels(Group.objects.get(name=ARBITRARY_SUPERUSER_GROUP)) == set(
        DESIGNATED_GROUP_PERMISSIONS[SUPERUSER_ROLE],
    )


@pytest.mark.django_db
def test_one_group_named_for_both_roles_keeps_the_union_of_their_permissions(
    settings: SettingsWrapper,
) -> None:
    """A small deployment where every administrator is also staff.

    Nothing stops an operator pointing both variables at one group, and the
    reading of that configuration should be the obvious one. Provisioning per
    role rather than per name would call `set` twice on the same row and let the
    superuser slot's empty declaration clear what the staff slot attached --
    disarming the staff grant on a configuration that reads as widening it.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim="sub",
        group_claim="groups",
        staff_group=ARBITRARY_STAFF_GROUP,
        superuser_group=ARBITRARY_STAFF_GROUP,
    )

    result = provision_designated_groups()

    assert result.created == (ARBITRARY_STAFF_GROUP,)
    assert Group.objects.filter(name=ARBITRARY_STAFF_GROUP).count() == 1
    assert _permission_labels(Group.objects.get(name=ARBITRARY_STAFF_GROUP)) == set(
        DESIGNATED_GROUP_PERMISSIONS[STAFF_ROLE],
    ) | set(DESIGNATED_GROUP_PERMISSIONS[SUPERUSER_ROLE])


@pytest.mark.django_db
def test_an_unresolvable_permission_is_skipped_and_never_created(
    settings: SettingsWrapper,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-12's discipline applied to codenames: log it, skip it, never invent it.

    A codename that matches no row means either a mistake in the declaration or
    an app whose permissions do not exist yet. Creating the row would convert
    both into a grant nobody authorised, and the second case is exactly what the
    migration's `create_permissions` call exists to make impossible.
    """
    monkeypatch.setitem(
        provisioning.DESIGNATED_GROUP_PERMISSIONS,
        STAFF_ROLE,
        ("users.view_user", "users.polish_user"),
    )
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim="sub",
        group_claim="groups",
        staff_group=ARBITRARY_STAFF_GROUP,
        superuser_group=ARBITRARY_SUPERUSER_GROUP,
    )
    before = Permission.objects.count()

    result = provision_designated_groups()

    assert result.permissions_attached == 1
    assert _permission_labels(Group.objects.get(name=ARBITRARY_STAFF_GROUP)) == {"users.view_user"}
    assert Permission.objects.count() == before
    assert not Permission.objects.filter(codename="polish_user").exists()


@pytest.mark.django_db
def test_an_unconfigured_contract_writes_nothing_to_the_database(settings: SettingsWrapper) -> None:
    """Bring-up before a contract exists must be a no-op, not a failure or a guess.

    The database half of the unit test's claim: nothing is created, nothing is
    renamed, and the rows the migration already made are left exactly as they
    were rather than being cleaned up on the way past.
    """
    before = set(Group.objects.values_list("name", flat=True))
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim="",
        group_claim="",
        staff_group="",
        superuser_group="",
    )

    result = provision_designated_groups()

    assert result.created == ()
    assert result.permissions_attached == 0
    assert set(Group.objects.values_list("name", flat=True)) == before
    assert not Group.objects.filter(name="").exists()


@pytest.mark.django_db
def test_the_superuser_group_carries_no_permissions(settings: SettingsWrapper) -> None:
    """`ModelBackend.has_perm` short-circuits on `is_superuser`, so any grant here is unread.

    Asserted against the database rather than only against the declaration,
    because the failure this guards against is an attachment arriving from
    somewhere other than `DESIGNATED_GROUP_PERMISSIONS`.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim="sub",
        group_claim="groups",
        staff_group=ARBITRARY_STAFF_GROUP,
        superuser_group=ARBITRARY_SUPERUSER_GROUP,
    )

    provision_designated_groups()

    assert DESIGNATED_GROUP_PERMISSIONS[SUPERUSER_ROLE] == ()
    assert Group.objects.get(name=ARBITRARY_SUPERUSER_GROUP).permissions.count() == 0


@pytest.mark.django_db
def test_the_migration_reverse_removes_the_designated_groups() -> None:
    """The rollback half of `0003_provision_designated_groups`, which nothing else runs.

    `reverse` is executable code kept permanently in the graph -- the operation
    declares `elidable=False` -- but no other test calls it, so a broken filter,
    a wrong model or a raise would surface only when an operator ran
    `migrate users 0002`, which is the worst moment to find out.

    Asserts the two things the function promises: the groups the contract names
    are gone, and a group it does not name is untouched.
    """
    migration = import_module("django_service.users.migrations.0003_provision_designated_groups")
    contract = settings.CLAIMS_CONTRACT
    bystander = Group.objects.create(name="a-group-the-contract-does-not-name")

    migration.reverse(global_apps, None)

    assert not Group.objects.filter(name__in=(contract.staff_group, contract.superuser_group)).exists()
    assert Group.objects.filter(pk=bystander.pk).exists()


@pytest.mark.django_db
def test_the_migration_reverse_deletes_nothing_when_the_contract_is_unconfigured(
    settings: SettingsWrapper,
) -> None:
    """An unconfigured contract names nothing, so the rollback removes nothing.

    The guard matters because the alternative -- falling through to a filter on
    two empty strings -- would delete any group that happened to carry an empty
    name rather than declining to act.
    """
    migration = import_module("django_service.users.migrations.0003_provision_designated_groups")
    settings.CLAIMS_CONTRACT = ClaimsContract("", "", "", "")
    before = set(Group.objects.values_list("name", flat=True))

    migration.reverse(global_apps, None)

    assert set(Group.objects.values_list("name", flat=True)) == before
