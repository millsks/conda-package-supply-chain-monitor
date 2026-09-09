"""`CPM-AD-19`'s app-level URLconf: this app's HTML surfaces, namespaced.

The decision gives every app under `src/django_apps/` "an app-level `urls.py` with
`app_name` for any HTML views" beside an `api/` subpackage whose routing is central.
This is the first of them.

**Namespaced, and the namespace is load-bearing.** Every reverse in a template goes
through `conda_sentinel:` so a route added by a later story cannot collide with one
of the platform's -- `home`, `about` and the account flows are all unprefixed names
in the root URLconf, and a product route called `home` would silently win or lose
depending on include order.

**Mounted by the root URLconf and not by discovery.** `AD-8` forbids entry-point
discovery, and a URLconf that mounted itself would be exactly that.
"""

from __future__ import annotations

from django.urls import path

from conda_sentinel.surface.views import PackageDetailView
from conda_sentinel.surface.views import PackageHealthView

app_name = "conda_sentinel"

urlpatterns = [
    path("packages/", PackageHealthView.as_view(), name="package-health"),
    # Keyed on the canonical name so a link pasted into a ticket says which package
    # it is about. `<str:>` rather than `<slug:>`: a canonical name may carry a dot
    # or an underscore -- `ruamel.yaml`, `backports.zoneinfo` -- and `slug` matches
    # neither, which would make exactly the packages with awkward names unreachable.
    path("packages/<str:canonical_name>/", PackageDetailView.as_view(), name="package-detail"),
]
