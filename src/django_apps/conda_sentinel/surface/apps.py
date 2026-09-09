from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SurfaceConfig(AppConfig):
    """The read surfaces the three roles work in: `CPM-EP-APP`'s screens.

    The fifth application under the second import root, and the first with no
    models. That is not an oversight and it is what the application is *for*:
    `CPM-AD-10` gives the application layer no write path to a derived status or to
    evidence, so a read surface that declared a model would be declaring the one
    thing the decision forbids it. Workflow state and the identity override are the
    product's two human writes and neither lives here -- `CPM-AD-22` gives the first
    to a `workflow` application and `CPM-AD-14` has already given the second to
    `identity`.

    **Why this is a separate application and not more of `core`.** `core` is
    deliberately kept free of any import from `policies`: the policy-run
    orchestrator reaches its passes through the registry `policies/apps.py` fills at
    `ready()`, never by importing them, which is what lets a pass be added without
    touching the orchestrator. A read surface cannot work that way -- it has to know
    that a vulnerability verdict is on `package_vulnerability.vulnerability_status`
    and that the advisory behind it is on `vulnerability_finding` -- so putting the
    projection in `core` would have inverted that dependency for every module in the
    package. Here it is the ordinary direction: this application sits on top of
    `core`, `policies` and `identity`, and nothing sits on top of it.
    `tests/unit/django_apps/test_app_layering_audit.py` holds the rule.

    The derived label is `surface`, the last segment of `name`.

    No `ready()`, on the terms `CoreConfig` states: `django_service.users` is the
    sole stage-two owner (`AD-26`), and this application registers nothing.
    """

    name = "conda_sentinel.surface"
    verbose_name = _("Surface")
