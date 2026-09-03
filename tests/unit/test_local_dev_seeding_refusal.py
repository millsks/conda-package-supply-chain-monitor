"""The deployed-environment refusal, asserted before any database work happens.

AC #4: invoked in a deployed environment, seeding raises the same
`ImproperlyConfigured` the refusal contract uses and never creates a local
account there. The second half is what this module is really about -- an
implementation that refused *after* provisioning the groups, or after resolving
the first persona, would satisfy a test that only caught the exception while
having already written to a production database.

So the provisioning callable and both mapper operations are replaced by spies,
and the assertion is that none of them was reached. No database is touched here
by construction: if the refusal ever stopped firing, the spies would record a
call and the test would fail rather than quietly reaching for a connection.

Locality is read from `os.environ` at call time (`config.locality`), so
`monkeypatch.setenv` is enough and no module has to be reloaded. The suite runs
in the `dev` pixi environment, which declares `COMPONENT_RUNTIME=local`, which is
why every case below sets or deletes the variable explicitly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.authorization.mapper import SyncOutcome
from config.local_dev import seeding
from config.local_dev.personas import PERSONAS
from config.locality import RUNTIME_ENV_VAR

if TYPE_CHECKING:
    from collections.abc import Mapping

# Every value that is not the one recognized declaration. `dev` and `""` are the
# two most likely near-misses: a platform setting a generic `ENV=dev` for a
# development *deployment*, and a variable declared but never given a value.
DEPLOYED_VALUES = ("production", "dev", "", "Production", "1", "true")


class _Spy:
    """Records that it was called, and with what, without doing any of the work."""

    def __init__(self, result: Any = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.result = result

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(args)
        return self.result


class _StubGroups:
    """The one queryset method the seeding event reads off a user."""

    def values_list(self, *_fields: str, **_options: Any) -> list[str]:
        """Return the group names, of which a stub has none."""
        return []


class _StubUser:
    """A resolved user, with only the attributes the seeding event reads."""

    pk = 1
    idp_subject = "stub"
    groups = _StubGroups()


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> dict[str, _Spy]:
    """Replace every side-effecting call `seed_personas` makes with a spy.

    Returns:
        The spies, by the name they replaced in the seeding module.
    """
    replacements = {
        "provision_designated_groups": _Spy(),
        "resolve_user": _Spy(result=_StubUser()),
        "sync_for_interactive": _Spy(result=SyncOutcome()),
    }
    for name, spy in replacements.items():
        monkeypatch.setattr(seeding, name, spy)
    return replacements


@pytest.mark.parametrize("declared", DEPLOYED_VALUES)
def test_seeding_refuses_when_the_runtime_is_not_local(
    monkeypatch: pytest.MonkeyPatch,
    spies: dict[str, _Spy],
    declared: str,
) -> None:
    """AC #4: anything that is not the one declaration is deployed, and refused."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, declared)
    with pytest.raises(ImproperlyConfigured):
        seeding.seed_personas()
    assert not any(spy.calls for spy in spies.values())


def test_seeding_refuses_when_the_runtime_is_undeclared(
    monkeypatch: pytest.MonkeyPatch,
    spies: dict[str, _Spy],
) -> None:
    """Locality fails closed: an absent declaration is deployed, not local.

    This is the case a lost declaration produces, and it is the one that has to
    refuse -- a default of "local when unset" would disarm every refusal built on
    locality the moment the variable failed to reach the process.
    """
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    with pytest.raises(ImproperlyConfigured):
        seeding.seed_personas()
    assert not any(spy.calls for spy in spies.values())


def test_the_refusal_names_the_variable_an_operator_has_to_look_at(
    monkeypatch: pytest.MonkeyPatch,
    spies: dict[str, _Spy],
) -> None:
    """The one thing the exception cannot be inferred from is which declaration was missing."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")
    with pytest.raises(ImproperlyConfigured, match=RUNTIME_ENV_VAR):
        seeding.seed_personas()
    assert not any(spy.calls for spy in spies.values())


def test_the_refusal_fires_before_the_group_provisioning(
    monkeypatch: pytest.MonkeyPatch,
    spies: dict[str, _Spy],
) -> None:
    """AC #4's "never creates a local account there", stated at its first opportunity.

    Provisioning is the second statement of `seed_personas` and it writes rows.
    A refusal placed after it would have already modified a production database
    by the time the exception left the function.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")
    with pytest.raises(ImproperlyConfigured):
        seeding.seed_personas()
    assert spies["provision_designated_groups"].calls == []


def test_a_local_run_reaches_every_step(
    monkeypatch: pytest.MonkeyPatch,
    spies: dict[str, _Spy],
) -> None:
    """The non-vacuity guard for this module.

    Every assertion above is that something did *not* happen, so a
    `seed_personas` that raised unconditionally -- or one whose spies were
    patched onto the wrong names -- would pass all of them while checking
    nothing. This is the same call with locality declared, and it must reach the
    provisioning and both mapper operations, once per declared persona.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, "local")
    assert seeding.seed_personas() == [persona.key for persona in PERSONAS]
    assert len(spies["provision_designated_groups"].calls) == 1
    assert len(spies["resolve_user"].calls) == len(PERSONAS)
    assert len(spies["sync_for_interactive"].calls) == len(PERSONAS)


def test_the_provisioning_is_called_with_the_live_registry(
    monkeypatch: pytest.MonkeyPatch,
    spies: dict[str, _Spy],
) -> None:
    """AD-27: called with no argument, so it uses the live app registry.

    Its `apps` parameter is the seam that lets one body serve the data migration
    and every runtime caller. Passing a registry from here would be this module
    deciding something only a migration knows.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, "local")
    seeding.seed_personas()
    assert spies["provision_designated_groups"].calls == [()]


def test_the_mapper_receives_the_payload_build_claims_produced(
    monkeypatch: pytest.MonkeyPatch,
    spies: dict[str, _Spy],
) -> None:
    """Resolve and sync see one and the same claims mapping, per persona.

    Two payloads built separately is how the identity a user resolves by and the
    groups it is synced with drift apart -- the user would be resolved from one
    payload and authorized from another.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, "local")
    seeding.seed_personas()
    resolved: list[Mapping[str, Any]] = [call[0] for call in spies["resolve_user"].calls]
    synced: list[Mapping[str, Any]] = [call[1] for call in spies["sync_for_interactive"].calls]
    assert [id(claims) for claims in resolved] == [id(claims) for claims in synced]
