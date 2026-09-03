"""A deployed component pointed at the local settings module refuses (AC #5, #6).

FR-12's escape route, and the reason the refusal contract lives outside the
settings package at all. A deployed process whose `DJANGO_SETTINGS_MODULE` names
`config.settings.local` gets the development secret key, `DEBUG=True`, the
console email backend and the locally minted signing keypair -- and nothing
inside `local.py` could object, because `local.py` is the thing that would have
to object.

The state is constructed exactly as AC #6 describes rather than simulated:
`COMPONENT_RUNTIME` is deleted, so locality fails closed to *deployed* (AD-13),
and `config.settings.local` is then imported for real. What raises is the
module's own last statement.

Locality is read from the environment and never inferred from which settings
module loaded (AC #5) -- and the condition is the mirror image: the module is
read from the object that is executing and never from
`os.environ["DJANGO_SETTINGS_MODULE"]`, which a process can set to one value and
import another.

Each case imports its settings module fresh. `config.settings.base` is evicted
alongside the target because the `from .base import *` in each leaf would
otherwise reuse the already-imported copy and re-read no environment at all. The
idiom is re-declared here rather than shared through a conftest, following
`tests/unit/test_settings.py` and `tests/unit/test_no_network_at_boot.py`.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.locality import LOCAL
from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_one
from config.startup.stage_one import LOCAL_SETTINGS_MODULE
from config.startup.stage_one import PRODUCTION_SETTINGS_MODULE
from tests.conftest import valid_deployed_settings_namespace

if TYPE_CHECKING:
    from collections.abc import Iterator

BASE = "config.settings.base"
TEST_SETTINGS_MODULE = "config.settings.test"
SETTINGS_MODULES = (BASE, LOCAL_SETTINGS_MODULE, PRODUCTION_SETTINGS_MODULE, TEST_SETTINGS_MODULE)

# A runtime value that is neither `local` nor absent. Locality fails closed, so
# it reads deployed exactly as an unset variable does -- and a condition that
# had been written against "the variable is missing" rather than against
# `is_deployed()` would pass the case above and fail this one.
UNRECOGNIZED_RUNTIME = "staging"


@pytest.fixture(autouse=True)
def _evict_settings_modules() -> Iterator[None]:
    """Drop freshly imported settings modules before and after each case."""
    for name in SETTINGS_MODULES:
        sys.modules.pop(name, None)
    yield
    for name in SETTINGS_MODULES:
        sys.modules.pop(name, None)


@pytest.mark.parametrize(
    "runtime",
    [pytest.param(None, id="unset"), pytest.param(UNRECOGNIZED_RUNTIME, id="unrecognized")],
)
@pytest.mark.forbidden_state("local-settings-module-loaded")
def test_a_deployed_component_importing_the_local_settings_module_refuses(
    monkeypatch: pytest.MonkeyPatch,
    runtime: str | None,
) -> None:
    """AC #6, constructed rather than simulated: the import itself raises.

    Both spellings of *deployed* are exercised, because AC #5's second half is
    that absent **and** unrecognized both mean deployed. A condition written
    against a missing variable rather than against `is_deployed()` would pass
    the first and fail the second.
    """
    if runtime is None:
        monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(RUNTIME_ENV_VAR, runtime)

    with pytest.raises(ImproperlyConfigured) as refused:
        importlib.import_module(LOCAL_SETTINGS_MODULE)

    message = str(refused.value)
    assert LOCAL_SETTINGS_MODULE in message, "the refusal does not name the module that was loaded"
    assert f"{RUNTIME_ENV_VAR}={LOCAL}" in message, "the refusal does not state the local-development resolution"
    assert PRODUCTION_SETTINGS_MODULE in message, "the refusal does not state the deployment resolution"


def test_the_local_settings_module_imports_cleanly_when_locality_is_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the same condition, and the one every developer path takes.

    Without this the escape-route test above would pass just as well against a
    condition that refused unconditionally -- which would make `pixi run manage`
    impossible on a fresh clone.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, LOCAL)

    local_settings = importlib.import_module(LOCAL_SETTINGS_MODULE)

    assert local_settings.DEBUG is True


def test_a_deployed_component_importing_a_deployed_settings_module_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The condition is about which module loaded, not about being deployed.

    Driven through `run_stage_one` against a constructed namespace rather than by
    importing `production.py`, which demands a real `DJANGO_SECRET_KEY` from the
    environment -- an unrelated refusal that would make this case pass for the
    wrong reason.

    The namespace is the fully valid one rather than a bare `ModuleType`. Story
    4.2 added five conditions after this one, and every one of them refuses an
    empty namespace -- so a bare module would raise here and this case would fail
    while saying nothing about the condition it is written for.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)

    run_stage_one(valid_deployed_settings_namespace())


def test_stage_one_returns_before_any_condition_when_the_component_is_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every condition is deployed-only, so the whole stage returns first.

    Asserted against the one namespace that *would* refuse, so it fails if the
    early return is ever moved below the conditions rather than above them.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, LOCAL)

    run_stage_one(ModuleType(LOCAL_SETTINGS_MODULE))
