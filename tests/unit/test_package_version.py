"""Tests for both branches of the package version lookup.

`src/django_service/__init__.py` reads its version from installed distribution
metadata and falls back to `0.0.0` when there is none -- a bare checkout, or a
source tree imported without being installed.

That fallback used to carry `# pragma: no cover`. AD-20 forbids clearing the
coverage floor "by a pragma on unreached code", and a pragma on a branch that a
five-line test can reach is precisely that: the line leaves the denominator, the
percentage rises, and nothing is covered. The pragma is gone and this is what
replaces it -- the branch is covered because it is exercised.

A unit test: it patches an import-time lookup and reloads one module. No
network, no database, no filesystem beyond the import system's own reads.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from typing import TYPE_CHECKING

import pytest

import django_service

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

DISTRIBUTION = "conda-package-supply-chain-monitor"

# What the package reports when its distribution metadata cannot be found.
FALLBACK_VERSION = "0.0.0"
FALLBACK_VERSION_INFO = (0, 0, 0)


@pytest.fixture
def package_without_distribution_metadata(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Reload `django_service` with its distribution metadata missing, then restore it.

    The patch is applied to `importlib.metadata.version` rather than to
    `django_service.version`: the reload re-runs the `from importlib.metadata
    import version` line, so the name the module ends up holding is whatever
    `importlib.metadata` has at reload time, and patching the module attribute
    would be undone by the very reload it was meant to affect.

    The teardown undoes the patch *before* reloading, explicitly rather than by
    relying on fixture finalisation order. Reloading while still patched would
    leave `django_service.__version__` at the fallback for every test that runs
    after this one, in a module they have no reason to suspect.

    Yields:
        The reloaded module.

    """

    def _not_installed(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _not_installed)
    try:
        yield importlib.reload(django_service)
    finally:
        monkeypatch.undo()
        importlib.reload(django_service)


def test_the_version_comes_from_the_installed_distribution() -> None:
    """The happy branch: hatch-vcs derives the version and it is read back."""
    assert django_service.__version__ == importlib.metadata.version(DISTRIBUTION)
    assert django_service.__version_info__[0] == int(django_service.__version__.split(".")[0])


def test_a_missing_distribution_falls_back_to_the_zero_version(
    package_without_distribution_metadata: ModuleType,
) -> None:
    """The branch the pragma used to hide: no metadata, so `0.0.0`."""
    reloaded = package_without_distribution_metadata
    assert reloaded.__version__ == FALLBACK_VERSION
    assert reloaded.__version_info__ == FALLBACK_VERSION_INFO


def test_the_real_version_is_restored_for_the_rest_of_the_session() -> None:
    """A sentinel: whenever it runs, the module holds the installed version.

    Nothing orders this after the fixture's user, so it is not a proof that the
    teardown restored anything -- run first, or in isolation, it is a duplicate
    of `test_the_version_comes_from_the_installed_distribution`. What it claims
    is only what holds unconditionally: at this point in the session
    `django_service.__version__` is the installed distribution's version, so a
    module left reloaded under the patch is caught here rather than surfacing
    as an unexplained failure somewhere that has no reason to suspect it.
    """
    assert django_service.__version__ == importlib.metadata.version(DISTRIBUTION)
