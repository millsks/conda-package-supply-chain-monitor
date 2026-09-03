"""Persona seeding against a real database.

What the unit tests cannot show: that the declarations become rows, that the
memberships they declare are the memberships the users end up with, that a second
run changes nothing, that a changed declaration revokes as well as grants, and
that the designated groups arrive from `provision_designated_groups` rather than
from anything this package writes.

Every test rolls back. The `db` fixture wraps each in a transaction, which is
what leaves the state as found; `transaction=True` would truncate the tables the
group-provisioning migration seeded and nothing here needs it.

`COMPONENT_RUNTIME` is set explicitly in every test rather than inherited from
the `dev` pixi environment the suite runs in. The suite does inherit it, so the
tests would pass without the fixture -- and would then be asserting the pixi
manifest rather than the seeding contract, and would go green in a component
that had lost the declaration entirely.

Authorship is not re-asserted here. `tests/unit/users/test_provisioning.py`
scans every module under `src/` for a `Group` creation and requires the one
writer to be `django_service/users/provisioning.py`, so `seeding.py` is already
held to AD-27 by that test. What this module adds is the runtime half: that
seeding *calls* the shared mechanism, and that with the mechanism disabled it
surfaces the missing groups instead of creating them.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from typing import Any

import pytest
import structlog
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from config.authorization.claims import ClaimsContract
from config.authorization.mapper import resolve_user
from config.authorization.mapper import sync_for_interactive
from config.local_dev import seed
from config.local_dev import seeding
from config.local_dev.personas import DESIGNATED_STAFF
from config.local_dev.personas import PERSONAS
from config.local_dev.personas import build_claims
from config.local_dev.personas import get_persona
from config.local_dev.personas import resolve_groups
from config.local_dev.seeding import seed_personas
from config.locality import RUNTIME_ENV_VAR
from django_service.users.provisioning import provision_designated_groups

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.integration

# Names that appear nowhere in `src/`, so nothing below can pass because a
# literal in the source happened to match.
IDENTITY_CLAIM = "urn:example:principal-id"
GROUP_CLAIM = "realm_access.roles"
STAFF_GROUP = "shipping-desk-operators"
SUPERUSER_GROUP = "shipping-desk-owners"

# An ordinary group: not designated, so an operator creates it, not AD-27's
# provisioning. It is what a changed declaration moves a persona *to*.
ORDINARY_GROUP = "manifest-readers"

# A designated name nothing provisions, for the disabled-provisioning case.
UNPROVISIONED_STAFF_GROUP = "no-such-designated-group"


@pytest.fixture(autouse=True)
def _local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declare this run local, explicitly rather than by inheritance."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, "local")


@pytest.fixture(autouse=True)
def _contract(settings: SettingsWrapper) -> None:
    """Point the claims contract at names that appear nowhere in the source."""
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim=GROUP_CLAIM,
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )


def _events(captured: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """Select one event by name from a `capture_logs` recording."""
    return [event for event in captured if event["event"] == name]


def _group_names(subject: str) -> set[str]:
    """Return the groups the user carrying an identity key holds."""
    user = get_user_model().objects.get(idp_subject=subject)
    return set(user.groups.values_list("name", flat=True))


def test_seeding_materializes_declared_personas(db: None) -> None:
    """AC #2: the declarations become local accounts, with the memberships declared.

    Resolution is by the identity key (AD-11), so each persona is looked up by
    its declared `subject` rather than by its username -- which is what makes the
    username an attribute rather than an identity.
    """
    assert seed_personas() == [persona.key for persona in PERSONAS]

    for persona in PERSONAS:
        user = get_user_model().objects.get(idp_subject=persona.subject)
        assert user.username == persona.username
        assert user.email == persona.email
        assert user.name == persona.name
        assert set(user.groups.values_list("name", flat=True)) == set(resolve_groups(persona))


def test_the_staff_persona_and_the_read_only_persona_diverge(db: None) -> None:
    """AC #1: the two personas end up with genuinely different authorization.

    The divergence is produced by the mapper reading their claims, not by any
    branch in the seeding: `is_staff` comes from the designated staff group and
    from nothing else.
    """
    seed_personas()

    staff = get_user_model().objects.get(idp_subject=get_persona("staff").subject)
    reader = get_user_model().objects.get(idp_subject=get_persona("reader").subject)

    assert staff.is_staff is True
    assert reader.is_staff is False
    assert staff.is_superuser is False
    assert reader.is_superuser is False
    assert _group_names(staff.idp_subject) != _group_names(reader.idp_subject)


def test_seeding_calls_the_shared_group_provisioning(
    db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #2 / AD-27: the designated groups come from Story 2.3's one callable.

    Called with no argument, so it uses the live app registry -- its `apps`
    parameter is the seam that lets one body serve the data migration too.
    """
    calls: list[tuple[Any, ...]] = []

    def _spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return provision_designated_groups(*args, **kwargs)

    monkeypatch.setattr(seeding, "provision_designated_groups", _spy)
    seed_personas()

    assert calls == [()]
    assert Group.objects.filter(name=STAFF_GROUP).exists()
    assert Group.objects.filter(name=SUPERUSER_GROUP).exists()


def test_seeding_surfaces_missing_groups_rather_than_creating_them(
    db: None,
    monkeypatch: pytest.MonkeyPatch,
    settings: SettingsWrapper,
) -> None:
    """AD-27's load-bearing half: with the provisioning disabled, nothing invents a group.

    This is the test that would fail if `seeding.py` ever grew a
    `Group.objects.get_or_create`. Such an implementation passes every other test
    in this file and every local smoke check, while leaving every deployed
    component ungovernable -- which is precisely why the assertion is that the
    group is *absent* afterwards and that the mapper said so.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim=GROUP_CLAIM,
        staff_group=UNPROVISIONED_STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )
    monkeypatch.setattr(seeding, "provision_designated_groups", lambda *_args, **_kwargs: None)

    with structlog.testing.capture_logs() as captured:
        seed_personas()

    assert not Group.objects.filter(name=UNPROVISIONED_STAFF_GROUP).exists()

    staff = get_user_model().objects.get(idp_subject=get_persona("staff").subject)
    assert staff.is_staff is False
    assert _group_names(staff.idp_subject) == set()

    ignored = _events(captured, "authorization.unknown_group_claim")
    assert [event["group"] for event in ignored] == [UNPROVISIONED_STAFF_GROUP]


def test_seeding_is_idempotent(db: None) -> None:
    """AC #2 and AC #5: a second run resolves the same rows and duplicates nothing.

    Idempotence here is not a re-run guard; it is a consequence of resolution
    being by the identity key. A run that created a second row would mean the
    identity key had stopped being the thing a persona is looked up by.
    """
    user_model = get_user_model()

    seed_personas()
    first = {persona.subject: user_model.objects.get(idp_subject=persona.subject).pk for persona in PERSONAS}

    seed_personas()
    second = {persona.subject: user_model.objects.get(idp_subject=persona.subject).pk for persona in PERSONAS}

    assert first == second
    for persona in PERSONAS:
        assert user_model.objects.filter(idp_subject=persona.subject).count() == 1
    assert user_model.objects.filter(username__in=[persona.username for persona in PERSONAS]).count() == len(PERSONAS)


def test_a_persona_resolves_to_the_same_user_twice(db: None) -> None:
    """AC #5: two sign-ins as one persona are one user.

    Driven through the mapper directly rather than through seeding, because
    "signs in twice" is the sign-in path Story 3.4 mounts, and the property is
    the mapper's: resolution reads `idp_subject` and nothing else.
    """
    provision_designated_groups()
    persona = get_persona("staff")
    claims = build_claims(persona)

    first = resolve_user(claims)
    sync_for_interactive(first, claims)
    second = resolve_user(claims)
    sync_for_interactive(second, claims)

    assert first.pk == second.pk
    assert get_user_model().objects.filter(idp_subject=persona.subject).count() == 1


def test_a_changed_declaration_is_applied_on_re_authentication(db: None) -> None:
    """AC #3: the membership change happens, *including the removal*.

    The removal half is the one that has to be asserted rather than assumed: a
    test that only checks the added group passes while revocation silently never
    happens, which is FR-9's whole point failing quietly. `is_staff` is checked
    with it, because AD-12 clears it from the same diff.
    """
    Group.objects.get_or_create(name=ORDINARY_GROUP)
    seed_personas()

    persona = get_persona("staff")
    assert _group_names(persona.subject) == {STAFF_GROUP}

    # The declaration changes: the staff sentinel is dropped and an ordinary
    # group takes its place. A locally constructed copy stands for an edit to
    # `personas.py`, which is what a developer would actually do.
    changed = replace(persona, groups=(ORDINARY_GROUP,))
    assert DESIGNATED_STAFF not in changed.groups

    claims = build_claims(changed)
    user = resolve_user(claims)
    outcome = sync_for_interactive(user, claims)

    assert _group_names(persona.subject) == {ORDINARY_GROUP}
    assert outcome.added == (ORDINARY_GROUP,)
    assert outcome.removed == (STAFF_GROUP,)
    user.refresh_from_db()
    assert user.is_staff is False


def test_seeding_emits_one_event_per_persona(db: None) -> None:
    """One structured event per persona, carrying what an operator would open a shell for.

    Never `print`, never stdlib `logging`: the seeding output is a log line like
    every other authorization change in this component.
    """
    with structlog.testing.capture_logs() as captured:
        seed_personas()

    events = _events(captured, "local_dev.persona_seeded")
    assert [event["persona"] for event in events] == [persona.key for persona in PERSONAS]
    assert all(event["user_id"] is not None for event in events)

    staff = next(event for event in events if event["persona"] == "staff")
    assert staff["groups"] == (STAFF_GROUP,)
    assert staff["is_staff"] is True


def test_a_deployed_invocation_creates_no_account(
    db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #4, against a real database: the refusal leaves no row behind.

    The unit test proves the mapper is never reached; this proves the outcome
    that matters, which is that a production database is unchanged.
    """
    user_model = get_user_model()
    before = user_model.objects.count()
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")

    with pytest.raises(ImproperlyConfigured):
        seed_personas()

    assert user_model.objects.count() == before
    for persona in PERSONAS:
        assert not user_model.objects.filter(idp_subject=persona.subject).exists()


def test_seeding_performs_no_network_call(db: None, no_network: None) -> None:
    """FR-23 / AC #3: seeding is a database write, and reaches nothing else.

    Neither a registry, nor the identity provider, nor a package index. The
    personas are declared in `personas.py` and the groups come from AD-27's one
    provisioning callable, so there is nothing for seeding to go and fetch --
    which is a property of the design and therefore worth asserting rather than
    assuming.

    Order matters in the signature: `db` opens its connection before
    `no_network` installs the guard, so the guard is never in the way of the
    harness's own database connection -- asserted below rather than left to the
    ordering, so a reordering of the two parameters fails loudly instead of
    quietly asserting less.

    The database is outside what this proves in any case. libpq does its socket
    work inside a C extension and never touches Python's `socket` module, so a
    PostgreSQL connection is invisible to the guard. What the case establishes is
    the claim in the sentence above it: seeding reaches no identity provider, no
    registry and no package index. The positive post-condition is the same one
    `test_seeding_materializes_declared_personas` makes -- every declared
    persona came back, and every one of them is a row -- because a negative
    assertion over seeding that never ran would pass on its own.
    """
    assert connection.connection is not None, "the database connection was opened after the guard, not before it"

    assert seed_personas() == [persona.key for persona in PERSONAS]

    for persona in PERSONAS:
        assert get_user_model().objects.filter(idp_subject=persona.subject).exists()


def test_the_entry_point_seeds_and_reports(db: None) -> None:
    """`python -m config.local_dev.seed` is the runnable form, and it runs.

    Called as a function rather than as a subprocess: a subprocess would resolve
    a different pixi environment and a different database, and the thing worth
    pinning is that the module's `main` sets Django up and drives the same
    seeding the task promises.
    """
    assert seed.main() == [persona.key for persona in PERSONAS]
    for persona in PERSONAS:
        assert get_user_model().objects.filter(idp_subject=persona.subject).exists()


def test_the_entry_point_refuses_a_deployed_run(
    db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entry point adds no escape hatch of its own around the refusal."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")
    with pytest.raises(ImproperlyConfigured):
        seed.main()
