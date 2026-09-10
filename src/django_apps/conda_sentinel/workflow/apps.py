from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WorkflowConfig(AppConfig):
    """The one application that owns every queue item (`CPM-AD-22`).

    All three queues -- identity review, remediation and compliance review -- are
    filtered views over one table here, not three models in three applications. The
    decision names the failure that buys: "the same item existing twice in two
    role-exclusive queues with diverging state". One row cannot diverge from itself.

    **The identity review queue lives here and not in `identity`**, which is the part
    that looks wrong until the reason is said: it has to rank by the same
    bucket-then-score rule the other two do, and a queue in another application would
    grow its own ranking within a week.

    Installed after `policies` because the policy run opens items, and before
    `surface` because the queues are read there. Declares no `ready()`:
    `django_service.users` is the sole stage-two owner (`AD-26`), and this
    application registers nothing.

    The derived label is `workflow`, the last segment of `name`.
    """

    name = "conda_sentinel.workflow"
    verbose_name = _("Workflow")

    def ready(self) -> None:
        """Register the step that opens queue items after a policy run.

        Registration is a side effect of *adoption* rather than of import, exactly as
        `policies/apps.py` adopts its passes: nothing self-registers and nothing is
        discovered by entry point or module walk, so a component that has not adopted
        this application opens no items and `core` is none the wiser.

        The import is here rather than at module scope because `apps.py` is imported
        during `django.setup()` *before* the app registry is populated, and
        `workflow/opening.py` reads models.
        """
        from conda_sentinel.core.after_run import register_after_run_step  # noqa: PLC0415 - see above
        from conda_sentinel.workflow.opening import OPENING_STEP_NAME  # noqa: PLC0415 - see above
        from conda_sentinel.workflow.opening import open_queue_items  # noqa: PLC0415 - see above

        register_after_run_step(OPENING_STEP_NAME, open_queue_items)
