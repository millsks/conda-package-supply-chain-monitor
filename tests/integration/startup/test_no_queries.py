"""Both stages issue zero queries against a real connection (AC #7, NFR-1).

The counterpart to `tests/unit/startup/test_no_network_no_queries.py`, which
asserts the same claim through `connection.execute_wrapper` -- a recorder that
installs without opening a connection, and therefore holds in a unit test that
touches no database at all. This module makes the assertion the way NFR-1's
budget is actually measured: `django.test.utils.CaptureQueriesContext` against a
live connection, counting what the backend logged.

Both are kept. The unit form proves nothing reached the cursor and runs in
milliseconds with no database; this form proves the count is zero on a
connection that was genuinely opened, which is the form Story 4.3 will have to
amend when its migration-state read lands. `CaptureQueriesContext` cannot run as
a unit test -- its `__enter__` calls `ensure_connection()`, which pytest-django
blocks outside `django_db` -- so the split is where the database boundary is,
not a duplication of convenience.

**Zero, and still zero after Story 4.3.** Both of that story's database
conditions gate on `config.locality.is_serving_process()`, and no test process
declares `COMPONENT_PROCESS` -- AD-13's fail-open process type means an absent
declaration is *not* a serving process. So neither condition reaches a cursor
here, and zero remains the honest number for a run that is not serving traffic.
The two are driven with the variable set in
`tests/integration/startup/test_stage_two_database_conditions.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_one
from config.startup import run_stage_two
from tests.conftest import deployed_url_patterns
from tests.conftest import temporary_root_urlconf
from tests.conftest import valid_deployed_settings_namespace

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType


@pytest.fixture
def deployed_settings_namespace(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """A valid deployed configuration: deployed locality, deployed settings module.

    Deployed rather than local, because every condition is deployed-only and the
    local path would return before reaching any of them -- leaving the count
    below a statement about code that never ran.

    **Valid means fully valid, not merely bare.** A bare `ModuleType` satisfied
    every condition stage 1 held when this module was written; against the six it
    holds now it refuses on the first one, before any query could have been
    issued, and the count below would be zero for the wrong reason. The builder
    is `tests/conftest.py`'s so that this module and its unit counterpart cannot
    disagree about what a valid deployed namespace is, and `OTEL_SDK_DISABLED` is
    deleted because condition 3 reads the environment rather than the namespace.

    Returns:
        A namespace no stage-1 condition objects to.

    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)
    return valid_deployed_settings_namespace()


@pytest.fixture
def deployed_urlconf() -> Iterator[str]:
    """A root URL configuration a deployed component would actually serve.

    The same amendment its unit counterpart carries, for the same reason: Story
    4.3's URLconf conditions make the configuration in force part of what a valid
    deployed state is, and this process holds one built under
    `COMPONENT_RUNTIME=local`, which mounts the local persona sign-in route that
    stage 2 exists to refuse. The conditions still walk a real resolver; they
    walk one whose locality matches the locality the test declares.

    Yields:
        The dotted name of the installed configuration.

    """
    with temporary_root_urlconf(*deployed_url_patterns()) as urlconf:
        yield urlconf


@pytest.mark.django_db
def test_neither_stage_issues_a_query(
    deployed_settings_namespace: ModuleType,
    deployed_urlconf: str,
) -> None:
    """AC #7: no query beyond migration state, and neither read fires off a serving process."""
    with CaptureQueriesContext(connection) as captured:
        run_stage_one(deployed_settings_namespace)
        run_stage_two()

    assert list(captured.captured_queries) == []
