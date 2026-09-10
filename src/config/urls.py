from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include
from django.urls import path
from django.views import defaults as default_views
from django.views.generic import RedirectView
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView

from config.local_dev.constants import LOCAL_SIGNIN_PATH_PREFIX
from config.locality import is_local

if TYPE_CHECKING:
    from django.urls import URLPattern
    from django.urls import URLResolver

urlpatterns = [
    # The platform's probes, first (AD-22, Story 5.3). First because the resolver
    # walks this list in order and `livez`/`readyz` are the two paths that must
    # answer while everything else about this process may be in doubt; also
    # because the head of the list is the one insertion point that stays correct
    # however the entries below it change -- Epic 7's Story 7.4 deletes the home
    # and about routes as demonstration content (AD-29), so anchoring on them
    # would break with that story rather than with anything about health.
    #
    # Mounted at the root and behind no prefix: a probe carries no credential.
    # See config/health/urls.py for why the paths carry no trailing slash and are
    # not part of the FR-17 authentication surface.
    path("", include("config.health.urls")),
    path(
        "about/",
        TemplateView.as_view(template_name="pages/about.html"),
        name="about",
    ),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("django_service.users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    # This product's own HTML surfaces (`CPM-AD-19`), namespaced `conda_sentinel:`
    # and mounted under the application's own name since `CPM-APP-S13`.
    #
    # **One line, and that is the point of `CPM-AD-19`.** Routing is central, and
    # every template and test reaches these pages through the namespace rather than
    # through a written path -- so moving all of them is this prefix and nothing else.
    #
    # The prefix names the *application within this service*. `django_apps/` is a
    # second import root and `component.toml` adopts applications explicitly; the
    # paths this product holds are the generic ones -- `packages`, `reports`,
    # `coverage`, `queues` -- and a namespace prevents a name collision, not a path
    # one. A second product adopted beside this one would shadow a route silently.
    #
    # It is not `FORCE_SCRIPT_NAME`, which names the *service within a host* and moves
    # `/api/` and the accounts flows with it. A deployment can use both.
    #
    # Mounted here rather than discovered: `AD-8` forbids entry-point discovery, and
    # a domain app that mounted its own routes would be exactly that.
    path("conda-sentinel/", include("conda_sentinel.surface.urls")),
    # The root leads here. `CPM-APP-S12` made the front door this product's and
    # `CPM-APP-S13` moved the pages behind the prefix; a permanent redirect is what
    # keeps the front door working. `RedirectView` rather than a view of our own:
    # there is nothing to decide, and `pattern_name` means the target follows the
    # route if it ever moves again.
    path("", RedirectView.as_view(pattern_name="conda_sentinel:home", permanent=False), name="root"),
    # Media files
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]
if settings.DEBUG:
    # DEBUG only: route static files through the resolver. staticfiles.views.serve
    # finds them via the staticfiles finders -- the source dirs, not STATIC_ROOT,
    # which is WhiteNoise's surface and is not a route.
    urlpatterns += staticfiles_urlpatterns()

# API URLS
urlpatterns += [
    # API base url
    path("api/", include("config.api_router")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-docs",
    ),
]


def local_signin_urlpatterns() -> list[URLPattern | URLResolver]:
    """Return the local persona sign-in mount, or nothing when this is not a local run.

    AD-21 states the rule this function is: "the module ships in every component;
    the route is mounted only where locality is local", and "shipping is not
    mounting". FR-13 makes a reachable local sign-in route a stage-2 refusal
    condition, so a route mounted unconditionally would make every deployed
    component refuse to start and nothing would ever deploy.

    Gated on `config.locality.is_local()` and never on `settings.DEBUG`. `DEBUG`
    is a rendering decision and not the locality signal (AD-13); a deployed
    component with it mistakenly true would otherwise mount a live credential
    path. This is a runtime configuration branch inside a `core` path that ships
    in every combination, so it is not AD-24's conditional-import prohibition,
    which governs feature removal during materialization.

    **Why this is a function and not a bare `if` at module scope.** A URLconf's
    locality branch is evaluated once, at import time, and the whole suite runs
    in the `dev` pixi environment, which declares `COMPONENT_RUNTIME=local` in
    its activation env. A module-level `if` is therefore assertable only by
    reloading this module -- which mutates an object every later test in the
    session resolves through. A function makes both branches directly callable
    under a monkeypatched environment, with nothing reloaded and nothing to
    restore.

    Returns:
        A single-entry list mounting `config.local_dev.urls` at the declared
        prefix when the run is local, otherwise an empty list. The include is by
        dotted string, so that URLconf is imported as the mount is built and a
        deployed component -- which takes the empty branch -- never imports it
        at all.

    """
    if not is_local():
        return []
    return [path(LOCAL_SIGNIN_PATH_PREFIX, include("config.local_dev.urls"))]


urlpatterns += local_signin_urlpatterns()

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
            *urlpatterns,
        ]
