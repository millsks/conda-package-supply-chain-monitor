from __future__ import annotations

import pytest
from django.db import connection
from django.db import transaction
from django.db.utils import IntegrityError

from django_service.users.models import User
from tests.factories import UserFactory


def test_user_get_absolute_url(user: User):
    assert user.get_absolute_url() == f"/users/{user.username}/"


@pytest.mark.django_db
def test_user_persists_without_an_identity_key():
    """A user created through the factory carries no identity key until it authenticates."""
    user = UserFactory.create(username="no-identity-key")

    user.refresh_from_db()

    assert user.idp_subject is None


@pytest.mark.django_db
def test_many_users_may_share_a_null_identity_key():
    """NULL is exempt from the unique constraint, which is what lets existing rows survive.

    The usernames are explicit because `UserFactory` declares
    `django_get_or_create = ["username"]` over an unseeded `Faker("user_name")`:
    on a repeated draw the second `create()` would return the first row instead
    of inserting, and this test would report a uniqueness bug that is really a
    factory artifact.
    """
    first = UserFactory.create(username="null-key-first")
    second = UserFactory.create(username="null-key-second")

    assert first.pk != second.pk
    # Scoped to the two rows this test created -- a table-wide count would break
    # on any seeded or fixture-created user and read as a constraint failure.
    persisted = User.objects.filter(pk__in=[first.pk, second.pk], idp_subject__isnull=True)
    assert set(persisted.values_list("pk", flat=True)) == {first.pk, second.pk}


@pytest.mark.django_db
def test_two_users_may_not_share_a_non_null_identity_key():
    """The identity key is the sole store, so a collision is a database error, not a silent merge."""
    UserFactory.create(username="collision-first", idp_subject="idp|shared-subject")

    # The atomic block keeps the broken transaction contained, so the assertion
    # below still has a usable connection.
    with pytest.raises(IntegrityError) as excinfo, transaction.atomic():
        UserFactory.create(username="collision-second", idp_subject="idp|shared-subject")

    # Both backends name the offending column: sqlite reports "UNIQUE constraint
    # failed: users_user.idp_subject", PostgreSQL "...unique constraint
    # \"users_user_idp_subject_key\"". Without this the distinct usernames above
    # are the only thing separating a real finding from a username collision.
    assert "idp_subject" in str(excinfo.value)
    assert User.objects.filter(idp_subject="idp|shared-subject").count() == 1


@pytest.mark.django_db
def test_the_identity_key_is_unique_in_the_schema_not_only_the_model():
    """AC #1's "indexed" half, read out of the backend rather than the declaration.

    `unique=True` is what supplies the index, so the guarantee is only real if
    the database actually carries a unique constraint over the column. The model
    introspection in `tests/unit/users/test_models.py` cannot see that; this can.
    """
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, "users_user")

    # At least one index over the column must be unique -- not every one of them.
    # PostgreSQL carries two indexes here for a single `unique=True` CharField:
    # `users_user_idp_subject_key`, the unique btree that is the guarantee, and
    # `users_user_idp_subject_..._like`, a NON-unique `varchar_pattern_ops` index
    # Django adds for LIKE performance. Requiring all of them to be unique fails
    # on PostgreSQL while passing on the sqlite substitution, which never creates
    # the pattern-ops index -- exactly the R-5 parity gap, and why this assertion
    # is about existence rather than universality.
    unique_over_idp_subject = [
        name
        for name, definition in constraints.items()
        if definition["columns"] == ["idp_subject"] and definition["unique"]
    ]
    assert unique_over_idp_subject, f"no unique index over users_user.idp_subject in {sorted(constraints)}"
