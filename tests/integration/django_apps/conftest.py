"""Fixtures the domain-application integration cases share.

One fixture today, and it is the one two modules need: the tables behind
`tests/passes.py`'s fixture derived models. `tests/integration/django_apps/test_policy_run.py`
runs the passes that write them and `tests/integration/django_apps/test_rollup.py`
asserts that composing the rollup leaves them alone, and a per-module copy of the
schema fixture is exactly the duplication `tests/collectors.py` and
`tests/model_registry.py` were extracted to prevent -- two fixtures that can
disagree look like two passing tests.

It sits in a conftest rather than in `tests/passes.py` because it is a *pytest*
fixture: it depends on `django_db_setup` and `django_db_blocker`, which only the
plugin can supply, and a helper module that imported them would be a plugin
wearing a library's name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection

from tests.passes import fixture_derived_models

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.db import models
    from pytest_django import DjangoDbBlocker


@pytest.fixture(scope="session")
def derived_tables(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[tuple[type[models.Model], type[models.Model]]]:
    """The two fixture derived tables, built once and dropped at the end of the session.

    **Session-scoped, and the DDL runs outside every test's transaction.** That is
    forced rather than chosen, for the reason
    `tests/integration/django_apps/test_append_only_evidence.py`'s `evidence_table`
    gives at length: SQLite cannot toggle foreign-key enforcement inside a
    multi-statement transaction, so its schema editor refuses to open within one,
    and this repository runs the suite on SQLite locally and on PostgreSQL in the
    gate. Creating the tables per test would therefore work in the gate and fail
    on every developer machine. The *rows* still roll back per test:
    `@pytest.mark.django_db` wraps each case, and only the empty tables outlive
    it.

    **Stale tables are dropped rather than collided with.** `--reuse-db` is in
    `addopts`, so a run killed between the create and the drop would otherwise
    leave tables that make every later run fail in this fixture. Both names are
    prefixed `cpm_fixture_`, which is what makes the drop safe: it can never land
    on a table a migration built.

    **The teardown checks each table is there before dropping it**, so a
    `create_model` that failed is not followed by a `delete_model` that raises on
    the way out -- which would show the reader the teardown's error rather than
    the one that actually broke the run.

    Args:
        django_db_setup: pytest-django's session-scoped database setup, so the
            test database exists before any DDL runs.
        django_db_blocker: The guard that keeps database access out of tests
            which did not ask for it; unblocked around the DDL.

    Yields:
        The first and second fixture derived models, in declared order.

    """
    models_pair = fixture_derived_models()
    with django_db_blocker.unblock():
        existing = connection.introspection.table_names()
        for model in models_pair:
            table = model._meta.db_table  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
            if table in existing:
                with connection.schema_editor() as editor:
                    editor.delete_model(model)
        for model in models_pair:
            with connection.schema_editor() as editor:
                editor.create_model(model)
    try:
        yield models_pair
    finally:
        with django_db_blocker.unblock():
            present = connection.introspection.table_names()
            for model in models_pair:
                if model._meta.db_table in present:  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
                    with connection.schema_editor() as editor:
                        editor.delete_model(model)
