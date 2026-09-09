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
