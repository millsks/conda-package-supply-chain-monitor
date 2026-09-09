"""What `core/permissions.py` decides, without a database and without a request.

`tests/unit/django_apps/test_permission_audit.py` asks whether the rule is declared
in one place and obeyed everywhere; this module asks whether the rule is *right*.
The three questions are the ones a role check gets wrong:

* **Who holds nothing.** Anonymous, unconfigured, and signed-in-but-in-no-group are
  three different states that all answer "no role", and only the last is a person.
  `EXPERIENCE.md`'s G-4 is that person -- a successful sign-in that reaches a wall --
  and a check that conflated them would refuse them with a log line saying nothing.
* **Who the factory will accept.** `requires_roles` refuses an empty set and an
  unknown name at *import*, because a class requiring a role nobody can hold refuses
  everybody, and a surface nobody can reach looks exactly like a surface nobody uses.
* **Whether a superuser walks through.** `CPM-AD-13` says not, at length, and the
  one-line version of the other decision is easy to reintroduce.

The group memberships are stubs rather than rows. `granted_roles` asks a user
exactly one question -- `groups.values_list("name", flat=True)` -- so a stub answers
it honestly and the real-user path is covered against a real database in
`tests/integration/django_apps/test_role_permissions.py`. What is gained is that
every state above is reachable here, including two the database makes awkward: a
deployment whose role contract is unset, and a `RoleContract` whose fields hold
whitespace.

No database, no network, no requests.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
import structlog

from conda_sentinel.core import permissions as core_permissions
from conda_sentinel.core.permissions import PRODUCT_ROLES
from conda_sentinel.core.permissions import REFUSAL_EVENT
from conda_sentinel.core.permissions import ROLE_CONTRACT_SETTING
from conda_sentinel.core.permissions import AnyProductRole
from conda_sentinel.core.permissions import RolePermission
from conda_sentinel.core.permissions import granted_roles
from conda_sentinel.core.permissions import requires_roles
from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER
from conda_sentinel.core.roles import RoleContract

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The group names this suite's `ROLE_CONTRACT` binds to the three slots, spelled
#: through the contract rather than as literals so a settings change is a failure
#: here rather than a silently unheld role.
A_REVIEWER_GROUP: Final[str] = "cpm-security-reviewer"
AN_ENGINEER_GROUP: Final[str] = "cpm-packaging-engineer"
A_LEADERSHIP_GROUP: Final[str] = "cpm-leadership"

#: The control event the capture below emits to prove it is live, on the terms
#: `captured_identity_service_logs` sets in `tests/conftest.py`: an assertion over
#: an empty list passes for the wrong reason, and a capture that cannot see the
#: module's logger produces exactly that.
CAPTURE_CONTROL: Final[str] = "permissions-capture-control"


def a_user(*groups: str, authenticated: bool = True) -> SimpleNamespace:
    """Return a stand-in answering the one question `granted_roles` asks.

    Args:
        *groups: The group names this user is a member of.
        authenticated: Whether the request carried a signed-in user.

    Returns:
        An object exposing `is_authenticated`, `username` and a `groups` manager
        whose `values_list` returns the names.

    """
    return SimpleNamespace(
        is_authenticated=authenticated,
        username="someone",
        groups=SimpleNamespace(values_list=lambda *_args, **_kwargs: list(groups)),
    )


def a_request(user: object, path: str = "/api/packages/") -> SimpleNamespace:
    """Return a stand-in request carrying a user and a path.

    Args:
        user: The acting user.
        path: What the refusal log should report as reached for.

    Returns:
        An object with the two attributes `has_permission` reads.

    """
    return SimpleNamespace(user=user, path=path)


class APackageHealthView:
    """A stand-in view, named so a refusal log has something to report."""


@pytest.fixture
def contract(settings: Any) -> RoleContract:
    """Return the role contract this suite configures, as the module reads it.

    Args:
        settings: pytest-django's settings fixture, which restores what it changes.

    Returns:
        The configured contract.

    """
    return getattr(settings, ROLE_CONTRACT_SETTING)


@pytest.fixture
def captured_logs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Capture what `core/permissions.py` logs, with the control guard.

    Args:
        monkeypatch: pytest's patcher, which restores the module's own logger.

    Yields:
        The captured events, in order, with the control event already cleared.

    """
    monkeypatch.setattr(core_permissions, "logger", structlog.get_logger(core_permissions.__name__))
    with structlog.testing.capture_logs() as captured:
        core_permissions.logger.warning(CAPTURE_CONTROL)
        assert [event["event"] for event in captured] == [CAPTURE_CONTROL], (
            "structlog.testing.capture_logs() cannot see core.permissions' logger, so every assertion "
            "over what it logged would be vacuous"
        )
        captured.clear()
        yield captured


# ---------------------------------------------------------------------------
# Which roles a user holds.
# ---------------------------------------------------------------------------


def test_the_configured_groups_are_the_ones_this_suite_names(contract: RoleContract) -> None:
    """The stubs below name group names, so the names have to be the configured ones.

    Without this the whole module could pass against a contract binding nothing:
    every membership stub would name a group no slot holds, every user would hold no
    role, and every refusal case would pass for a reason that is not the one it
    claims.
    """
    assert contract.security_reviewer == A_REVIEWER_GROUP
    assert contract.packaging_engineer == AN_ENGINEER_GROUP
    assert contract.leadership == A_LEADERSHIP_GROUP


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ((A_REVIEWER_GROUP,), {SECURITY_REVIEWER}),
        ((AN_ENGINEER_GROUP,), {PACKAGING_ENGINEER}),
        ((A_LEADERSHIP_GROUP,), {LEADERSHIP}),
        ((A_REVIEWER_GROUP, A_LEADERSHIP_GROUP), {SECURITY_REVIEWER, LEADERSHIP}),
        ((A_REVIEWER_GROUP, "some-unrelated-directory-group"), {SECURITY_REVIEWER}),
    ],
    ids=["reviewer", "engineer", "leadership", "two-roles", "and-a-group-no-slot-holds"],
)
def test_a_membership_becomes_the_role_its_slot_names(groups: tuple[str, ...], expected: set[str]) -> None:
    """A group name resolves to a slot, and a group no slot names resolves to nothing.

    The last case is the one worth having: a directory carries hundreds of groups
    this product has never heard of, and a user is a member of many of them.

    Args:
        groups: The user's memberships.
        expected: The role slots they should confer.

    """
    assert granted_roles(a_user(*groups)) == expected


@pytest.mark.parametrize(
    ("user", "why"),
    [
        (a_user(A_REVIEWER_GROUP, authenticated=False), "anonymous"),
        (a_user(), "signed in and in no group at all"),
        (a_user("some-unrelated-directory-group"), "signed in and in no group a slot names"),
    ],
    ids=["anonymous", "no-groups", "unrelated-groups"],
)
def test_holding_nothing_has_more_than_one_shape(user: SimpleNamespace, why: str) -> None:
    """Three states that all answer "no role", and the middle one is a real person.

    `EXPERIENCE.md`'s G-4 is that person: the sign-in succeeded, the platform's
    `IsAuthenticated` floor is satisfied, and every scoped surface still refuses. The
    answer is the same for all three and the *log line* is what distinguishes them,
    which is why the refusal records `held` as well as `required`.

    Args:
        user: The acting user.
        why: What state they are in, for the failure message.

    """
    assert granted_roles(user) == frozenset(), why


def test_an_anonymous_user_confers_nothing_even_carrying_the_group() -> None:
    """Authentication is read first, and it is not decoration.

    The stub deliberately carries a real reviewer group while reporting
    `is_authenticated=False`, which is the shape a naive check would let through:
    reading the memberships and never asking whether anybody signed in.
    """
    assert granted_roles(a_user(A_REVIEWER_GROUP, authenticated=False)) == frozenset()


def test_an_unconfigured_deployment_confers_nothing(settings: Any) -> None:
    """No contract means no role, and every scoped surface refuses.

    Correct for a component nobody has told who the reviewers are -- and visible
    rather than silent, because the refusal is logged. An `AttributeError` here would
    be a 500 instead, on a deployment whose only fault is an unset variable.

    Args:
        settings: pytest-django's settings fixture.

    """
    delattr(settings, ROLE_CONTRACT_SETTING)

    assert granted_roles(a_user(A_REVIEWER_GROUP)) == frozenset()


def test_a_contract_holding_whitespace_confers_nothing(settings: Any) -> None:
    """An unset variable reads as the empty string, and a blank one must read the same.

    Otherwise an empty slot name would match a group whose name is empty -- or worse,
    a `" "` from a block scalar in a ConfigMap would be a role name that a directory
    could be made to satisfy.

    Args:
        settings: pytest-django's settings fixture.

    """
    settings.ROLE_CONTRACT = RoleContract(security_reviewer="  ", packaging_engineer="", leadership="")

    assert granted_roles(a_user("", " ", "  ")) == frozenset()


# ---------------------------------------------------------------------------
# What a surface may declare.
# ---------------------------------------------------------------------------


def test_the_factory_refuses_a_class_requiring_nothing() -> None:
    """A permission class requiring no role refuses everybody, including the authorized.

    Refused where the class is built -- at import, on the module declaring the
    surface -- rather than at the first request.
    """
    with pytest.raises(ValueError, match=r"no role at all"):
        requires_roles()


def test_the_factory_refuses_a_role_the_contract_does_not_define() -> None:
    """The same failure with a different cause: a typo is a surface nobody can reach.

    And the message names the three that exist, because the person reading it has
    just misspelled one of them.
    """
    with pytest.raises(ValueError, match=r"security_reveiwer") as refusal:
        requires_roles("security_reveiwer")

    assert SECURITY_REVIEWER in str(refusal.value)


def test_the_factory_mints_a_class_a_traceback_can_read() -> None:
    """The name is not decoration: it is what a refused request's `view` field is beside.

    A factory returning eight classes all called `RolePermission` would make a DRF
    schema and a traceback equally uninformative.
    """
    minted = requires_roles(SECURITY_REVIEWER, LEADERSHIP)

    assert issubclass(minted, RolePermission)
    assert minted.required_roles == {SECURITY_REVIEWER, LEADERSHIP}
    assert minted.__name__ == "RequiresLeadershipSecurityReviewer"


def test_required_roles_is_an_any_rather_than_an_all() -> None:
    """A surface naming two roles and meaning "both" is a surface no one person reaches.

    No requirement in this product asks for one, and `AnyProductRole` -- which names
    all three -- would be unreachable if this were an *all*.
    """
    permission = requires_roles(SECURITY_REVIEWER, LEADERSHIP)()

    assert permission.has_permission(a_request(a_user(A_REVIEWER_GROUP)), APackageHealthView()) is True


def test_the_base_class_declares_no_role_and_no_surface_uses_it() -> None:
    """`RolePermission` itself refuses everybody, which is why the factory exists.

    Asserted rather than left implicit because the empty default is what makes a
    subclass that forgets `required_roles` fail closed.
    """
    assert RolePermission.required_roles == frozenset()
    assert RolePermission().has_permission(a_request(a_user(A_LEADERSHIP_GROUP)), APackageHealthView()) is False


# ---------------------------------------------------------------------------
# The check itself.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "groups",
    [(A_REVIEWER_GROUP,), (AN_ENGINEER_GROUP,), (A_LEADERSHIP_GROUP,)],
    ids=[SECURITY_REVIEWER, PACKAGING_ENGINEER, LEADERSHIP],
)
def test_a_read_surface_admits_every_one_of_the_three_roles(groups: tuple[str, ...]) -> None:
    """`CPM-AD-13` grants read access to evidence to all three, so all three pass.

    Args:
        groups: The one group this user holds.

    """
    assert AnyProductRole().has_permission(a_request(a_user(*groups)), APackageHealthView()) is True


def test_a_read_surface_still_refuses_somebody_holding_no_role() -> None:
    """Which is what makes `AnyProductRole` a check rather than a formality.

    The platform's `IsAuthenticated` floor admits this user; `CPM-AD-13`'s check is
    what does not.
    """
    assert AnyProductRole().has_permission(a_request(a_user()), APackageHealthView()) is False


def test_a_scoped_surface_refuses_a_role_it_did_not_name() -> None:
    """The leak the decision exists to prevent, stated as one case.

    A packaging engineer reaching a reviewer's queue is refused -- not by that view's
    own idea of a role, but by the one check.
    """
    reviewers_only = requires_roles(SECURITY_REVIEWER)()

    assert reviewers_only.has_permission(a_request(a_user(AN_ENGINEER_GROUP)), APackageHealthView()) is False


def test_a_superuser_is_not_exempt() -> None:
    """`CPM-AD-13`, argued in the module docstring and pinned here.

    Django's own admin checks `is_superuser` and it would be one line to do the same.
    A superuser browsing a queue is reading another role's work, which is the exact
    thing the decision names -- and unlike a group membership, a bypass is invisible
    to anybody auditing who can see what.
    """
    superuser = a_user()
    superuser.is_superuser = True
    superuser.is_staff = True

    assert AnyProductRole().has_permission(a_request(superuser), APackageHealthView()) is False


# ---------------------------------------------------------------------------
# The refusal record.
# ---------------------------------------------------------------------------


def test_a_refusal_is_logged_with_the_acting_user(captured_logs: list[dict[str, Any]]) -> None:
    """`CPM-AD-13`'s third clause: "a refused request is logged with the acting user identity".

    All five fields are asserted, because each answers a question the operator
    reading the alert has: who, on what surface, at what URL, needing what, holding
    what. `held` is the field that distinguishes G-4's zero-groups sign-in from a
    genuine attempt to reach another role's queue, and it is empty in exactly one of
    them.

    Args:
        captured_logs: What the module logged.

    """
    reviewers_only = requires_roles(SECURITY_REVIEWER)()

    assert reviewers_only.has_permission(a_request(a_user(AN_ENGINEER_GROUP)), APackageHealthView()) is False

    assert len(captured_logs) == 1
    assert captured_logs[0] == {
        "event": REFUSAL_EVENT,
        "log_level": "warning",
        "actor": "someone",
        "view": "APackageHealthView",
        "path": "/api/packages/",
        "required": [SECURITY_REVIEWER],
        "held": [PACKAGING_ENGINEER],
    }


def test_a_grant_is_not_logged(captured_logs: list[dict[str, Any]]) -> None:
    """Only refusals are recorded, and that is a decision about what an alert means.

    A log line per admitted request would put ten thousand entries a day beside the
    one an operator needs to see -- and the request itself is already recorded by the
    platform's access log.

    Args:
        captured_logs: What the module logged.

    """
    assert AnyProductRole().has_permission(a_request(a_user(A_LEADERSHIP_GROUP)), APackageHealthView()) is True

    assert captured_logs == []


def test_an_anonymous_refusal_names_a_actor_rather_than_raising(
    captured_logs: list[dict[str, Any]],
) -> None:
    """The refusal that must not become a 500.

    `AnonymousUser` has no `username`, and an unguarded read would raise inside the
    permission check -- turning the most common refusal there is into an error with
    no record of who was refused.

    Args:
        captured_logs: What the module logged.

    """
    anonymous = SimpleNamespace(is_authenticated=False)

    assert AnyProductRole().has_permission(a_request(anonymous), APackageHealthView()) is False

    assert len(captured_logs) == 1
    assert captured_logs[0]["actor"] == str(anonymous)
    assert captured_logs[0]["held"] == []


def test_the_required_roles_are_logged_sorted() -> None:
    """A set has no order, and an unordered field cannot be grepped or grouped.

    An operator counting refusals by what they required needs `["leadership",
    "packaging_engineer", "security_reviewer"]` to be one string every time rather
    than one of six.
    """
    assert sorted(AnyProductRole.required_roles) == sorted(PRODUCT_ROLES)
    assert sorted(AnyProductRole.required_roles) == [LEADERSHIP, PACKAGING_ENGINEER, SECURITY_REVIEWER]
