from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CollectorsConfig(AppConfig):
    """The collectors application, third under the second import root.

    `name` is `conda_package_supply_chain_monitor.collectors`, never
    `django_apps.conda_package_supply_chain_monitor.collectors`:
    `src/django_apps/` is a path root declared by
    `[tool.hatch.build.targets.wheel.sources]` in `pyproject.toml`, not a
    package, and it carries no `__init__.py`. It never appears in an import
    statement.

    The derived label is `collectors`, the last segment of `name`. It is the home
    the architecture spine's capability map gives `CPM-EP-IDENTITY` alongside
    `identity`, and the one `CPM-EP-CURRENCY`, `CPM-EP-SECURITY` and
    `CPM-EP-PY314` will add their own collectors and evidence tables to.

    **The evidence table lives here rather than in `identity`.** `CPM-AD-7` gives
    each collector its own evidence table, and putting `inventory_snapshots` in
    `identity` would put an append-only log inside the application that owns the
    one mutable package row -- which is exactly the confusion `CPM-AD-25` exists
    to prevent.

    No `default_auto_field`. `config/settings/base.py` sets
    `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"` project-wide, and a
    per-app restatement is a second declaration of the shape `CPM-AD-3` fixes.

    **It does declare `ready()`, and it is the first adopted application that
    does.** `core` and `identity` declare none, and their AppConfigs say why:
    `django_service.users` is the sole stage-two owner (AD-26), and what holds
    that is ordering rather than a ban on the hook --
    `tests/unit/startup/test_installed_apps_ordering.py` asserts that every
    adopted application is installed *after* the owner, so stage two has already
    run by the time anything of this application's does. The hook here adopts one
    collector into `core`'s registry, which is where `CPM-AD-28`'s boot sweep and
    `CPM-AD-20`'s scheduling both look for it -- and `core/registry.py` requires
    exactly this: "a collector arrives here because somebody wrote
    `register(TheCollector)` in an `AppConfig.ready()`, where a reader can see
    it."
    """

    name = "conda_package_supply_chain_monitor.collectors"
    verbose_name = _("Collectors")

    def ready(self) -> None:
        """Adopt this application's collectors, declared one by one (AD-8).

        Registration is a side effect of adoption rather than of import: nothing
        self-registers and nothing is discovered by entry point or module walk,
        so "which collectors does this component run" is answered by the lines
        below and by no other mechanism.

        **Adopting the same class twice is a no-op, and that is not a softening
        of `core/registry.py`'s duplicate-name refusal.** That refusal is about
        two *different* classes under one name -- they would share an allowance,
        share a run history, and be indistinguishable in every report -- and it
        still fires here, because the guard compares identity rather than merely
        checking the name. What it stops is a `ready()` that runs a second time
        aborting process startup over an adoption that had already succeeded:
        `AppConfig.ready` is Django's to call, a second `django.setup()` in one
        process calls it again, and a `CollectorRegistryError` out of a boot hook
        is a component that will not start for no reason anybody chose.
        """
        # Imported here rather than at module scope: `AppConfig` classes are
        # imported during `django.setup()` *before* the app registry is
        # populated, and this module reaches models through the collector it
        # registers -- a module-scope import would raise `AppRegistryNotReady`.
        from conda_package_supply_chain_monitor.collectors.tasks import (  # noqa: PLC0415 - see above
            InventoryIngestionCollector,
        )
        from conda_package_supply_chain_monitor.core.registry import register  # noqa: PLC0415 - see above
        from conda_package_supply_chain_monitor.core.registry import registrations  # noqa: PLC0415 - see above

        if registrations().get(InventoryIngestionCollector.name) is not InventoryIngestionCollector:
            register(InventoryIngestionCollector)
