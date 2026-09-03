"""The public API surface of the user resource. No database is touched."""

from __future__ import annotations

from django_service.users.api.serializers import UserSerializer


def test_the_identity_key_is_not_part_of_the_api_surface() -> None:
    """AD-11: the API exposes attributes; the identity key is not an attribute.

    `UserSerializer` enumerates its fields today, so this holds by construction.
    It is asserted anyway because a later `fields = "__all__"` would publish the
    identity key over REST with every other test still green.
    """
    assert "idp_subject" not in UserSerializer().fields
    assert set(UserSerializer().fields) == {"username", "name", "url"}
