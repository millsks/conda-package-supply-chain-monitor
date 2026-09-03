from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    """The first domain application to live under the second import root.

    `name` is `conda_package_supply_chain_monitor.core`, never
    `django_apps.conda_package_supply_chain_monitor.core`: `src/django_apps/` is
    a path root declared by `[tool.hatch.build.targets.wheel.sources]` in
    `pyproject.toml`, not a package, and it carries no `__init__.py`. It never
    appears in an import statement. The distribution package inside it is what
    every domain application is a subpackage of, so they share one stable
    top-level name.

    The derived label is `core`, the last segment of `name`.

    No `ready()`. `django_service.users` is the sole stage-two owner (AD-26).
    What holds that here is ordering, not a ban on the hook:
    `tests/unit/startup/test_installed_apps_ordering.py` asserts that this
    application is installed after the owner, so the refusal contract has
    already been evaluated by the time anything of this application's runs, and
    `tests/unit/django_apps/test_core_app.py` asserts that this class defines no
    `ready()` at all. Adding one would need both to be reconsidered.
    """

    name = "conda_package_supply_chain_monitor.core"
    verbose_name = _("Core")
