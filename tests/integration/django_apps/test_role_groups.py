"""The product's role groups against a real database.

What the unit tests cannot show: that the migration left three rows behind, that
provisioning them again converges rather than duplicating, and -- the criterion
this story exists for -- that a role asserted by the identity provider actually
becomes a Django group membership, and stops being one when the provider stops
asserting it.

The sync half deliberately calls the *platform's* `sync_authorization` with
nothing stubbed. `AD-10` says the product never re-implements group resolution
and `CPM-FR-30` is satisfied there, so what is under test here is that the claim
the product configures resolves through the mechanism that already exists. A test
that drove a role-specific code path would be testing code this story is
forbidden to write.

Groups are never created directly. `django_service.users.provisioning` is the one
mechanism permitted to create a `Group` (AD-27), and `AD-12`'s "a claim naming no
row is ignored, never created" is defensible only while that guarantee holds -- a
test that made its own rows would hide a real defect in it.

Every test here rolls back. `@pytest.mark.django_db` wraps each in a transaction,
which is what leaves the state as found; `transaction=True` would truncate the
tables the migrations seeded and take the first test's evidence with it.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING
from typing import Any

import pytest
import structlog
from django.apps import apps as global_apps
from django.conf import settings
from django.contrib.auth.models import Group

from conda_package_supply_chain_monitor.core.roles import RoleContract
from conda_package_supply_chain_monitor.core.roles import role_group_permissions
from config.authorization.exceptions import ClaimsRejected
from config.authorization.mapper import sync_authorization
from django_service.users import provisioning
from django_service.users.provisioning import provision_designated_groups
from django_service.users.provisioning import provision_groups
from tests.factories import UserFactory

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

    from django_service.users.models import User

MIGRATION_MODULE = "conda_package_supply_chain_monitor.core.migrations.0001_provision_role_groups"

# Names chosen to look nothing like the ones the suite is configured with, so a
# case passing on them cannot be passing on a literal in the source.
A_REVIEWER_GROUP = "wharf-inspectors"
AN_ENGINEER_GROUP = "wharf-riggers"
A_LEADERSHIP_GROUP = "wharf-masters"

AN_UNCONFIGURED_CONTRACT = RoleContract(security_reviewer="", packaging_engineer="", leadership="")

SUBJECT = "urn:example:principal:role-holder"

# How many role slots there are, and so how many rows a fully configured contract
# pointing at three distinct groups asks for.
ROLE_COUNT = 3


@pytest.fixture
def arbitrary_contract(settings: SettingsWrapper) -> RoleContract:
    """Point the role contract at three groups no migration has created."""
    contract = RoleContract(
        security_reviewer=A_REVIEWER_GROUP,
        packaging_engineer=AN_ENGINEER_GROUP,
        leadership=A_LEADERSHIP_GROUP,
    )
    settings.ROLE_CONTRACT = contract
    return contract


@pytest.fixture
def colliding_contract(settings: SettingsWrapper) -> RoleContract:
    """Point one role slot at the group the claims contract already designates.

    Not a contrived state. "Platform and engineering leadership" and the group
    that confers `is_staff` are frequently one directory group, and this codebase
    already treats the analogous collision *within* the claims contract -- both
    designated variables naming one group -- as a configuration rather than a
    mistake.
    """
    contract = RoleContract(
        security_reviewer=A_REVIEWER_GROUP,
        packaging_engineer=AN_ENGINEER_GROUP,
        leadership=settings.CLAIMS_CONTRACT.staff_group,
    )
    settings.ROLE_CONTRACT = contract
    return contract


@pytest.fixture
def role_holder(db: None) -> User:
    """A user carrying an identity key, as `resolve_user` would have left it."""
    created: User = UserFactory.create(username="reviewer", idp_subject=SUBJECT)
    return created


def _claims(*names: str, groups: bool = True) -> dict[str, Any]:
    """Build a claim set asserting `names` at the configured group claim.

    Args:
        names: The group names the token asserts.
        groups: False to omit the group claim entirely, which is the case AD-12
            makes a refusal rather than an assertion of no groups.

    Returns:
        The claims, keyed by the names `settings.CLAIMS_CONTRACT` configures.

    """
    contract = settings.CLAIMS_CONTRACT
    claims: dict[str, Any] = {contract.identity_key_claim: SUBJECT}
    if groups:
        claims[contract.group_claim] = list(names)
    return claims


# ---------------------------------------------------------------------------
# AC #1, first half -- the rows exist, provisioned by migration.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_migration_provisions_the_three_role_groups() -> None:
    """Asserted on the state the migration left, before anything here provisions.

    Nothing in this test creates a group. `core/0001_provision_role_groups` ran
    when the test database was built, and what is read back is its output -- which
    is the only way to show that the migration is what guarantees the rows,
    rather than some later call that happens to run first in production too.
    """
    expected = set(role_group_permissions(settings.ROLE_CONTRACT))

    assert len(expected) == ROLE_COUNT
    assert set(Group.objects.filter(name__in=expected).values_list("name", flat=True)) == expected


@pytest.mark.django_db
def test_the_role_groups_carry_no_permissions() -> None:
    """Membership is the fact this story establishes; grants arrive with the surfaces.

    Asserted against the rows rather than only against the declaration, because
    an empty tuple in the declaration and an empty permission set on the row are
    different claims: `permissions.set` is what makes the second follow from the
    first, and a grant attached by hand in the admin would show up here.
    """
    for name in role_group_permissions(settings.ROLE_CONTRACT):
        assert Group.objects.get(name=name).permissions.count() == 0


# ---------------------------------------------------------------------------
# Provisioning through the one writer.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_provisioning_creates_a_row_per_configured_role_and_converges(
    arbitrary_contract: RoleContract,
) -> None:
    """Three names in, three rows out, and the second pass creates nothing.

    Idempotence is structural rather than a re-run guard, so it is asserted at
    the call site: `migrate` is run again on every deployment, and a second
    insert would either duplicate or raise.
    """
    asked = role_group_permissions(arbitrary_contract)

    first = provision_groups(asked)
    second = provision_groups(asked)

    assert set(first.created) == set(asked)
    assert first.existing == ()
    assert second.created == ()
    assert set(second.existing) == set(asked)
    assert Group.objects.filter(name__in=asked).count() == ROLE_COUNT


@pytest.mark.django_db
def test_two_slots_naming_one_group_produce_one_row(settings: SettingsWrapper) -> None:
    """An operator may legitimately point two role variables at one group.

    A small deployment where the packaging engineers are also the leadership
    audience is a configuration, not a mistake. It must produce one row rather
    than two passes over the same name, because the second pass would `set` its
    own permissions over the first's and silently clear the earlier grant.
    """
    settings.ROLE_CONTRACT = RoleContract(
        security_reviewer=A_REVIEWER_GROUP,
        packaging_engineer=A_LEADERSHIP_GROUP,
        leadership=A_LEADERSHIP_GROUP,
    )
    asked = role_group_permissions(settings.ROLE_CONTRACT)

    result = provision_groups(asked)

    assert set(result.created) == {A_REVIEWER_GROUP, A_LEADERSHIP_GROUP}
    assert Group.objects.filter(name=A_LEADERSHIP_GROUP).count() == 1


@pytest.mark.django_db
def test_the_migration_forward_provisions_through_the_one_writer(
    arbitrary_contract: RoleContract,
) -> None:
    """The happy path of `forward`, driven directly rather than only inferred.

    Every other provisioning case here calls `provision_groups`, which leaves
    `forward` itself -- the contract read, the guard, and the arguments it hands
    the writer -- exercised by nothing. `*/migrations/*` is omitted from
    coverage, so that gap is invisible to the floor, which is the very reason the
    migration's docstring gives for keeping logic out of it.
    """
    migration = import_module(MIGRATION_MODULE)
    asked = role_group_permissions(arbitrary_contract)

    migration.forward(global_apps, None)

    assert set(Group.objects.filter(name__in=asked).values_list("name", flat=True)) == set(asked)


@pytest.mark.django_db
def test_the_migration_forward_hands_the_writer_the_registry_it_was_given(
    arbitrary_contract: RoleContract,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`apps` is the seam that lets one implementation serve migration and runtime.

    A `forward` that dropped it would provision against the *live* registry from
    inside a migration, which works on a fresh database and fails on any
    deployment whose historical `auth` state differs from the current one -- the
    kind of defect that only appears on the oldest database in the estate.
    """
    migration = import_module(MIGRATION_MODULE)
    received: list[object] = []

    def _spy(groups: object, apps: object = None, **kwargs: object) -> None:
        received.append(apps)

    monkeypatch.setattr(provisioning, "provision_groups", _spy)

    migration.forward(global_apps, None)

    assert received == [global_apps]


@pytest.mark.django_db
def test_the_migration_provisions_nothing_when_the_contract_is_unconfigured(
    settings: SettingsWrapper,
) -> None:
    """`migrate` on a fresh clone must stay usable before any contract exists.

    Driven through the migration's own `forward` rather than through
    `provision_groups`, because the guard being asserted is the migration's: a
    raise here would fire inside `migrate`, before anyone has role groups to
    declare, and leave the database mid-migration over a configuration mistake.

    The skip is logged rather than silent, and the event is asserted: an operator
    who set two of the three variables gets no role groups, and without this line
    would get no signal either.
    """
    migration = import_module(MIGRATION_MODULE)
    settings.ROLE_CONTRACT = AN_UNCONFIGURED_CONTRACT
    before = set(Group.objects.values_list("name", flat=True))

    with structlog.testing.capture_logs() as captured:
        migration.forward(global_apps, None)

    assert set(Group.objects.values_list("name", flat=True)) == before
    events = [event for event in captured if event["event"] == "authorization.provisioning_skipped"]
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["reason"] == "role_contract_unconfigured"


# ---------------------------------------------------------------------------
# The role contract is a second declaration over one `auth_group` table.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_provisioning_a_role_group_never_clears_a_designated_groups_permissions(
    colliding_contract: RoleContract,
) -> None:
    """A shared name must not let the later pass disarm the earlier one.

    `core/0001` declares `users/0003` as a dependency, so in a single `migrate`
    the role pass always runs after the designated groups were given their
    permissions. A `permissions.set` with the role slot's empty declaration would
    clear `users.view_user` and `users.change_user` from that row, and nothing
    would catch it: `stage_two`'s condition asks whether the designated rows
    *exist*, not what they hold. The symptom is staff members authenticating,
    receiving `is_staff`, and landing on an empty admin index.
    """
    migration = import_module(MIGRATION_MODULE)
    provision_designated_groups()
    shared = Group.objects.get(name=colliding_contract.leadership)
    before = set(shared.permissions.values_list("pk", flat=True))

    migration.forward(global_apps, None)

    shared.refresh_from_db()
    assert before, "the designated staff group must hold permissions for this to mean anything"
    assert set(shared.permissions.values_list("pk", flat=True)) == before


@pytest.mark.django_db
def test_the_migration_reverse_never_deletes_a_designated_group(
    colliding_contract: RoleContract,
) -> None:
    """Rolling back the role migration must not take the administrators with it.

    `forward` did not create a row the claims contract names -- `users/0003` did
    -- and deleting it cascades through `auth_user_groups`, removing every
    membership it held. The next start would then refuse for a missing designated
    group, with the memberships already gone.
    """
    migration = import_module(MIGRATION_MODULE)
    provision_designated_groups()
    migration.forward(global_apps, None)
    shared = colliding_contract.leadership

    migration.reverse(global_apps, None)

    assert Group.objects.filter(name=shared).exists()
    assert not Group.objects.filter(name__in=(A_REVIEWER_GROUP, AN_ENGINEER_GROUP)).exists()


@pytest.mark.django_db
def test_the_migration_reverse_removes_only_the_role_groups(
    arbitrary_contract: RoleContract,
) -> None:
    """The rollback half, which nothing else runs.

    `reverse` is executable code kept permanently in the graph -- the operation
    declares `elidable=False` -- so a broken filter, a wrong model or a raise
    would surface only when an operator rolled the migration back, which is the
    worst moment to find out.
    """
    migration = import_module(MIGRATION_MODULE)
    asked = role_group_permissions(arbitrary_contract)
    provision_groups(asked)
    designated = settings.CLAIMS_CONTRACT.staff_group

    migration.reverse(global_apps, None)

    assert not Group.objects.filter(name__in=asked).exists()
    assert Group.objects.filter(name=designated).exists()


@pytest.mark.django_db
def test_the_migration_reverse_deletes_nothing_when_the_contract_is_unconfigured(
    settings: SettingsWrapper,
) -> None:
    """An unconfigured contract names nothing, so the rollback removes nothing.

    The guard matters because the alternative -- falling through to a filter on
    three empty strings -- would delete any group that happened to carry an empty
    name rather than declining to act.
    """
    migration = import_module(MIGRATION_MODULE)
    settings.ROLE_CONTRACT = AN_UNCONFIGURED_CONTRACT
    before = set(Group.objects.values_list("name", flat=True))

    migration.reverse(global_apps, None)

    assert set(Group.objects.values_list("name", flat=True)) == before


# ---------------------------------------------------------------------------
# AC #1, second half -- an asserted role is held, and a revoked one is removed.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_asserted_role_group_is_held_after_the_next_sync(role_holder: User) -> None:
    """The criterion the story exists for, driven through the platform's own mapper.

    Nothing product-specific runs. The role group is an ordinary `Group` and the
    role claim is the ordinary group claim, which is exactly what `AD-10` says:
    the product provisions the rows and the platform resolves them.
    """
    role = settings.ROLE_CONTRACT.security_reviewer

    outcome = sync_authorization(role_holder, _claims(role))

    assert outcome.added == (role,)
    assert outcome.ignored == ()
    assert set(role_holder.groups.values_list("name", flat=True)) == {role}


@pytest.mark.parametrize("slot", ["security_reviewer", "packaging_engineer", "leadership"])
@pytest.mark.django_db
def test_a_role_group_confers_neither_staff_nor_superuser(role_holder: User, slot: str) -> None:
    """The premise the whole design rests on: a role group cannot escalate.

    `sync_authorization` derives both flags from the *designated* names alone, so
    a role group is an ordinary group -- but "ordinary" is exactly the property
    that would be silently lost if a role name were ever pointed at the staff or
    superuser slot, or if the derivation were widened. Asserted per slot, because
    the three are configured independently and only one of them needs to be
    wrong.
    """
    role = getattr(settings.ROLE_CONTRACT, slot)

    outcome = sync_authorization(role_holder, _claims(role))

    assert outcome.is_staff is False
    assert outcome.is_superuser is False
    role_holder.refresh_from_db()
    assert role_holder.is_staff is False
    assert role_holder.is_superuser is False


@pytest.mark.django_db
def test_a_role_revoked_at_the_provider_is_removed_at_the_next_sync(role_holder: User) -> None:
    """Revocation reaches the component at the next resolution, not before.

    `R-2` records the consequence this cannot promise around: a group revoked at
    the provider is honoured until the token the claims came from expires. What
    it does promise is that the *next* resolution removes it, which is the half
    that would otherwise leave a departed reviewer holding the role forever.
    """
    role = settings.ROLE_CONTRACT.packaging_engineer
    sync_authorization(role_holder, _claims(role))

    outcome = sync_authorization(role_holder, _claims())

    assert outcome.removed == (role,)
    assert set(role_holder.groups.values_list("name", flat=True)) == set()


@pytest.mark.django_db
def test_one_role_replaces_another_in_a_single_sync(role_holder: User) -> None:
    """The add and the remove are one diff, so no observer sees both roles at once.

    A person moving between roles is the ordinary case the two tests above only
    cover the ends of; that it is one transaction is what keeps the intermediate
    state -- holding the union, or neither -- unobservable.
    """
    contract = settings.ROLE_CONTRACT
    sync_authorization(role_holder, _claims(contract.security_reviewer))

    outcome = sync_authorization(role_holder, _claims(contract.leadership))

    assert outcome.added == (contract.leadership,)
    assert outcome.removed == (contract.security_reviewer,)
    assert set(role_holder.groups.values_list("name", flat=True)) == {contract.leadership}


# ---------------------------------------------------------------------------
# AC #3 -- an absent group claim is refused, and is distinguishable from zero.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_absent_group_claim_is_refused(role_holder: User) -> None:
    """A misconfigured claim *name* must not read as "this person has no roles".

    The two are indistinguishable on the row afterwards, so treating the absent
    case as an assertion of no groups is how a misconfiguration presents as a
    permissions bug -- and, with role-scoped surfaces, as a queue that silently
    empties for everyone.
    """
    with pytest.raises(ClaimsRejected):
        sync_authorization(role_holder, _claims(groups=False))


@pytest.mark.django_db
def test_a_group_claim_asserting_no_groups_syncs_to_no_roles(role_holder: User) -> None:
    """The other side of the same distinction: present and empty is legitimate.

    An authenticated caller holding no role is a real state -- somebody in the
    directory who has not been granted one yet. It syncs, and it does not raise.
    """
    outcome = sync_authorization(role_holder, _claims())

    assert outcome.added == ()
    assert outcome.removed == ()
    assert outcome.ignored == ()
    assert set(role_holder.groups.values_list("name", flat=True)) == set()
