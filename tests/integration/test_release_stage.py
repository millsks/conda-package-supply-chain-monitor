"""The release-stage contract, asserted from the deployment side (AD-22, FR-41).

`tests/unit/test_release_stage.py` asserts the half that is an absence: nothing
in this component migrates. This module asserts the half that makes that absence
survivable -- that a serving process which finds a schema the release stage never
migrated refuses to start, and that the release stage's own step is not caught by
the refusal it exists to clear.

**What this module is not.** The refusal is Epic 4's. It is condition 7 of the
nine-condition table, it lives in `src/config/startup/stage_two.py` with one
owner (AD-26), and FR-16's per-condition test for it is
`tests/integration/startup/test_stage_two_database_conditions.py`. Nothing here
reimplements, moves, duplicates or relaxes it, and nothing here is a replacement
for that test. The question asked here is the deployment repository's question,
which FR-16's is not: *given the process types `component.toml` tells a platform
to start, and the migration steps it tells the platform to run first, what
happens when the platform starts a process without running them?*

That is why every case is derived from `component.toml` rather than from a
literal. The process types are read out of `[[processes]]`, so a combination
where the `celery` region removed `worker` and `beat` asserts over `web` alone
and stays honest rather than failing on a process it does not have.

**R-3, as a test rather than as a paragraph.** The converse case below is the
recorded residual risk in executable form. With `COMPONENT_PROCESS` absent the
identical unmigrated state raises nothing at all -- which is correct and is the
whole reason process type fails *open* (AD-13): `pixi run migrate` is the one
action that clears the condition, so a refusal that fired on it would deadlock
the release stage against a state nothing could resolve. The price is that a
serving process started outside `pixi run web`, `worker` or `beat` does not fire
the refusal either. That price is carried and recorded -- in
`docs/deployment.md` under its own subheading -- not mitigated, and this module
asserts the shape of it rather than pretending it away.

**State.** `COMPONENT_PROCESS` and `COMPONENT_RUNTIME` are process-global and are
manipulated only through `monkeypatch`. The unmigrated database is
`tests.conftest.never_migrated_database_alias`, an in-memory sqlite alias that
ceases to exist when its connection closes and which restores the connection
handler to the mapping it held before -- so the suite leaves the database exactly
as it found it. Nothing here writes a row anywhere.

`tests/integration/conftest.py` marks everything under `tests/integration/` as an
integration test; the marker is not re-applied by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.component import load_component_declaration
from config.locality import PROCESS_ENV_VAR
from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_two
from tests.conftest import deployed_url_patterns
from tests.conftest import never_migrated_database_alias
from tests.conftest import temporary_root_urlconf

if TYPE_CHECKING:
    from pytest_django.plugin import DjangoDbBlocker

# The alias the release stage was never run against. Never `default`: `default`
# is the alias every caller already has, and a fault placed there could be found
# by an implementation that reads `DATABASES["default"]` and stops. The name says
# what the state is -- a database no declared migration step has reached.
UNRELEASED_ALIAS: Final[str] = "unreleased"

# A migration pending on any database that was never migrated at all.
# `contenttypes` is the first thing any Django schema needs, so it is the
# migration a genuinely empty database is missing whatever else it is missing.
A_PENDING_MIGRATION: Final[str] = "contenttypes.0001_initial"

# What the refusal has to tell an operator, beyond which alias is wrong. AD-22's
# rule is the *instruction*: the fix is the release stage, run before the new
# version serves, and specifically not an entrypoint added to make the process
# start. A message that named the alias and stopped would leave adding a
# `depends-on = ["migrate"]` to `web` as the obvious next move -- which is the
# race the whole contract exists to prevent.
RELEASE_STAGE_INSTRUCTION: Final[str] = "release-stage"

# The process types this component declares, read from `component.toml` rather
# than spelled out. In a combination without background task processing this is
# `("web",)` and every case below still holds.
DECLARED_PROCESSES: Final[tuple[str, ...]] = tuple(process.name for process in load_component_declaration().processes)


@pytest.fixture(autouse=True)
def _deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declare the run deployed, and nothing else.

    Locality fails closed, so deleting `COMPONENT_RUNTIME` is what makes this a
    deployed run -- `run_stage_two` returns immediately otherwise. Process type
    is deliberately *not* set here: it is the variable every case below is about,
    and a fixture that set it would decide the question in three of them and hide
    it in the fourth. `OTEL_SDK_DISABLED` is deleted for the same reason the
    stage-1 cases delete it: a developer's exported value is not this suite's
    input.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)
    monkeypatch.delenv(PROCESS_ENV_VAR, raising=False)


def _stage_two() -> None:
    """Run stage 2 over a URL configuration a correctly configured deployed component serves.

    The URL configuration is overridden rather than inherited because the suite
    runs local, so `config/urls.py` mounts the local persona sign-in route and an
    earlier stage-2 condition would refuse before the migrations condition was
    reached -- a refusal, but not the one this module is about.
    """
    with temporary_root_urlconf(*deployed_url_patterns()):
        run_stage_two()


def test_the_declaration_names_a_process_to_assert_over() -> None:
    """The parametrization below is derived, so an empty declaration would collect nothing.

    A `component.toml` with no `[[processes]]` entry would silently reduce this
    module to the two unparametrized cases and report green while the contract
    it exists for went unasserted. Every valid combination declares `web`.
    """
    assert DECLARED_PROCESSES, (
        "component.toml declares no process type, so the refusal contract is asserted over nothing"
    )


@pytest.mark.parametrize("process", DECLARED_PROCESSES)
def test_a_declared_serving_process_refuses_a_schema_the_release_stage_never_migrated(
    monkeypatch: pytest.MonkeyPatch,
    django_db_blocker: DjangoDbBlocker,
    process: str,
) -> None:
    """AC #2: the platform starts a process before running the declared steps, and it refuses.

    Parametrized over every process type `component.toml` tells a deployment
    repository to start, because the contract is about all of them and not about
    `web`: a `worker` that began consuming against an unrecognized schema is the
    same defect arriving through a queue instead of through a request.

    `django_db_blocker` rather than the `django_db` marker: the marker wraps the
    case in a `TestCase`, which forbids every alias it was not told about at
    class setup, and `unreleased` does not exist until the block below configures
    it. The blocker lifts pytest-django's connection guard and rebinds nothing,
    which is what a condition that opens its own connections needs. Nothing is
    written -- the condition reads migration state, and the alias is in memory.
    """
    monkeypatch.setenv(PROCESS_ENV_VAR, process)

    with django_db_blocker.unblock(), never_migrated_database_alias(UNRELEASED_ALIAS):
        with pytest.raises(ImproperlyConfigured) as refused:
            _stage_two()
        message = str(refused.value)

    assert f"DATABASES[{UNRELEASED_ALIAS!r}]" in message
    assert A_PENDING_MIGRATION in message
    assert RELEASE_STAGE_INSTRUCTION in message, (
        f"the refusal names the alias but does not tell the operator that migration is a "
        f"{RELEASE_STAGE_INSTRUCTION} step: {message!r}. AD-22's rule is the instruction, and an operator "
        f"who is not given it adds a migrate to an entrypoint instead."
    )


def test_the_release_stage_step_itself_is_not_a_serving_process_and_is_not_refused(
    django_db_blocker: DjangoDbBlocker,
) -> None:
    """AC #4 and R-3: with no process type declared, the identical state raises nothing.

    This is the exemption the release stage depends on. `pixi run migrate`
    declares no `COMPONENT_PROCESS` -- `tests/unit/test_release_stage.py` asserts
    that it does not -- so it reaches this state as *not a serving process* and
    runs, which is the only way the state can ever be cleared. Failing process
    type closed instead would refuse the one command that fixes the refusal.

    And this is R-3 in the same breath, which is why it is one case and not two:
    the mechanism that exempts `pixi run migrate` cannot distinguish it from a
    gunicorn somebody started by hand outside the declared tasks. That process
    also does not fire the refusal. The price is accepted and recorded; there is
    no mitigation here to assert, and adding one would be the deadlock.
    """
    with django_db_blocker.unblock(), never_migrated_database_alias(UNRELEASED_ALIAS):
        _stage_two()


def test_the_refusal_is_the_only_thing_standing_between_the_two_cases(
    monkeypatch: pytest.MonkeyPatch,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    """The pair above differ in one variable, and this is the case that proves it.

    Without this, the accepting case could be passing because the unmigrated
    alias was never actually configured, or because stage 2 returned early for
    some reason unrelated to process type -- and it would look identical either
    way. Here the same block runs twice over one configuration of the state, once
    with the variable and once without, so the difference is attributable to the
    variable rather than to anything the two set-ups did differently.
    """
    with django_db_blocker.unblock(), never_migrated_database_alias(UNRELEASED_ALIAS):
        _stage_two()

        monkeypatch.setenv(PROCESS_ENV_VAR, DECLARED_PROCESSES[0])
        with pytest.raises(ImproperlyConfigured) as refused:
            _stage_two()

    assert f"DATABASES[{UNRELEASED_ALIAS!r}]" in str(refused.value)
