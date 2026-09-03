"""The probe routes: `livez` and `readyz`, at the root and behind nothing.

**No trailing slash, and no prefix.** Platform probe configuration is written by
hand into a deployment manifest, and every slash and path segment in it is a
chance to point the liveness probe at the readiness path. Short, root-level,
slashless paths are the convention every platform's examples use, and matching it
is worth more here than matching this component's other routes.

**Behind no authentication, and deliberately not under a prefix that has any.**
Not under the admin mount, not under `api/`, not under `accounts/`. A probe
carries no credential, so a route that required one would report a perfectly
healthy process as unhealthy and the platform would restart it. FR-17's allowlist
governs the route prefixes that *are* credential paths -- `accounts/`, the admin
mount, the local sign-in prefix and `api/auth-token/` -- and root-level `livez`
and `readyz` fall under none of them, so they are not judged by it and must not be
added to it: an allowlist entry would state that these routes are part of the
component's authentication surface, which is exactly what they are not.

**No `app_name`, so no namespace.** `reverse("liveness")` and
`reverse("readiness")` are the names, unqualified. A namespace would be the right
call for a reusable application's routes; these are two fixed operational paths
that exist exactly once per component, and `health:liveness` would only give a
caller a second spelling to get wrong.
"""

from __future__ import annotations

from django.urls import path

from config.health.views import liveness
from config.health.views import readiness

urlpatterns = [
    path("livez", liveness, name="liveness"),
    path("readyz", readiness, name="readiness"),
]
