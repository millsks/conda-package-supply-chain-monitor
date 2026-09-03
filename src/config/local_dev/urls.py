"""The two local sign-in routes, included by the project URLconf only when local.

Two routes and no third. The index is a `GET` at the prefix itself; the act is a
`POST` at the prefix plus the persona's key. The key is a **path segment** and
never a query parameter -- AD-21 names "a query-parameter shim" as a forbidden
shape, and a segment is what makes the route enumerable by the refusal contract
rather than one URL that means different things depending on what follows a `?`.

No `app_name`, and therefore no namespace. The URL name is one of the two
constants AD-21 fixes, and a namespace would make the reversible name a
composition of a namespace and that constant -- two declarations where the AD
asks for one, and a second thing Epic 7's move into `accelerator.toml` would have
to carry. The index's name is derived from the same constant rather than declared
beside it, so the pair cannot drift.

This module is imported only where `config.locality.is_local()` answered true.
`config/urls.py` includes it by dotted string from inside a function that
returns nothing on a deployed run, so importing the project URLconf there does
not import this one at all. Importing it would still be harmless; *mounting* it
is what Epic 4's stage-2 condition refuses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import path

from config.local_dev import views
from config.local_dev.constants import LOCAL_SIGNIN_URL_NAME

if TYPE_CHECKING:
    from django.urls import URLPattern

__all__ = ["urlpatterns"]

urlpatterns: list[URLPattern] = [
    path("", views.persona_index, name=f"{LOCAL_SIGNIN_URL_NAME}_index"),
    path("<slug:persona_key>/", views.persona_signin, name=LOCAL_SIGNIN_URL_NAME),
]
