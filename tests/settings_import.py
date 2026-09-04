"""How the suite imports a settings module fresh, in one place.

Two modules import the settings modules again, at run time, to assert what they
*compose* from the environment rather than what Django materialised at start-up.
`tests/unit/test_settings.py` asserts the values themselves; Story 5.6's
`tests/unit/test_payload_properties.py` asserts the payload properties that fall
out of them -- no file-based log handler, a session store that writes nothing to
local disk. Both need the same three things first, and each of the three is a
way a fresh import goes quietly wrong.

*The module has to actually be re-imported.* `config.settings.base` is evicted
alongside every target, because the `from .base import *` in each leaf would
otherwise reuse an already-imported copy and the environment the caller just set
would never be read.

*The environment has to be the caller's and nobody else's.* A developer with
`DJANGO_DEBUG=True` exported gets a different `DEBUG`, a different composed
`LOGGING` renderer and a different answer from an assertion that never mentioned
either. `import_settings` clears the whole configured-prefix surface -- `DJANGO_*`,
`COMPONENT_*` and `CPM_*` -- before it sets what the caller asked for, so the
import reads a stated environment rather than an inherited one.

*structlog has to be put back.* `src/config/settings/base.py` calls
`configure_structlog()` at module scope, so **importing a settings module
reconfigures structlog for the whole process**. A module that re-imports four of
them across a dozen cases and restores nothing leaves the last configuration
standing, which blinds `structlog.testing.capture_logs()` in any module that
sorts after it -- silently, with no failure in the module that caused it. The
eviction fixture below saves the configuration and restores it in a `finally`.

`DJANGO_SETTINGS_MODULE` is deliberately not cleared. pytest-django sets it for
the session, `config/settings/production.py` runs stage 1 of the refusal contract
on import and the roster names it, and clearing it would make a fresh import fail
for a reason that has nothing to do with what any caller is asserting.

This is a helper module, not a collected one -- see `tests/pixi_manifest.py` and
`tests/dockerfile.py`, which sit here for the same reason.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import TYPE_CHECKING
from typing import Final

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Mapping
    from types import ModuleType

    import pytest

#: The four settings modules, and all four rather than the three that are ever
#: imported directly: `local.py` declares no `LOGGING` of its own and inherits
#: `base.py`'s through `from .base import *`, so a fresh import of it has to
#: evict `base` too or it composes nothing at all.
BASE_SETTINGS: Final[str] = "config.settings.base"
LOCAL_SETTINGS: Final[str] = "config.settings.local"
PRODUCTION_SETTINGS: Final[str] = "config.settings.production"
TEST_SETTINGS: Final[str] = "config.settings.test"
SETTINGS_MODULES: Final[tuple[str, ...]] = (BASE_SETTINGS, LOCAL_SETTINGS, PRODUCTION_SETTINGS, TEST_SETTINGS)

#: The prefixes a fresh import is allowed to read, and therefore the ones a
#: caller has to state rather than inherit. `CPM_` is the product's own -- the
#: three role-group names `config/settings/base.py` reads through
#: `conda_package_supply_chain_monitor.core.roles`. A prefix missing from this
#: tuple is a prefix a developer's shell still reaches, which is how an assertion
#: about a fresh import passes on a value the caller never stated.
CONFIGURATION_PREFIXES: Final[tuple[str, ...]] = ("DJANGO_", "COMPONENT_", "CPM_")

#: The one variable in those namespaces that is the *session's* rather than the
#: caller's -- see the module docstring.
PRESERVED_VARIABLES: Final[frozenset[str]] = frozenset({"DJANGO_SETTINGS_MODULE"})


def evicted_settings_modules() -> Iterator[None]:
    """Drop freshly imported settings modules around one case, and restore structlog.

    The generator body of an autouse fixture rather than a fixture itself, so
    that both call sites declare their own `@pytest.fixture` and neither has to
    import a fixture across modules.

    Django's active settings are unaffected by the eviction: they were
    materialised at start-up and hold no reference to these fresh module
    objects. structlog's configuration is *not* unaffected, which is the half
    that used to leak -- `configure_structlog()` runs at `base.py`'s module
    scope, so every fresh import reconfigures the process-wide pipeline.

    Yields:
        Control to the test, with the four settings modules evicted.
    """
    configuration = structlog.get_config()
    for name in SETTINGS_MODULES:
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name in SETTINGS_MODULES:
            sys.modules.pop(name, None)
        structlog.configure(**configuration)


def import_settings(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: Mapping[str, str],
    runtime_variable: str,
    runtime: str | None,
) -> ModuleType:
    """Import one settings module fresh, under a stated environment and nothing else.

    Fresh, through `importlib`, rather than through `override_settings`: what is
    under test is what the module *composes* at import time from the environment
    alone (FR-38), and an override asserts the opposite -- that a value can be
    replaced from outside.

    Every variable in `CONFIGURATION_PREFIXES` is cleared first, so a developer
    who has one exported gets the same answer the gate does. `environment` is
    then applied, and the runtime is either declared or deleted: absent is how a
    deployment spells itself and locality fails closed (AD-13), so a module that
    is only ever loaded deployed is imported with the variable *gone* rather
    than set to anything.

    Args:
        name: The settings module to import.
        monkeypatch: The environment is set through it, so it is restored.
        environment: The variables this import is to read.
        runtime_variable: The locality variable's name (`config.locality`).
        runtime: The locality to declare, or `None` to delete the variable.

    Returns:
        The freshly imported module.
    """
    for variable in list(os.environ):
        if variable.startswith(CONFIGURATION_PREFIXES) and variable not in PRESERVED_VARIABLES:
            monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    for variable, value in environment.items():
        monkeypatch.setenv(variable, value)
    if runtime is None:
        monkeypatch.delenv(runtime_variable, raising=False)
    else:
        monkeypatch.setenv(runtime_variable, runtime)
    return importlib.import_module(name)
