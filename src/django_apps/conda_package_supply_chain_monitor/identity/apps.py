from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IdentityConfig(AppConfig):
    """The package-identity application, second under the second import root.

    `name` is `conda_package_supply_chain_monitor.identity`, never
    `django_apps.conda_package_supply_chain_monitor.identity`: `src/django_apps/`
    is a path root declared by `[tool.hatch.build.targets.wheel.sources]` in
    `pyproject.toml`, not a package, and it carries no `__init__.py`. It never
    appears in an import statement. The distribution package inside it is what
    every domain application is a subpackage of, so they share one stable
    top-level name.

    The derived label is `identity`, the last segment of `name`. Bare "identity"
    is forbidden in prose (PRD §3 Glossary) -- this is the *package*-identity
    application, and the app label is the one place the bare word is a Django
    identifier rather than a term.

    No `default_auto_field`. `config/settings/base.py:149` sets
    `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"` project-wide, and a
    per-app restatement is a second declaration of one decision -- the shape
    `CPM-AD-3` fixes for every table in this product.

    No `ready()`. `django_service.users` is the sole stage-two owner (AD-26).
    What holds that here is ordering, not a ban on the hook:
    `tests/unit/startup/test_installed_apps_ordering.py` asserts that every
    adopted application is installed after the owner, so the refusal contract
    has already been evaluated by the time anything of this application's runs,
    and `tests/unit/django_apps/test_identity_app.py` asserts that this class
    defines no `ready()` at all. Adding one would need both to be reconsidered.
    """

    name = "conda_package_supply_chain_monitor.identity"
    verbose_name = _("Package identity")
