from __future__ import annotations

import typing

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

# The social adapter that used to sit beside this class is gone. It lives at
# `config.authorization.adapters.OIDCSocialAccountAdapter` now, because AD-11
# routes every interactive sign-in through the mapper and AD-4 forbids
# `django_service` importing `config`. Its `populate_user` name derivation went
# with it rather than moving: the mapper owns every claim-derived attribute.


# django-allauth ships no `py.typed` marker and no stub package exists for it on
# conda-forge, so `ignore_missing_imports` resolves every allauth name to `Any`
# and strict mode refuses the subclass. The base classes are real; only their
# types are missing upstream. `warn_unused_ignores` removes these the moment
# allauth starts publishing types.
class AccountAdapter(DefaultAccountAdapter):  # type: ignore[misc]
    def is_open_for_signup(self, request: HttpRequest) -> bool:
        """Report whether self-service registration is permitted.

        Args:
            request: The request asking to sign up.

        Returns:
            The value of the ``ACCOUNT_ALLOW_REGISTRATION`` setting.

        """
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)
