from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

from config.startup import run_stage_two


class UsersConfig(AppConfig):
    name = "django_service.users"
    verbose_name = _("Users")

    def ready(self) -> None:
        """Run stage 2 of the refusal contract (AD-26, FR-12).

        This application is the named stage-2 owner --
        `config.startup.stage_two.STAGE_TWO_OWNER_APP_LABEL` is its label, and
        `tests/unit/startup/test_installed_apps_ordering.py` asserts that no
        adopted application precedes it in `INSTALLED_APPS`. It is an immovable
        core app inside `django_service`, which AD-29 makes `core` in its
        entirety, so the invocation point travels in all six combinations by
        construction and cannot be scoped out of one of them.
        """
        # This runs inside `django.setup()`, which is boot, so FR-23 and NFR-1
        # apply to whatever `run_stage_two()` grows into: no network call, and
        # no query beyond migration state. `tests/unit/test_no_network_at_boot.py`
        # enforces the network half, booting this component with every socket
        # refused.
        run_stage_two()
