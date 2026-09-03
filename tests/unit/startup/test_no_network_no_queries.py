"""Neither stage reaches the network or the database (AC #7, NFR-1).

NFR-1: "the nine checks are settings and URL-configuration inspection with no
network call and no query beyond the migration state, so their cost is
irrelevant to startup time." Both stages run at boot -- stage 1 while the
settings module is still executing, stage 2 inside `django.setup()` -- so a
condition that resolved a JWKS document or counted rows would put a network
round trip and a query on the critical path of every process this component
starts, including `pixi run migrate`.

**No wall-clock assertion.** NFR-1's own `[ASSUMPTION]` records that no platform
startup-time budget exists, so there is no threshold to assert against. The cost
is bounded by asserting the two things that could make it unbounded.

**Zero queries, and still zero after Story 4.3.** The migration-state read and
the designated-group existence read both landed with that story, and the number
here did not move -- deliberately, and it is worth stating why rather than
leaving a reader to wonder whether the assertion went stale. Both conditions
gate on `config.locality.is_serving_process()`, which reads `COMPONENT_PROCESS`,
and no test process sets it (AD-13: absent means *not* a serving process, and
the whole suite is not one). So the two database conditions return before they
query, and zero is what a management command and a test run genuinely cost.
`tests/integration/startup/test_stage_two_database_conditions.py` is where those
two are driven with the variable set. Widening this number is therefore a claim
that something queries on a path that is not a serving process, which nothing
should.

**Two URL configurations, because one of them is a stand-in.** Story 4.3's
stage-2 conditions resolve the URLconf at boot, which makes the configuration in
force part of what these assertions cover -- and this process built the *local*
one, which mounts the persona sign-in route stage 2 exists to refuse. Most cases
here therefore run against `deployed_url_patterns()`, a two-route stand-in. One
case runs against `config/urls.py` itself, executed under a popped
`COMPONENT_RUNTIME` so it takes its deployed branch: pointing a gate away from
the tree it is guarding is how a gate stops guarding anything, and the shipped
tree is where a DRF router, a schema generator or an identity provider's
metadata fetch would actually live.

The query half is asserted with `connection.execute_wrapper`, which installs a
recorder without opening a connection -- so this stays a unit test, touching no
database at all, and the assertion is the stronger one: not merely that no query
was counted, but that nothing even reached the cursor.
`tests/integration/startup/test_no_queries.py` makes the same claim through
`django.test.utils.CaptureQueriesContext` against a real connection.

The network half reuses the delivered `no_network` fixture rather than patching
`socket.socket` by hand: that guard already covers `connect`, `connect_ex`,
`create_connection`, `getaddrinfo` and `gethostbyname`, and raises a
`BaseException` subclass so a stray `except Exception:` inside a condition
cannot swallow the refusal and report a clean run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection

from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_one
from config.startup import run_stage_two
from tests.conftest import deployed_component_urlconf
from tests.conftest import deployed_url_patterns
from tests.conftest import temporary_root_urlconf
from tests.conftest import valid_deployed_settings_namespace

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

#: The cache backend `config/settings/production.py` hardcodes. Named here so
#: that the one third-party import stage 1 performs happens inside the guards
#: below rather than being skipped -- see `deployed_settings_namespace`.
DEPLOYED_CACHE_BACKEND = "django_redis.cache.RedisCache"


@pytest.fixture
def deployed_settings_namespace(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """A valid deployed configuration: deployed locality, deployed settings module.

    Deployed rather than local on purpose -- every condition is deployed-only,
    so the local path would return before reaching any of them and the
    assertions below would hold over code that never ran.

    **Valid means fully valid, not merely bare.** A bare `ModuleType` was enough
    while stage 1 held one condition; it is not enough now. Every one of the six
    would refuse it -- no `DATABASES`, no claims contract, no issuer -- and each
    refusal would be raised *before* the socket or the cursor could be reached,
    so both assertions below would pass over conditions that never ran. The
    namespace is built by `tests/conftest.py`, which
    `tests/integration/startup/test_no_queries.py` shares, and
    `OTEL_SDK_DISABLED` is deleted here because condition 3 reads the
    environment rather than the namespace.

    **Why a cache alias is set here and nowhere else in this file.** Stage 1 has
    exactly one line that runs code this component did not write: condition 8
    resolves a `CACHES` alias's `BACKEND` with `import_string`, which imports a
    third-party module. The shared factory declares no `CACHES` -- deliberately,
    because it is a core fixture and feature-scoped keys do not belong in it -- so
    the condition returns at its first `isinstance` check and that import never
    happens. Both assertions below would then hold over the one line most capable
    of opening a socket. Naming the backend `production.py` actually configures is
    what puts the import inside the `no_network` guard and inside the cursor
    recorder, which is what NFR-1 claims about it.

    What that does *not* prove, recorded rather than left to be assumed: whether
    `django_redis` opens a socket the first time Python executes its module body.
    `tests/unit/startup/test_feature_scoped_refusals.py` sorts before this file
    and resolves the same dotted path, so in a full-suite run the module is
    already in `sys.modules` and the import here resolves from the cache. What is
    covered either way is the resolution stage 1 itself performs -- the import
    call, the `issubclass` test and everything the condition does around them --
    which is the code this contract owns. A dependency that reached the network at
    import time is `tests/unit/test_no_network_at_boot.py`'s subject, and it boots
    a process rather than reusing this one's imports.

    Returns:
        A namespace no stage-1 condition objects to.

    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)
    namespace = valid_deployed_settings_namespace()
    namespace.CACHES = {"default": {"BACKEND": DEPLOYED_CACHE_BACKEND, "LOCATION": "redis://redis:6379/0"}}
    return namespace


@pytest.fixture
def deployed_urlconf() -> Iterator[str]:
    """A root URL configuration a deployed component would actually serve.

    Story 4.3 added two stage-2 conditions that resolve the URLconf, which makes
    the configuration in force part of what "valid" means here -- and the one
    this process holds is not it. The whole suite runs in the `dev` pixi
    environment, which declares `COMPONENT_RUNTIME=local`, so `config/urls.py`
    mounted the local persona sign-in route when it was imported and stage 2
    correctly refuses it the moment a test declares the run deployed. Overriding
    `ROOT_URLCONF` is what makes the deployed locality these tests assert under
    consistent with the configuration they assert over; the conditions still walk
    a real resolver, and the negative case they walk is
    `tests/unit/startup/test_stage_two_urlconf.py`'s subject in its own right.

    Yields:
        The dotted name of the installed configuration.

    """
    with temporary_root_urlconf(*deployed_url_patterns()) as urlconf:
        yield urlconf


def test_neither_stage_opens_a_socket(
    no_network: None,
    deployed_settings_namespace: ModuleType,
    deployed_urlconf: str,
) -> None:
    """AC #7, first half: no network call, with every chokepoint refusing."""
    run_stage_one(deployed_settings_namespace)
    run_stage_two()


def test_the_shipped_url_configuration_opens_no_socket_either(
    no_network: None,
    deployed_settings_namespace: ModuleType,
) -> None:
    """The same claim over `config/urls.py`, not over the two-route stand-in.

    The fixture above overrides `ROOT_URLCONF` for a reason that is sound -- this
    process built the local configuration, which stage 2 refuses -- but it has a
    cost this case pays back. Before Story 4.3 the stage-2 roster was empty and
    no URL configuration was resolved at boot at all; the story *added* a
    boot-time URLconf import and the gate was then pointed at a two-route
    stand-in, so the tree that actually ships -- `config.api_router`'s DRF
    router, drf-spectacular, `django_service.users.urls`, allauth, the admin --
    was never materialized inside the socket-refusing context.

    It is materialized here, and inside the guard rather than before it: the
    module is executed within the `with` block, so the `include()` imports and
    the resolver construction are both covered. A DRF router, a schema generator
    or an allauth provider that reached the network while a URL configuration was
    being built would be found by this and by nothing else.
    """
    with deployed_component_urlconf():
        run_stage_one(deployed_settings_namespace)
        run_stage_two()


def test_neither_stage_reaches_the_database_cursor(
    deployed_settings_namespace: ModuleType,
    deployed_urlconf: str,
) -> None:
    """AC #7, second half: zero queries, and no connection attempted either.

    `execute_wrapper` records at the cursor rather than at the connection, so a
    condition that opened a connection and issued nothing would still pass this
    -- which is why the integration counterpart asserts the count against a real
    connection as well.
    """
    executed: list[str] = []

    # Django fixes this signature, `many` included -- which is why it carries no
    # annotations here: writing `many: bool` would trip ruff `FBT001` on a
    # parameter list this file does not own.
    def _record(execute, sql, params, many, context):
        executed.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(_record):
        run_stage_one(deployed_settings_namespace)
        run_stage_two()

    assert executed == []
