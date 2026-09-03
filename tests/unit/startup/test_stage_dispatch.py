"""Both stages dispatch their condition roster, and only when deployed.

This story delivers the frame and one condition. The frame's own behaviour --
the roster is iterated, and it is iterated *after* the locality check, not
before -- is what Stories 4.2, 4.3, 4.4 and 4.6 all rely on, and with an empty
stage-2 roster nothing else in the suite would execute the dispatch at all.

The rosters are replaced by name (`monkeypatch.setattr(module, "_STAGE_TWO", ...)`)
rather than by attribute access, so no cross-module private read is written and
ruff `SLF001` has nothing to flag. Replacing them is legitimate here for the
same reason it would not be in a condition test: what is under test is the
dispatch, and the roster is its input.

The boot sentinel is asserted here only in its in-process form -- that it is
readable and true. That it *fires from the invocation point* cannot be asserted
in this process at all: pytest-django completes `django.setup()`, and therefore
`UsersConfig.ready()`, during collection, so the record is already written
before any test body runs and would stay written if the call were deleted.
`tests/integration/startup/test_stage_two_fires.py` is where that claim is made,
in a subprocess.
"""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

from config.locality import LOCAL
from config.locality import RUNTIME_ENV_VAR
from config.startup import run_stage_one
from config.startup import run_stage_two
from config.startup import stage_one
from config.startup import stage_two
from config.startup.stage_two import stage_two_has_run

if TYPE_CHECKING:
    import pytest

# A namespace no condition in this story objects to, so a refusal in these cases
# is the recorded condition firing rather than FR-12's escape route.
NEUTRAL_SETTINGS_MODULE = "config.settings.production"


def test_stage_two_runs_every_condition_in_its_roster_when_deployed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The roster is dispatched in order, and each entry is called once."""
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    evaluated: list[str] = []
    monkeypatch.setattr(
        stage_two,
        "_STAGE_TWO",
        (lambda: evaluated.append("first"), lambda: evaluated.append("second")),
    )

    run_stage_two()

    assert evaluated == ["first", "second"]


def test_stage_two_runs_no_condition_when_the_component_is_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every condition is deployed-only, and the early return is above the roster."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, LOCAL)
    evaluated: list[str] = []
    monkeypatch.setattr(stage_two, "_STAGE_TWO", (lambda: evaluated.append("condition"),))

    run_stage_two()

    assert evaluated == []


def test_stage_two_records_that_it_was_entered_before_the_locality_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sentinel has to be observable on a local path or it is observable nowhere.

    Every developer and CI path runs local (AD-13), so a record written after
    the `is_deployed()` early return would never be seen and the boot probe that
    reads it would assert nothing.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, LOCAL)
    monkeypatch.setattr(stage_two, "_STAGE_TWO_RAN", {"entered": False})

    assert stage_two_has_run() is False

    run_stage_two()

    assert stage_two_has_run() is True


def test_stage_one_passes_the_settings_module_to_every_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The calling convention Stories 4.2 and 4.4 build on: the namespace is the argument.

    Conditions read candidate names off this object with `getattr`, because
    `django.conf.settings` is not yet populated while a settings module is still
    executing.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    inspected: list[ModuleType] = []
    monkeypatch.setattr(stage_one, "_STAGE_ONE", (inspected.append,))
    namespace = ModuleType(NEUTRAL_SETTINGS_MODULE)

    run_stage_one(namespace)

    assert inspected == [namespace]


def test_stage_one_runs_no_condition_when_the_component_is_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The early return is above the roster here too."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, LOCAL)
    inspected: list[ModuleType] = []
    monkeypatch.setattr(stage_one, "_STAGE_ONE", (inspected.append,))

    run_stage_one(ModuleType(NEUTRAL_SETTINGS_MODULE))

    assert inspected == []
