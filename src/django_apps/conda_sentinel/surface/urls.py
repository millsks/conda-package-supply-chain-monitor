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

from conda_sentinel.surface.views import CoverageView
from conda_sentinel.surface.views import HomeView
from conda_sentinel.surface.views import PackageDetailView
from conda_sentinel.surface.views import PackageHealthView
from conda_sentinel.surface.views import QueueView
from conda_sentinel.surface.views import ReportExportView
from conda_sentinel.surface.views import ReportView

app_name = "conda_sentinel"

urlpatterns = [
    # Not mounted at `/`: the root belongs to the platform's own template, and taking
    # it would mean this product decided what an accelerator-built component's front
    # page is. `home` is the product's front page and the nav points at it.
    path("home/", HomeView.as_view(), name="home"),
    path("coverage/", CoverageView.as_view(), name="coverage"),
    path("packages/", PackageHealthView.as_view(), name="package-health"),
    # Keyed on the canonical name so a link pasted into a ticket says which package
    # it is about. `<str:>` rather than `<slug:>`: a canonical name may carry a dot
    # or an underscore -- `ruamel.yaml`, `backports.zoneinfo` -- and `slug` matches
    # neither, which would make exactly the packages with awkward names unreachable.
    path("packages/<str:canonical_name>/", PackageDetailView.as_view(), name="package-detail"),
    # One route for three queues, because they are three filtered views over one
    # table (`CPM-AD-22`) and three routes would invite three views. `<str:>` rather
    # than an enumeration in the pattern: the closed set is `QUEUE_OWNERS`, and a
    # segment outside it is a 404 the view raises with a message naming the queues
    # that do exist.
    path("queues/<str:queue>/", QueueView.as_view(), name="queue"),
    # One route for six reports, on the same terms the queues take one for three:
    # they are six questions over one rollup, and six routes would invite six views
    # and six chances to forget the provenance every report has to state.
    path("reports/<str:slug>/", ReportView.as_view(), name="report"),
    path("reports/<str:slug>/export/", ReportExportView.as_view(), name="report-export"),
]
