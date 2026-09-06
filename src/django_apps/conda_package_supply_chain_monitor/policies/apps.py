from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PoliciesConfig(AppConfig):
    """The policy application, fourth under the second import root.

    `name` is `conda_package_supply_chain_monitor.policies`, never
    `django_apps.conda_package_supply_chain_monitor.policies`:
    `src/django_apps/` is a path root declared by
    `[tool.hatch.build.targets.wheel.sources]` in `pyproject.toml`, not a
    package, and it carries no `__init__.py`. It never appears in an import
    statement.

    The derived label is `policies`, the last segment of `name`. It is the home
    the architecture spine's source tree gives the passes, and the capability map
    puts `CPM-EP-CURRENCY`, `CPM-EP-SECURITY`, `CPM-EP-PY314` and
    `CPM-EP-PRIORITY` in it alongside their collectors.

    **Why this application exists rather than the pass living in `core`.**
    `core` holds the machinery -- `PolicyPass`, the registry, the orchestration
    and the one rollup writer -- and a domain policy declared there would be a
    rule nobody could withdraw without touching the machinery that runs it.
    `collectors` is ruled out from the other side: `CPM-AD-8` says a collector
    never computes a derived status. So the first pass is the story that creates
    the home, exactly as `CPM-IDENTITY-S06` was the story that made the
    collectors application declare a `ready()`.

    No `default_auto_field`. `config/settings/base.py` sets
    `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"` project-wide, and a
    per-app restatement is a second declaration of the shape `CPM-AD-3` fixes.

    **It declares `ready()`, and it is the second adopted application that
    does.** `core` and `identity` declare none, and their AppConfigs say why;
    `collectors` declares one for the same reason this does. What holds
    `AD-26`'s sole stage-two owner is ordering rather than a ban on the hook --
    `tests/unit/startup/test_installed_apps_ordering.py` asserts that every
    adopted application is installed *after* the owner, so stage two has already
    run by the time anything of this application's does.
    """

    name = "conda_package_supply_chain_monitor.policies"
    verbose_name = _("Policies")

    def ready(self) -> None:
        """Adopt this application's policy passes, one by one (AD-8).

        Registration is a side effect of adoption rather than of import: nothing
        self-registers and nothing is discovered by entry point or module walk,
        so "which passes does this component run" is answered by the tuple below
        and by no other mechanism. `core/policy.py` requires exactly this -- "a
        pass arrives here because somebody wrote `register_pass(TheCurrencyPass)`
        where a reader can see it".

        **The order is a declaration, and it is why this is a tuple.**
        `core/policy.py` keeps registration order where the collector registry
        sorts by name, because `CPM-AD-21` lets a later pass read an earlier
        pass's derived rows for the same run. One pass today; the loop is what
        keeps the ordering explicit when there are seven.

        **Adopting the same class twice is a no-op, and that is not a softening
        of the registry's duplicate-name refusal.** That refusal is about two
        *different* classes under one name, and it still fires here, because the
        guard compares identity rather than merely checking the name. What it
        stops is a `ready()` that runs a second time aborting process startup
        over an adoption that had already succeeded: `AppConfig.ready` is
        Django's to call, a second `django.setup()` in one process calls it
        again, and a `PolicyPassError` out of a boot hook is a component that
        will not start for no reason anybody chose. `collectors/apps.py` guards
        its registrations the same way and for the same reason.

        **No refusal is evaluated here, and that is a difference from
        `collectors/apps.py` worth stating.** That hook re-asks `CPM-AD-28`'s
        freshness rule and `CPM-AD-20`'s cadence reconciliation because stage two
        sweeps a registry it has not populated yet. A pass declares no freshness
        target and no cadence -- it runs inside a policy run rather than on a
        schedule of its own -- so there is no equivalent rule to re-ask, and a
        refusal invented here would be one nothing in the architecture asks for.
        What `register_pass` itself refuses is checked at the moment of
        registration, which is this call.
        """
        # Imported here rather than at module scope: `AppConfig` classes are
        # imported during `django.setup()` *before* the app registry is
        # populated, and this module reaches models through the pass it
        # registers -- a module-scope import would raise `AppRegistryNotReady`.
        from conda_package_supply_chain_monitor.core.policy import pass_registrations  # noqa: PLC0415 - see above
        from conda_package_supply_chain_monitor.core.policy import register_pass  # noqa: PLC0415 - see above
        from conda_package_supply_chain_monitor.policies.currency import CurrencyPass  # noqa: PLC0415 - see above

        for policy_pass in (CurrencyPass,):
            if pass_registrations().get(policy_pass.name) is not policy_pass:
                register_pass(policy_pass)
