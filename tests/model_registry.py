"""How the suite reads Django's model registry, and what it calls an evidence model.

Three audits sweep the registry rather than a hand-written list.
`tests/unit/django_apps/test_outcome_field_audit.py` asks which fields are
derived statuses (`EVIDENCE.01-AUDIT-001`);
`tests/unit/django_apps/test_evidence_inheritance_audit.py` asks whether every
evidence model still carries the append-only guard (`EVIDENCE.02-AUDIT-001`);
`tests/unit/django_apps/test_evidence_constraint_audit.py` asks whether any of
them carries a unique constraint (`EVIDENCE.02-AUDIT-003`). All three need the
same primitives -- which applications count as this repository's own, and which
of their models count as evidence -- and a second copy of any of them is the
failure `tests/source_scan.py` was extracted to prevent: two sweeps that
disagree about what they cover look exactly like two passing tests.

**Scope is taken from the source tree, never from a list of app labels.** An
application added under `src/django_apps/` is in scope the moment it exists,
which is the same promise the import-root remapping in `pyproject.toml` makes.
A list would be edited by whoever remembered it existed, so the first evidence
app added by somebody who did not is the one that escapes every audit here.

The scope is *installed* applications, and the bound is worth stating: a model
declaring `app_label = "evidence"` while no such application is in
`INSTALLED_APPS` is returned by no app config and is therefore invisible here.
It is also invisible to Django -- no migration builds its table and no query
routes to it -- so the case is inert rather than an evasion. Adopting the
application is what puts its models in view, and adoption is the two-line,
explicitly declared act inherited `AD-8` requires anyway.

**"Evidence model" is defined three ways, on purpose, and no one of them would
do.**

* *Inherits `AppendOnlyModel`.* Alone it makes `EVIDENCE.02-AUDIT-001` circular
  -- every model inheriting the base inherits the base -- and a table that
  simply forgot the base is invisible.
* *Its app label is `evidence`.* Alone it is escapable by putting the table
  anywhere else, which `CPM-AD-7` positively encourages: each collector owns its
  own evidence table, in its own application. So this mark catches the shape
  `CPM-AD-7` least expects and misses the one it makes the norm.
* *It declares an `observed_at` field.* This is the mark that catches the normal
  case: a collector's evidence model, in the collector's own app, that forgot
  the base carries neither of the first two marks and is caught by this one.
  `observed_at` is not an incidental column name -- `CPM-AD-7` fixes its meaning
  ("always the moment of *this* observation") and `AppendOnlyModel` is the only
  thing in the product that declares it.

**And one declared way out**, because the union has to be escapable by a model
that is legitimately not evidence. `CPM-AD-2` exempts the run ledger --
`collection_runs` and `policy_runs` are mutable by construction -- and
`CPM-EVIDENCE-S03`'s own acceptance criterion requires that exemption to be
"documented at the definition". Setting `not_evidence = True` on the model *is*
that documentation, in a form the audits can read. It is not a quiet door: the
audit records every model that uses it in a table and fails when the two
disagree, exactly as `RECORDED_EXEMPTIONS` does for the source scans.

**Neither mark is empty any more, and that is stated rather than assumed.**
`CPM-IDENTITY-S06` landed the first evidence model -- `collectors.InventorySnapshot`,
the `inventory_snapshots` table `CPM-AD-25` names -- so every sweep over
`evidence_models()` now has a real table to be about, and none of the three
audits needed an edit to start mattering. That is the property the three marks
were built for: the model arrived in a collector's own application, which is the
shape `CPM-AD-7` makes the norm and which the `observed_at` mark catches.
`exempt_models()` has not been empty since `CPM-EVIDENCE-S03`'s run ledger.
What still keeps the audits honest is that each of them *also* measures these
predicates against fixture models built in an isolated registry, conforming and
not -- a single real subject can be conforming for reasons the detector never
had to notice. `isolate_apps`
patches `Options.default_apps` rather than the global `django.apps.apps`, so
those fixtures are invisible to `first_party_models()` below and must be passed
to the predicates directly -- which is why the predicates take a model rather
than reading the registry themselves.

**This module imports a Django model, and `tests/source_scan.py` deliberately
does not.** That module reads its repository root off its own `__file__` so the
source scans work in a collection-only run that never configured Django. This
one cannot: its whole subject is the model registry, which does not exist until
Django is set up. The trade is recorded rather than hidden -- importing this
module in a run without settings fails at import, and `--ds=config.settings.test`
in `addopts` is what guarantees it never happens here.

A helper module, not a collected one. `[tool.pytest.ini_options] python_files`
matches `test_*.py` and `tests.py`, so nothing here is collected, and it sits at
`tests/` rather than under `tests/unit/` for the reason `tests/source_scan.py`
does: a collected test module is not a helper library.
`tests/unit/test_model_registry.py` holds this module's own guards.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final

from django.apps import apps

from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from tests.source_scan import SRC_ROOT

if TYPE_CHECKING:
    from django.db import models

#: The app label `CPM-EP-EVIDENCE`'s own application will carry, per the source
#: tree in the architecture spine. Nothing declares it yet; it is one of the
#: three marks precisely so that the day something does, the audits already apply
#: to it without an edit.
EVIDENCE_APP_LABEL: Final[str] = "evidence"

#: The field whose presence makes a model evidence wherever it lives. Named after
#: the column `AppendOnlyModel` declares and `CPM-AD-7` gives its meaning to.
OBSERVED_AT_FIELD: Final[str] = "observed_at"

#: The class attribute a model sets to `True` to declare, at its definition, that
#: it is not evidence despite carrying a mark. See the module docstring: this is
#: `CPM-AD-2`'s run-ledger exemption made machine-readable, and the audit records
#: every user of it.
NOT_EVIDENCE_ATTRIBUTE: Final[str] = "not_evidence"

#: The models `CPM-AD-2` exempts from the evidence rules, by `app_label.Model`.
#:
#: One home for a pair that three modules need: the recorded table in
#: `tests/unit/django_apps/test_evidence_inheritance_audit.py`, the state
#: assertion in `tests/unit/test_model_registry.py`, and the status-field
#: amendment in `tests/unit/django_apps/test_outcome_field_audit.py`. Two
#: hand-written copies of a list that can disagree look exactly like two passing
#: tests -- which is this module's own argument for existing, applied to itself.
#:
#: It is still a hand-written table, and that is the point: `CPM-AD-2` exempts
#: these two by name, and a third model taking the escape must be recorded here
#: by somebody who decided to, not discovered by a predicate.
RUN_LEDGER_MODEL_LABELS: Final[frozenset[str]] = frozenset({"core.CollectionRun", "core.PolicyRun"})

#: Four applications that must be in scope, so a scope that had narrowed to
#: nothing is caught. `core` is where the base lives; `identity` is the second
#: application under the second import root, and naming it is what keeps the
#: anchor honest now that the scope predicate has more than one `django_apps`
#: subtree to find; `collectors` is the third and is where evidence models
#: actually land (`CPM-AD-7` gives each collector its own table in its own
#: application), so a scope that reached the first two and not it would sweep a
#: repository with no evidence in it; `users` is inherited platform and is still
#: this repository's own source, which is what `CPM-AD-5`'s "anywhere" means.
FIRST_PARTY_APP_NAMES: Final[tuple[str, ...]] = (
    "conda_package_supply_chain_monitor.collectors",
    "conda_package_supply_chain_monitor.core",
    "conda_package_supply_chain_monitor.identity",
    "django_service.users",
)

#: An installed application that must *not* be in scope. Third-party packages
#: carry status fields, unique constraints and cascades of their own, whose rules
#: are not this product's to dictate, and an audit that failed on them would be
#: turned off within a day.
A_THIRD_PARTY_APP_NAME: Final[str] = "allauth.account"

#: What `isolate_apps` is pointed at, and the label the fixture models declare
#: when the label is not itself the thing under test. Declared once here because
#: four test modules build fixture models and a per-module copy is how two of
#: them come to register into different registries.
FIXTURE_APP: Final[str] = "conda_package_supply_chain_monitor.core"
FIXTURE_LABEL: Final[str] = "core"

#: The fact the fixture evidence models observe. One ordinary value, so that
#: nothing about append-only behaviour depends on the shape of what was observed.
A_FACT: Final[str] = "conda-forge/numpy 2.4.0"


def first_party_app_names() -> set[str]:
    """Return the names of every installed application living in this repository.

    Returns:
        The `AppConfig.name` of each installed application whose package sits
        under `src/`. Separate from `first_party_models` because the scope guard
        in each audit asserts against the *applications* -- a scope that had
        narrowed to nothing must be caught even in a repository whose
        applications happen to declare no models.

    """
    return {
        app_config.name
        for app_config in apps.get_app_configs()
        if Path(app_config.path).resolve().is_relative_to(SRC_ROOT)
    }


def installed_app_names() -> set[str]:
    """Return the names of every installed application, first-party or not.

    Returns:
        Every `AppConfig.name`. The scope guards assert a third-party application
        is *installed* before asserting it is out of scope: one that had been
        removed would satisfy "not in scope" for the wrong reason, and the
        exclusion the guard exists to prove would go untested.

    """
    return {app_config.name for app_config in apps.get_app_configs()}


def first_party_models() -> list[type[models.Model]]:
    """Return every model declared by an application living in this repository.

    Returns:
        The models of every installed application whose package sits under
        `src/`, in registry order.

    """
    in_scope = first_party_app_names()
    found: list[type[models.Model]] = []
    for app_config in apps.get_app_configs():
        if app_config.name in in_scope:
            found.extend(app_config.get_models())
    return found


def declares_not_evidence(model: type[models.Model]) -> bool:
    """Report whether a model declares itself exempt from the evidence rules.

    Args:
        model: The model to check.

    Returns:
        True only for `not_evidence = True` written on the model. Any other value
        -- absent, `False`, a truthy string -- is not a declaration, because an
        exemption this consequential should not be reachable by accident.

    """
    return getattr(model, NOT_EVIDENCE_ATTRIBUTE, False) is True


def evidence_marks(model: type[models.Model]) -> list[str]:
    """Return the marks that make a model evidence, in the order they are argued.

    Args:
        model: The model to classify.

    Returns:
        One name per mark the model carries -- `base`, `app_label`,
        `observed_at`. Empty for a model carrying none, and empty for one that
        declares `not_evidence = True`, whatever marks it would otherwise have.
        Returned as a list rather than a boolean so a failure can say *why* the
        model was audited.

    """
    if declares_not_evidence(model):
        return []
    meta = model._meta  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    marks: list[str] = []
    if issubclass(model, AppendOnlyModel):
        marks.append("base")
    if meta.app_label == EVIDENCE_APP_LABEL:
        marks.append("app_label")
    if any(field.name == OBSERVED_AT_FIELD for field in meta.concrete_fields):
        marks.append(OBSERVED_AT_FIELD)
    return marks


def is_evidence_model(model: type[models.Model]) -> bool:
    """Report whether a model is evidence, by any of the three independent marks.

    Args:
        model: The model to classify.

    Returns:
        True when the model carries at least one mark and has not declared
        itself exempt. See the module docstring for why no single mark would do.

    """
    return evidence_marks(model) != []


def evidence_models() -> list[type[models.Model]]:
    """Return every evidence model this repository declares.

    Returns:
        The first-party models carrying at least one mark, in registry order.
        No longer empty -- `CPM-IDENTITY-S06` landed `collectors.InventorySnapshot`
        -- and every caller still pairs its sweep with fixture models, because a
        detector can be right about one real table for reasons that would not
        survive a second.

    """
    return [model for model in first_party_models() if is_evidence_model(model)]


def exempt_models() -> list[type[models.Model]]:
    """Return every first-party model declaring itself not evidence.

    Returns:
        The models setting `not_evidence = True`, in registry order.
        `CPM-EVIDENCE-S03`'s run ledger is the only user, and
        `tests/unit/django_apps/test_evidence_inheritance_audit.py` reconciles
        this against a recorded table so the escape cannot be taken silently.

    """
    return [model for model in first_party_models() if declares_not_evidence(model)]
