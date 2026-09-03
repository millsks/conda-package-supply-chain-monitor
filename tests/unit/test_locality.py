"""Tests for `config.locality`, the single reader of the `COMPONENT_*` contract.

Two defaults, deliberately opposite (AD-13). **Locality fails closed**: absent or
unrecognized means deployed, so local development is the exception that declares
itself and a declaration lost on the way to production leaves the refusals armed.
**Process type fails open**: absent means not a serving process, because failing
it closed would make `pixi run migrate` -- a release-stage step -- declare itself
a serving process and deadlock the release on the migrations refusal.

Both defaults are asserted here rather than left to the module's docstring,
because each is a *silence*: nothing raises when either is inverted, and the
first observable symptom is a refusal that did not fire or a release that did not
finish.

The environment is read at call time, so `monkeypatch.setenv` is enough and no
module reloading is involved. That matters for the suite itself: these tests run
in the `dev` pixi environment, whose activation env declares
`COMPONENT_RUNTIME=local`, so the *absent* cases are reached by deleting the
variable rather than by assuming it is unset.

Unit tests: no database, no network, no filesystem.
"""

from __future__ import annotations

import pytest

from config.locality import LOCAL
from config.locality import PROCESS_ENV_VAR
from config.locality import RUNTIME_ENV_VAR
from config.locality import SERVING_PROCESSES
from config.locality import component_process
from config.locality import is_deployed
from config.locality import is_local
from config.locality import is_serving_process


@pytest.fixture(autouse=True)
def _undeclared(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an environment that declares neither variable.

    The `dev` environment sets `COMPONENT_RUNTIME=local`, which is the whole
    point of the manifest declaration -- so without this the "absent" cases
    would be testing the runner's environment rather than the reader's default.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(PROCESS_ENV_VAR, raising=False)


def test_the_contract_names_are_spelled_once() -> None:
    """The constants are the declaration site the rest of the tree reads (AD-1)."""
    assert RUNTIME_ENV_VAR == "COMPONENT_RUNTIME"
    assert PROCESS_ENV_VAR == "COMPONENT_PROCESS"
    assert LOCAL == "local"
    assert frozenset({"web", "worker", "beat"}) == SERVING_PROCESSES


def test_an_undeclared_runtime_is_deployed() -> None:
    """Deployment is the default and requires no declaration (AC #4)."""
    assert is_local() is False
    assert is_deployed() is True


@pytest.mark.parametrize("declared", ["", "   ", "production", "dev", "1", "true", "Local-ish", "locale"])
def test_an_unrecognized_runtime_is_deployed(monkeypatch: pytest.MonkeyPatch, declared: str) -> None:
    """Locality fails closed: only the recognized value is local (AC #4).

    `dev` is the case worth naming. A platform is likely to set a generic
    development marker for a development *deployment*, and a deployed dev
    environment is still deployed.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, declared)
    assert is_local() is False
    assert is_deployed() is True


@pytest.mark.parametrize("declared", ["local", "LOCAL", "Local", " local ", "\tlocal\n"])
def test_the_declared_runtime_is_local(monkeypatch: pytest.MonkeyPatch, declared: str) -> None:
    """The dev environment's declaration is read as local, whatever its casing (AC #1).

    The reader is deliberately more forgiving than the manifest assertion in
    `test_locality_declaration.py`, which pins the declared value to exactly
    `local`. A `Local` written into `pixi.toml` still reads as local here -- it
    is not a silent inversion -- but the manifest is held to one spelling so the
    declaration stays canonical.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, declared)
    assert is_local() is True
    assert is_deployed() is False


def test_locality_is_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """The answer follows the environment, so a later declaration is observed.

    Reading at import time would freeze whichever value happened to be set when
    the first importer touched the module -- and in a Django process that is
    `manage.py`, long before anything asks the question.
    """
    assert is_local() is False
    monkeypatch.setenv(RUNTIME_ENV_VAR, LOCAL)
    assert is_local() is True
    monkeypatch.delenv(RUNTIME_ENV_VAR)
    assert is_local() is False


def test_an_undeclared_process_is_not_serving() -> None:
    """Process type fails open: absent means not a serving process (AC #4).

    This is the asymmetry, and it is not tidiness waiting to happen. Failing it
    closed would make every management command -- `pixi run migrate` included --
    declare itself a serving process and refuse on the unapplied-migrations
    condition, deadlocking the release stage.
    """
    assert component_process() is None
    assert is_serving_process() is False


@pytest.mark.parametrize("process", sorted(SERVING_PROCESSES))
def test_a_declared_serving_process_is_recognized(monkeypatch: pytest.MonkeyPatch, process: str) -> None:
    """Each member of the closed set is reported back by name."""
    monkeypatch.setenv(PROCESS_ENV_VAR, process)
    assert component_process() == process
    assert is_serving_process() is True


@pytest.mark.parametrize(
    ("declared", "expected"),
    [(" web ", "web"), ("WORKER", "worker"), ("\tBeat\n", "beat")],
)
def test_a_declared_process_is_normalized_before_it_is_matched(
    monkeypatch: pytest.MonkeyPatch,
    declared: str,
    expected: str,
) -> None:
    """Padding and casing are stripped, and the normalized name is what comes back.

    Pinned rather than left implicit: every other positive case in this module
    is already lowercase and unpadded, so deleting the normalization from
    `component_process()` would leave the suite green while making ` web ` read
    as "not a serving process" -- a serving process that silently stops being
    one, which is exactly the class of silence this file exists to close.
    """
    monkeypatch.setenv(PROCESS_ENV_VAR, declared)
    assert component_process() == expected
    assert is_serving_process() is True


@pytest.mark.parametrize("declared", ["shell", "", "   ", "migrate", "webb"])
def test_an_unrecognized_process_is_not_serving(monkeypatch: pytest.MonkeyPatch, declared: str) -> None:
    """A value outside the closed set reads exactly as an absent one does."""
    monkeypatch.setenv(PROCESS_ENV_VAR, declared)
    assert component_process() is None
    assert is_serving_process() is False


def test_the_process_type_is_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Process type follows the environment too, for the same reason locality does."""
    assert component_process() is None
    monkeypatch.setenv(PROCESS_ENV_VAR, "worker")
    assert component_process() == "worker"
    monkeypatch.delenv(PROCESS_ENV_VAR)
    assert component_process() is None


def test_the_two_declarations_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declaring a serving process says nothing about locality, and vice versa.

    Epic 5's `web` task declares a process and no runtime, and inherits
    *deployed* from that silence -- it runs in the `default` environment, which
    declares no locality at all. A reader that coupled the two would make it
    local.
    """
    monkeypatch.setenv(PROCESS_ENV_VAR, "web")
    assert is_local() is False
    assert is_deployed() is True

    monkeypatch.setenv(RUNTIME_ENV_VAR, LOCAL)
    assert is_local() is True
    assert component_process() == "web"
