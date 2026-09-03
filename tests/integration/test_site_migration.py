"""AC #5: the `Site` data migration is retired, and the domain comes from the environment.

AD-31: "The `Site` domain is likewise environment-driven; the existing data
migration at `src/django_service/contrib/sites/migrations/0003_set_site_domain_and_name.py`
is **retired rather than parameterized**." What that prevents, in the spine's own
words, is "every deployed component redirecting to whatever callback domain a
data migration baked in".

These run against a migrated database, so they are integration tests: the point
of the first one is what the schema *contains* after the whole migration history
has been applied, which no amount of reading the module can establish.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import structlog
from django.conf import settings
from django.contrib.sites.models import Site
from django.db import migrations

if TYPE_CHECKING:
    from types import ModuleType

MIGRATION_MODULE = "django_service.contrib.sites.migrations.0003_set_site_domain_and_name"
SUCCESSOR_MODULE = "django_service.contrib.sites.migrations.0004_alter_options_ordering_domain"
BASE_SETTINGS = "config.settings.base"

# The values the retired migration used to write. Restated here rather than
# imported, because the whole point is that they no longer appear in the module.
RETIRED_DOMAIN = "millsks.github.io"
RETIRED_NAME = "Django 15-Factor Application Accelerator"


def _migration(name: str) -> ModuleType:
    return importlib.import_module(name)


@pytest.mark.django_db
def test_no_site_row_carries_the_retired_domain():
    """The migration history, applied in full, writes no repository-specific domain."""
    domains = set(Site.objects.values_list("domain", flat=True))
    names = set(Site.objects.values_list("name", flat=True))

    assert RETIRED_DOMAIN not in domains, (
        f"A Site row still carries {RETIRED_DOMAIN!r}. If this database predates the retirement, "
        "re-run with --create-db; if it does not, the migration is writing again."
    )
    assert RETIRED_NAME not in names


@pytest.mark.django_db
def test_the_retired_migration_writes_nothing_when_it_runs():
    """Its operations are no-ops in both directions, so the node applies and reverses cleanly."""
    module = _migration(MIGRATION_MODULE)

    operations = module.Migration.operations

    assert len(operations) == 1
    operation = operations[0]
    assert isinstance(operation, migrations.RunPython)
    assert operation.code is migrations.RunPython.noop
    assert operation.reverse_code is migrations.RunPython.noop


def test_the_retired_node_still_exists_and_keeps_its_place_in_the_history():
    """Retired, not deleted: `0004` depends on this node and applied databases record it."""
    module = _migration(MIGRATION_MODULE)
    successor = _migration(SUCCESSOR_MODULE)

    assert module.Migration.dependencies == [("sites", "0002_alter_domain_unique")]
    assert ("sites", "0003_set_site_domain_and_name") in successor.Migration.dependencies


def test_the_retired_migration_names_neither_the_domain_nor_a_parameter():
    """Retired rather than parameterized -- AD-25 owns parameterization and it is Epic 7's."""
    source = Path(_migration(MIGRATION_MODULE).__file__).read_text(encoding="utf-8")

    assert RETIRED_DOMAIN not in source
    assert RETIRED_NAME not in source
    assert "update_or_create" not in source
    assert "django_site_id_seq" not in source


def test_the_site_domain_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    """The replacement for what the migration used to do: settings, from `COMPONENT_SITE_*`.

    Imported fresh so the module-level environment reads are re-evaluated, the
    way `tests/unit/test_settings.py` does it. Django's active settings are
    untouched -- they were materialised at startup and hold no reference to this
    module object.

    The structlog configuration is saved and restored around the import because
    `config.settings.base` calls `configure_structlog()` at module scope. That
    call is global and outlives this test, and it configures
    `cache_logger_on_first_use=True` -- so without the restore, any module-level
    logger bound afterwards freezes its processor chain and
    `structlog.testing.capture_logs()` in a later test captures nothing. It is
    three of Story 2.5's refusal-reporting assertions that go silently blind,
    and only when this file and `tests/integration/authorization/test_adapters.py`
    both run, which is why the suite has to be run whole to see it.
    """
    monkeypatch.setenv("COMPONENT_SITE_DOMAIN", "component.example.test")
    monkeypatch.setenv("COMPONENT_SITE_NAME", "Component")
    sys.modules.pop(BASE_SETTINGS, None)
    structlog_config = structlog.get_config()
    try:
        base = importlib.import_module(BASE_SETTINGS)
        assert base.SITE_DOMAIN == "component.example.test"
        assert base.SITE_NAME == "Component"
    finally:
        sys.modules.pop(BASE_SETTINGS, None)
        structlog.configure(**structlog_config)

    # The active configuration exposes the same two names, so a caller reading
    # `settings.SITE_DOMAIN` is reading the environment-driven value rather than
    # something only the fresh import has.
    assert hasattr(settings, "SITE_DOMAIN")
    assert hasattr(settings, "SITE_NAME")


@pytest.mark.django_db
def test_nothing_writes_the_site_row_at_startup():
    """NFR-1 and AD-22: no boot-time query beyond migration state, and no boot-time write.

    The row Django's own `create_default_site` handler leaves behind is the only
    one there is, and it still carries Django's placeholder -- neither the
    retired literal nor the configured domain. That is what "the settings are the
    source of truth, the table merely exists" looks like from the database, and
    it is why nothing here or in an `AppConfig.ready()` may write the row.
    """
    site = Site.objects.get(pk=settings.SITE_ID)

    assert site.domain == "example.com"
    assert site.domain != RETIRED_DOMAIN
