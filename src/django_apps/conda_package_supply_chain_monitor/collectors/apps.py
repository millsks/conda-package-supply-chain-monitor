from typing import Final

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

#: The setting `config/settings/base.py` assigns the selected watchlist to.
#: Spelled once, here, so the refusal below names the same thing the read asks
#: for -- a literal in each would be two names that can drift apart.
WATCHLIST_PATH_SETTING: Final[str] = "INVENTORY_WATCHLIST_PATH"


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
    run by the time anything of this application's does. The hook here adopts this
    application's collectors into `core`'s registry, which is where `CPM-AD-28`'s
    boot sweep and `CPM-AD-20`'s scheduling both look for them -- and
    `core/registry.py` requires exactly this: "a collector arrives here because
    somebody wrote `register(TheCollector)` in an `AppConfig.ready()`, where a
    reader can see it."
    """

    name = "conda_package_supply_chain_monitor.collectors"
    verbose_name = _("Collectors")

    def ready(self) -> None:
        """Adopt this application's collectors and its inventory source, one by one (AD-8).

        Registration is a side effect of adoption rather than of import: nothing
        self-registers and nothing is discovered by entry point or module walk,
        so "which collectors does this component run" is answered by the lines
        below and by no other mechanism. The inventory source adapter is declared
        on exactly the same terms (`CPM-AD-29`): one call, in a place a reader
        can see it, and no entry point, module scan or import walk anywhere.

        **The watchlist path is read from settings rather than selected here.**
        `CPM-AD-29` selects the file by `config.locality.is_local()`, and `AD-4`
        forbids anything under `src/django_apps/` importing `config` --
        `config/settings/base.py` performs the read and assigns
        `INVENTORY_WATCHLIST_PATH`, in the shape `ROLE_CONTRACT` already
        establishes. What is here is the settings *access*, which is a read of a
        value the platform composed and not a second selection rule.

        **The roster is a loop over a tuple rather than a line per collector.**
        Eight are coming (`CPM-EP-CURRENCY`, `CPM-EP-SECURITY`, `CPM-EP-PY314`),
        and the guard below is the part that must not be written eight times: a
        copy of it that compared the wrong name, or that was left off a new
        adoption, would either abort boot on a second `django.setup()` or register
        nothing at all. Adoption stays explicit -- every class is named in the
        tuple, where a reader can see it, and nothing is discovered (inherited
        `AD-8`).

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

        **The adapter declaration is guarded the same way and for the same
        reason.** `declare_inventory_adapter` refuses a second declaration --
        deliberately, because a second one silently replacing the first is how a
        deployed component comes to ingest a development subset and record every
        package outside it as absent -- so a `ready()` that ran twice would abort
        boot. The guard is as narrow as the registration's beside it: it passes
        only for a `WatchlistAdapter` **already reading the very file settings
        selected**. An adapter of another kind, and a watchlist adapter bound to
        another path, both reach `declare_inventory_adapter` and are both
        refused, because "which file is this component's inventory" is exactly
        the question `CPM-AD-29` will not have answered by import order.

        Raises:
            ImproperlyConfigured: When the settings module declares no
                `INVENTORY_WATCHLIST_PATH`. Refused rather than left to an
                `AttributeError`: a settings module that dropped the assignment
                is a misconfiguration like every other one here, and a bare
                attribute error out of a boot hook says nothing about which
                setting is missing or what declares it.

        """
        # Imported here rather than at module scope: `AppConfig` classes are
        # imported during `django.setup()` *before* the app registry is
        # populated, and this module reaches models through the collector it
        # registers -- a module-scope import would raise `AppRegistryNotReady`.
        from django.conf import settings  # noqa: PLC0415 - see above
        from django.core.exceptions import ImproperlyConfigured  # noqa: PLC0415 - see above

        from conda_package_supply_chain_monitor.collectors.feedstock import (  # noqa: PLC0415 - see above
            FeedstockCollector,
        )
        from conda_package_supply_chain_monitor.collectors.pypi_release import (  # noqa: PLC0415 - see above
            PyPIReleaseCollector,
        )
        from conda_package_supply_chain_monitor.collectors.source_release import (  # noqa: PLC0415 - see above
            SourceReleaseCollector,
        )
        from conda_package_supply_chain_monitor.collectors.tasks import (  # noqa: PLC0415 - see above
            InventoryIngestionCollector,
        )
        from conda_package_supply_chain_monitor.collectors.tasks import (  # noqa: PLC0415 - see above
            declare_inventory_adapter,
        )
        from conda_package_supply_chain_monitor.collectors.tasks import (  # noqa: PLC0415 - see above
            declared_inventory_adapter,
        )
        from conda_package_supply_chain_monitor.collectors.watchlist import (  # noqa: PLC0415 - see above
            WatchlistAdapter,
        )
        from conda_package_supply_chain_monitor.core.registry import register  # noqa: PLC0415 - see above
        from conda_package_supply_chain_monitor.core.registry import registrations  # noqa: PLC0415 - see above

        for collector in (
            InventoryIngestionCollector,
            SourceReleaseCollector,
            PyPIReleaseCollector,
            FeedstockCollector,
        ):
            if registrations().get(collector.name) is not collector:
                register(collector)

        selected = getattr(settings, WATCHLIST_PATH_SETTING, None)
        if selected is None:
            message = (
                f"{WATCHLIST_PATH_SETTING} is not configured, so this component has no inventory source "
                f"file to declare an adapter for. config/settings/base.py assigns it as "
                f"watchlist_path(local=is_local()) -- locality selects the file and fails closed toward "
                f"production (CPM-AD-29)."
            )
            raise ImproperlyConfigured(message)

        declared = declared_inventory_adapter()
        if not (isinstance(declared, WatchlistAdapter) and declared.path == selected):
            declare_inventory_adapter(WatchlistAdapter(path=selected))
