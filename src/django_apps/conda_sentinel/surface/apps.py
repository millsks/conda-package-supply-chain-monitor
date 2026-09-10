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

    **It acquired a `ready()` in `CPM-APP-S08`**, which is worth saying because the
    docstring here previously stated it had none. `CPM-AD-9` sends an export beyond
    the row cap out of the request, and the work that leaves is *this* application's
    -- producing a report is what `surface/reports.py` does. `core` may not import
    it, so `core/jobs.py` declares the seam and this fills it, on the same terms
    `policies/apps.py` adopts its passes and `workflow/apps.py` adopts its after-run
    step. It is still not a stage-two owner: `django_service.users` remains the sole
    one (`AD-26`), and this registers a runner rather than configuring anything.
    """

    name = "conda_sentinel.surface"
    verbose_name = _("Surface")

    def ready(self) -> None:
        """Register the runner that produces a report export outside a request.

        Registration is a side effect of *adoption* rather than of import: nothing
        self-registers and nothing is discovered, so a component that has not adopted
        this application runs no exports and `core` is none the wiser.

        The import is here rather than at module scope because `apps.py` is imported
        during `django.setup()` *before* the app registry is populated, and the
        runner's module reaches models through the report projection.
        """
        from conda_sentinel.core.jobs import register_job_runner  # noqa: PLC0415 - see above
        from conda_sentinel.surface.exports import EXPORT_JOB_KIND  # noqa: PLC0415 - see above
        from conda_sentinel.surface.exports import run_export_job  # noqa: PLC0415 - see above

        register_job_runner(EXPORT_JOB_KIND, run_export_job)
