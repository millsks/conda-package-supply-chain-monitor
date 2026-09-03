"""The two stage-2 conditions that read a database, against real connections.

Condition 7 -- unapplied migrations on a serving process -- and the stage-2 half
of condition 5, a designated group absent from the database (AD-27). Both need a
live connection, which is what puts them here rather than beside the URLconf
conditions in `tests/unit/startup/test_stage_two_urlconf.py`.

**Both are serving-process-only, and that is the property most of these cases
turn on.** AD-13 makes process type fail *open*: `COMPONENT_PROCESS` absent means
this is not a serving process. `manage.py migrate` is the one action that clears
the migrations condition, so a refusal that fired on management commands would
deadlock the FR-41 release stage against a state nothing could resolve (AD-22).
Every case here declares the variable deliberately, and one case asserts what
happens when it is not declared -- which is the exemption itself, and R-3's
recorded price.

**AC #6, and why the fault is always on the second alias.** Stage 1's sqlite
refusal and stage 2's migrations refusal both iterate *every* configured
database, which is only reachable because stage 1 runs after the AD-8
composition step. A test whose fault sits on `default` cannot tell an
implementation that iterates from one that reads `DATABASES["default"]` and
stops, so the second alias is where every fault here is placed.

**Nothing is left behind, and every clause of that is load-bearing.** The second
alias is an in-memory sqlite database that ceases to exist when its connection
closes, and the connection handler is restored to the mapping it held before.
That setup is `tests.conftest.never_migrated_database_alias`, which lives there
rather than here because Story 5.5's `tests/integration/test_release_stage.py`
constructs the same state to assert AD-22's release-stage contract from the
deployment side -- and the `connections`-handler refresh it performs has a silent
failure mode a second copy would eventually get wrong.
No case here creates a `Group`; three *delete* one, inside `django_db`'s
transaction, which rolls the deletion back -- never `TransactionTestCase`
semantics, which would commit it and leave the rest of the session short a row
that `users.0003_provision_designated_groups` put there.

`default` is the pytest-django test database in every case, including the two
that take `django_db_blocker` rather than the `django_db` marker. Those two
request `django_db_setup` explicitly for that reason: the blocker lifts the
connection guard but rebinds nothing, so a case that took it alone would run
`_refuse_unapplied_migrations` -- which iterates every alias, `default` first --
against the repository's own `db.sqlite3`, passing or failing on whatever state
a developer's local artifact happened to be in.

**Where the served-path proof went.** Story 4.3 wrote the ASGI probe that drives
every stage-2 condition from a process that has served a request, and it lived at
the end of this file. FR-16 needs one case per condition rather than one case
over four, so Story 4.5 moved it to
`tests/integration/startup/test_stage_two_served_path.py` and split it there.
Nothing was dropped: the probe source and every assertion it fed are the same,
and the module beside it is now also where the management-command control and
AD-13's exemption are asserted. This file keeps the in-process cases, which are
the ones that need pytest-django's rolling-back transaction.

`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured

from config.locality import PROCESS_ENV_VAR
from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_one
from config.startup import run_stage_two
from tests.conftest import NEVER_MIGRATED_ENGINE
from tests.conftest import deployed_url_patterns
from tests.conftest import never_migrated_database_alias
from tests.conftest import temporary_root_urlconf
from tests.conftest import valid_deployed_settings_namespace

if TYPE_CHECKING:
    from pytest_django.plugin import DjangoDbBlocker

# The alias every fault below is configured under. Never `default`: an
# implementation that read only `DATABASES["default"]` would pass a test whose
# fault sat there, which is the whole of what AC #6 is about.
SECOND_ALIAS = "reporting"

# One of the pending migrations the refusal message has to name. `contenttypes`
# rather than a `users` migration because it is the first thing any Django
# schema needs, so it is pending on any database that was never migrated at all.
A_PENDING_MIGRATION = "contenttypes.0001_initial"

# A serving process type. Any member of `config.locality.SERVING_PROCESSES` does;
# `web` is the one that serves HTTP and therefore the one the conditions exist
# for.
SERVING_PROCESS = "web"


@pytest.fixture(autouse=True)
def _deployed_serving_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declare a deployed serving process, which is what both conditions require.

    Deployed because every condition is deployed-only, and a serving process
    because these two are the only conditions in the contract that additionally
    gate on process type. `OTEL_SDK_DISABLED` is deleted because the AC #6 case
    runs stage 1 as well, and condition 3 reads it off the environment.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)
    monkeypatch.setenv(PROCESS_ENV_VAR, SERVING_PROCESS)


def _refusal() -> str:
    """Run stage 2 over a URL configuration a deployed component would serve.

    The URL configuration is overridden rather than inherited because the suite
    runs local, so `config/urls.py` mounts the local persona sign-in route and
    the second stage-2 condition would refuse before either database condition
    was reached -- a refusal, but not the one under test.

    Returns:
        The refusal message, for the caller to assert its distinguishing
        substring on.

    Raises:
        Failed: Through `pytest.raises`, when stage 2 accepted the state.

    """
    with temporary_root_urlconf(*deployed_url_patterns()), pytest.raises(ImproperlyConfigured) as refused:
        run_stage_two()
    return str(refused.value)


def _accepted() -> None:
    """Run stage 2 over the same configuration and require it to pass."""
    with temporary_root_urlconf(*deployed_url_patterns()):
        run_stage_two()


@pytest.mark.forbidden_state("unapplied-migrations")
def test_unapplied_migrations_on_a_second_alias_refuse(django_db_blocker: DjangoDbBlocker) -> None:
    """AC #4: a serving process never starts against an unrecognized schema.

    The fault is on `reporting` while `default` is fully migrated, so an
    implementation that inspected only the default alias would find nothing and
    let the process serve.

    `django_db_blocker` rather than the `django_db` marker, and the difference is
    not stylistic. The marker wraps the case in a `TestCase`, which forbids every
    alias it was not told about at class setup -- and `reporting` cannot be
    declared there, because it does not exist until this body configures it. The
    blocker lifts pytest-django's global connection guard and nothing else, which
    is exactly what a condition that opens its own connections needs. Nothing is
    written: the condition reads migration state and the second database is in
    memory.
    """
    with django_db_blocker.unblock(), never_migrated_database_alias(SECOND_ALIAS):
        message = _refusal()

    assert f"DATABASES[{SECOND_ALIAS!r}]" in message
    assert A_PENDING_MIGRATION in message


@pytest.mark.django_db
def test_a_process_that_is_not_a_serving_process_is_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC #4's second half: `manage.py migrate` is not forbidden by the condition it clears.

    The same state as the case above -- migrations genuinely pending on a
    configured alias -- with `COMPONENT_PROCESS` absent. AD-13 makes absence mean
    *not a serving process*, and this is the exemption that keeps the FR-41
    release stage from deadlocking against a refusal only `migrate` could
    resolve. R-3 is the recorded price: a serving process started outside the
    Epic 5 tasks does not fire this refusal either.
    """
    monkeypatch.delenv(PROCESS_ENV_VAR, raising=False)

    with never_migrated_database_alias(SECOND_ALIAS):
        _accepted()


def test_both_stages_iterate_every_configured_database(django_db_blocker: DjangoDbBlocker) -> None:
    """AC #6: neither stage reads `DATABASES["default"]` alone.

    One test rather than two, because the claim is about the pair. Stage 1's
    sqlite condition and stage 2's migrations condition are handed the same
    shape of fault -- two aliases configured, the second one wrong -- and both
    have to find it. Stage 1 reads a settings namespace still being composed,
    stage 2 reads live connections, so the two cannot share an implementation
    and could drift apart without this.
    """
    namespace = valid_deployed_settings_namespace()
    namespace.DATABASES = {
        **namespace.DATABASES,
        SECOND_ALIAS: {"ENGINE": NEVER_MIGRATED_ENGINE, "NAME": "/srv/reporting.sqlite3"},
    }

    with pytest.raises(ImproperlyConfigured) as stage_one_refusal:
        run_stage_one(namespace)

    assert f"DATABASES[{SECOND_ALIAS!r}]" in str(stage_one_refusal.value)

    with django_db_blocker.unblock(), never_migrated_database_alias(SECOND_ALIAS):
        stage_two_message = _refusal()

    assert f"DATABASES[{SECOND_ALIAS!r}]" in stage_two_message


@pytest.mark.django_db
@pytest.mark.forbidden_state("designated-group-absent")
def test_the_designated_staff_group_absent_refuses() -> None:
    """AC #5, first half: the misconfiguration surfaces as a configuration error.

    Deleted inside `django_db`'s transaction, so the row is restored by the
    rollback and the rest of the session sees the database it expected.
    """
    staff_group = settings.CLAIMS_CONTRACT.staff_group
    Group.objects.filter(name=staff_group).delete()

    message = _refusal()

    assert repr(staff_group) in message
    assert repr(settings.CLAIMS_CONTRACT.superuser_group) not in message
    assert "AD-27" in message


@pytest.mark.django_db
@pytest.mark.forbidden_state("designated-group-absent")
def test_the_designated_superuser_group_absent_refuses() -> None:
    """AC #5, second half, asserted separately because it is a separate forbidden state.

    FR-16 requires each state to be testable on its own, and the two are fixed in
    different places: one is the group that confers `is_staff`, the other the
    group that confers `is_superuser`.
    """
    superuser_group = settings.CLAIMS_CONTRACT.superuser_group
    Group.objects.filter(name=superuser_group).delete()

    message = _refusal()

    assert repr(superuser_group) in message
    assert repr(settings.CLAIMS_CONTRACT.staff_group) not in message


@pytest.mark.django_db
def test_both_designated_groups_present_is_accepted() -> None:
    """The pass case, without which a condition that refused unconditionally would pass every case above.

    The rows are the ones `users.0003_provision_designated_groups` created from
    the claims contract when the test database was built -- the same mechanism a
    deployed component's release stage runs, rather than rows this test seeded
    for itself.
    """
    designated = {settings.CLAIMS_CONTRACT.staff_group, settings.CLAIMS_CONTRACT.superuser_group}

    assert set(Group.objects.filter(name__in=designated).values_list("name", flat=True)) == designated

    _accepted()


@pytest.mark.django_db
def test_the_refusal_creates_no_group() -> None:
    """AD-27's mechanism is a data migration, and a refusal never repairs.

    A condition that created the missing group would report a healthy component
    and hide the state it exists to report -- and would put a second group-
    creating mechanism beside `django_service.users.provisioning`, which is the
    duplication AD-27 forbids outright.
    """
    staff_group = settings.CLAIMS_CONTRACT.staff_group
    Group.objects.filter(name=staff_group).delete()

    _refusal()

    assert not Group.objects.filter(name=staff_group).exists()
