"""Field-introspection tests for the user model. No database is touched."""

from __future__ import annotations

from django_service.users.models import User

IDP_SUBJECT_MAX_LENGTH = 255


def test_idp_subject_is_unique_nullable_and_bounded() -> None:
    """The identity key is unique, nullable and capped at 255 characters."""
    field = User._meta.get_field("idp_subject")  # noqa: SLF001

    assert field.unique is True
    assert field.null is True
    assert field.max_length == IDP_SUBJECT_MAX_LENGTH


def test_idp_subject_needs_no_separate_index() -> None:
    """`unique=True` supplies the index, so `db_index` stays off (one index, one declaration)."""
    field = User._meta.get_field("idp_subject")  # noqa: SLF001

    assert field.db_index is False


def test_idp_subject_defaults_to_none() -> None:
    """A user built without an identity key carries no identity key."""
    field = User._meta.get_field("idp_subject")  # noqa: SLF001

    assert field.default is None
    assert field.blank is True


def test_username_remains_the_username_field() -> None:
    """AD-11: `idp_subject` is what identities resolve by; `username` stays USERNAME_FIELD."""
    assert User.USERNAME_FIELD == "username"
    assert "idp_subject" not in User.REQUIRED_FIELDS
