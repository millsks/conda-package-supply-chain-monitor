from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from django.http import HttpRequest


def allauth_settings(request: HttpRequest) -> dict[str, bool]:
    """Expose some settings from django-allauth in templates.

    Args:
        request: The request being rendered. Unused; the context processor
            contract requires it.

    Returns:
        The template context fragment carrying the registration switch.

    """
    return {
        "ACCOUNT_ALLOW_REGISTRATION": settings.ACCOUNT_ALLOW_REGISTRATION,
    }
