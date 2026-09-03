"""Shape assertions for the users migrations. No database is touched."""

from __future__ import annotations

from importlib import import_module

from django.db import migrations

IDP_SUBJECT_MAX_LENGTH = 255

_add_idp_subject = import_module("django_service.users.migrations.0002_user_idp_subject")


def test_the_identity_key_migration_is_a_single_additive_operation() -> None:
    """AC #3: it applies to an existing database without data loss.

    The guarantee is the operation list, not prose: one `AddField` cannot lose a
    row. A `RunPython` or `RunSQL` added later would run against every existing
    row in production while every test here -- which migrates an empty schema --
    stayed green, so the shape is pinned rather than described.
    """
    operations = _add_idp_subject.Migration.operations

    assert [type(operation).__name__ for operation in operations] == ["AddField"]
    assert _add_idp_subject.Migration.dependencies == [("users", "0001_initial")]


def test_the_migrated_column_is_nullable_so_existing_rows_need_no_backfill() -> None:
    """AC #3: existing rows carry a null identity key until their next authentication."""
    operation = _add_idp_subject.Migration.operations[0]
    assert isinstance(operation, migrations.AddField)
    assert operation.model_name == "user"
    assert operation.name == "idp_subject"

    field = operation.field
    assert field.null is True
    assert field.unique is True
    assert field.max_length == IDP_SUBJECT_MAX_LENGTH
    assert field.get_default() is None
