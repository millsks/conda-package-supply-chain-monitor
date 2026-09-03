"""Tests for the allauth account adapter.

These exercise adapter behaviour against unsaved User instances, so they need
no database.

The social adapter's cases are not here. It moved to
`config.authorization.adapters` when AD-11 routed interactive sign-in through
the mapper, and its tests moved with it to
`tests/unit/authorization/test_adapters.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.test import RequestFactory

from django_service.users.adapters import AccountAdapter

if TYPE_CHECKING:
    from django.http import HttpRequest


@pytest.fixture
def http_request() -> HttpRequest:
    return RequestFactory().get("/")


class TestAccountAdapter:
    def test_open_for_signup_by_default(self, http_request: HttpRequest):
        assert AccountAdapter().is_open_for_signup(http_request) is True

    def test_registration_can_be_disabled(self, settings, http_request: HttpRequest):
        settings.ACCOUNT_ALLOW_REGISTRATION = False
        assert AccountAdapter().is_open_for_signup(http_request) is False


def test_the_social_adapter_no_longer_lives_here():
    """AD-4: `django_service` may not import `config`, so the social adapter cannot stay.

    Asserted rather than left implicit because the class leaving is what forces
    `SOCIALACCOUNT_ADAPTER` to point at the authorization package. A copy
    reappearing here would give the component two social adapters, one of which
    consults no mapper.
    """
    import django_service.users.adapters as module  # noqa: PLC0415

    assert not hasattr(module, "SocialAccountAdapter")
