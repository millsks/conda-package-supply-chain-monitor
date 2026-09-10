"""The whole of `CPM-FR-27`'s v1 API, routed in one place.

**Central, and that is `CPM-AD-19`.** A domain app under `src/django_apps/` gets an
app-level `urls.py` for its HTML surfaces and an `api/` subpackage whose *routing* is
here -- so the API's shape is legible in one file rather than assembled from whatever
each app decided to mount. Entry-point discovery is forbidden (inherited `AD-8`), and
a router that discovered its own endpoints would be exactly that.

**Two rosters since `CPM-APP-S14`, mounted at two roots.** The platform's own user
endpoint stays at `/api/`, and this application's move under `/conda-sentinel/api/v1/`
-- the same boundary `CPM-APP-S13` drew for the HTML surfaces, and for the same
reason: a namespace prevents a name collision and not a path one. They are declared
together in this file because routing is central; they are *mounted* apart because
they belong to different things.

That split also removes a wart. While the two shared a root they shared a schema
document, and `tests/unit/django_apps/test_api_contract_audit.py` had to record the
platform's `UserViewSet` as a named exemption in order to answer "what does this API
write" honestly. Two roots, two contracts, and an integrator reading this
application's schema is no longer reading half of somebody's platform.

**This file is where AC 3 is enumerable.** `CPM-APP-S07` gives v1 two writes -- the
package-identity override and the queue action -- and the enumeration is only worth
anything if there is one list to read. There is, below, and
`tests/unit/django_apps/test_api_contract_audit.py` walks the resolver to prove the
list is the truth rather than the intention: every other endpoint answers `GET` and
nothing else, and no endpoint at all writes evidence or a derived status.

**Reads live in `surface`, writes in the domain that owns the data.** The queue
listing is `surface/api/` because it is a read; the queue *action* is
`workflow/api/`, because moving an item is `workflow`'s to do and `CPM-AD-22` says
so. The identity override is `identity/api/` for the same reason and a stronger one:
`CPM-AD-14` makes it the product's one governed write path to reference data, and it
belongs beside the service that guards it.
"""

from django.conf import settings
from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from conda_sentinel.identity.api.views import PackageIdentityOverrideAPIView
from conda_sentinel.surface.api.views import PackageDetailAPIView
from conda_sentinel.surface.api.views import PackageHealthListAPIView
from conda_sentinel.surface.api.views import QueueListAPIView
from conda_sentinel.surface.api.views import ReportAPIView
from conda_sentinel.surface.api.views import ReportRosterAPIView
from conda_sentinel.workflow.api.views import WorkflowItemTransitionAPIView
from django_service.users.api.views import UserViewSet

#: The platform's own API, which this application does not own and does not move.
#:
#: `/api/users/` is the accelerator's: it lets somebody edit their own name. Putting
#: it under this application's prefix would say something untrue about who owns it --
#: the same reasoning `CPM-APP-S13` applied to `/accounts/` and `/users/`.
router = DefaultRouter() if settings.DEBUG else SimpleRouter()

router.register("users", UserViewSet)

#: What the platform's API is reversed by. It keeps `api:` because it is the thing
#: mounted at `/api/`, and a namespace that reversed to a path under a *different*
#: root would read as a lie every time somebody followed it.
platform_urlpatterns = router.urls

#: The reads. Every one is a `GET`, every collection is paginated by the global bound
#: `CPM-AD-12` installs, and every one projects through the same functions the HTML
#: surfaces render from -- which is what `CPM-AD-24` means by "every read surface
#: projects the same values".
read_urls = [
    path("packages/", PackageHealthListAPIView.as_view(), name="package-health"),
    # `<str:>` rather than `<slug:>`: a canonical name may carry a dot or an
    # underscore -- `ruamel.yaml`, `backports.zoneinfo` -- and `slug` matches
    # neither, which would make exactly the packages with awkward names unreachable.
    path("packages/<str:canonical_name>/", PackageDetailAPIView.as_view(), name="package-detail"),
    path("queues/<str:queue>/", QueueListAPIView.as_view(), name="queue"),
    path("reports/", ReportRosterAPIView.as_view(), name="report-roster"),
    path("reports/<str:slug>/", ReportAPIView.as_view(), name="report"),
]

#: The writes. **Both of them**, and the list is AC 3 restated as data.
#:
#: Neither writes evidence or a derived status, and neither could: `CPM-AD-10` gives
#: the application layer no path to either, and both of these delegate to a service
#: whose whole job is guarding the one write it does make.
#:
#: A third entry here is a change to the product's contract and should read like one
#: in a diff, which is the reason for the separate list rather than one flat roster.
write_urls = [
    # `CPM-AD-14`'s governed write to reference data. Keyed on the surrogate integer
    # rather than the name, because the name is the thing being corrected.
    path(
        "packages/<int:package_id>/identity-override/",
        PackageIdentityOverrideAPIView.as_view(),
        name="package-identity-override",
    ),
    # `CPM-AD-22`'s queue action. It moves an item and never creates one -- opening
    # work is the policy run's, and an endpoint that created an item would let an
    # integrator invent a finding the product never derived.
    path(
        "workflow-items/<int:item_id>/transition/",
        WorkflowItemTransitionAPIView.as_view(),
        name="workflow-item-transition",
    ),
]

#: This application's API, reversed by `conda_sentinel_api:` and mounted under
#: `/conda-sentinel/api/v1/`.
#:
#: Named for what it is rather than sharing `api:` with the platform's, because after
#: `CPM-APP-S14` the two live at different roots -- and a namespace whose name says
#: `api` while reversing to somebody else's prefix is the kind of small untruth that
#: costs an afternoon.
product_urlpatterns = [*read_urls, *write_urls]
