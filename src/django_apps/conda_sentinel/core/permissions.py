"""`CPM-AD-13`: every surface declares the role it needs, and one implementation checks it.

`CPM-FR-31` scopes what each of the three roles may reach, and the failure the
decision exists to prevent is stated plainly: "each view inventing its own role
check, so a queue leaks to the wrong role". A per-view `if request.user.groups...`
is right eight times and wrong once, and the once is a queue another role can read.

So a surface *declares* and this module *decides*. A view names the roles it
requires through one of the classes below; `has_permission` is written once, here;
and a refusal is logged, once, here, with the acting user's identity.

**Declaring is not optional, and "no declaration" is not "open".** The platform
installs `IsAuthenticated` as the global default, which is a floor rather than an
answer: it says somebody is signed in and nothing about what they may see. A view
that declares no product permission is therefore reachable by any authenticated
user, which is exactly the leak `CPM-AD-13` is about --
`tests/unit/django_apps/test_permission_audit.py` sweeps every registered view for
one of these classes and fails a view that declares none.

**Read is shared and write is scoped, which is why the common class is the
permissive one.** `CPM-AD-13` grants read access to evidence to all three roles, and
the UX contract reaches the same conclusion for the nav: "every surface in the flat
nav is readable by all three roles... role scoping happens *below* the nav -- at the
deep queue URL, at the item, and at the transition." So `AnyProductRole` is what a
read surface declares, and it is a real check rather than a formality: it refuses an
authenticated user who holds *none* of the three roles, which is a real state --
`EXPERIENCE.md`'s G-4 is the zero-groups sign-in -- and one `IsAuthenticated` alone
would let through.

**A role is a group membership, and the group names are the operator's.**
`core/roles.py` reads them from the environment into a `RoleContract` because the
platform's claims contract owns the mapping from an identity provider's claim to a
Django group. Nothing here hard-codes a group name; a deployment that has not
configured the contract has no members of anything, and every scoped surface refuses
-- which is the correct behaviour for a component nobody has told who the reviewers
are, and is visible rather than silent because the refusal is logged.

**Superusers are not exempt, and that is deliberate.** Django's own admin checks
`is_superuser`, and it would have been one line to do the same here. `CPM-FR-31` is
about which *role* may see which surface, and a superuser browsing a queue is
reading another role's work -- the exact thing the decision names. An operator who
needs to see a queue joins the group that confers it, which is a change somebody can
audit; a superuser bypass is one nobody can see. `CPM-AD-14`'s override permission is
a separate question and stays where Django's permission system already puts it.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Final

import structlog
from django.conf import settings
from rest_framework.permissions import BasePermission

from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.core.roles import PACKAGING_ENGINEER
from conda_sentinel.core.roles import SECURITY_REVIEWER

if TYPE_CHECKING:
    from django.http import HttpRequest
    from rest_framework.views import APIView

__all__ = [
    "PRODUCT_ROLES",
    "REFUSAL_EVENT",
    "ROLE_CONTRACT_SETTING",
    "AnyProductRole",
    "RolePermission",
    "granted_roles",
    "requires_roles",
]

logger = structlog.get_logger(__name__)

#: The event a refusal is logged under, dotted as every event in this product is.
#:
#: `CPM-AD-13` requires that "a refused request is logged with the acting user
#: identity", and naming the event here is what lets
#: `tests/integration/django_apps/test_role_permissions.py` assert the log rather
#: than assert that a log call happened. An operator alerting on authorization
#: failures queries this one string.
REFUSAL_EVENT: Final[str] = "authorization.refused"

#: The settings key holding the `RoleContract` the platform composed.
#:
#: Spelled once, here, because the refusal below and the read must name the same
#: thing -- and because a settings module that dropped the assignment must produce a
#: refusal naming the setting rather than an `AttributeError` naming nothing.
ROLE_CONTRACT_SETTING: Final[str] = "ROLE_CONTRACT"

#: The three roles a surface may require, by the slot name `core/roles.py` gives
#: each. Built from that module's own constants rather than written out, so a
#: renamed role fails at import here rather than becoming a requirement nothing can
#: satisfy.
PRODUCT_ROLES: Final[tuple[str, ...]] = (SECURITY_REVIEWER, PACKAGING_ENGINEER, LEADERSHIP)


def granted_roles(user: object) -> frozenset[str]:
    """Return which of the three product roles a user holds.

    The one place a group membership becomes a role, so a caller never compares a
    group name itself -- which is what would hard-code an operator's naming into a
    view.

    Args:
        user: The acting user, as the request carries it. Typed loosely because an
            unauthenticated request carries `AnonymousUser`, which is not the user
            model and answers the same questions.

    Returns:
        The role slot names this user holds. Empty for an anonymous user, for a
        deployment whose role contract is unconfigured, and for a signed-in user in
        none of the three groups -- three different states that are all "holds no
        role", and are distinguished by the refusal's log rather than by this
        answer.

    """
    contract = getattr(settings, ROLE_CONTRACT_SETTING, None)
    if contract is None or not getattr(user, "is_authenticated", False):
        return frozenset()
    held = set(user.groups.values_list("name", flat=True))  # type: ignore[attr-defined]
    return frozenset(role for role in PRODUCT_ROLES if (name := getattr(contract, role, "").strip()) and name in held)


class RolePermission(BasePermission):
    """The one implementation of `CPM-AD-13`'s check.

    A subclass declares `required_roles` and nothing else. The comparison, the
    refusal and the log line are here, once -- which is the whole of what the
    decision asks for.

    **`required_roles` is an *any* rather than an *all*.** A surface that named two
    roles and meant "both" would be a surface no single person could reach, and no
    requirement in this product asks for one. Read surfaces name all three; the deep
    queue URLs `CPM-APP-S05` builds name one each.
    """

    #: The roles that may reach the surface this class is declared on. Empty on the
    #: base, which no surface declares: `requires_roles` mints the subclasses and
    #: refuses an empty set, so a class reaching a view always names somebody.
    required_roles: ClassVar[frozenset[str]] = frozenset()

    def has_permission(self, request: HttpRequest, view: APIView) -> bool:
        """Report whether the acting user holds a role this surface accepts.

        Args:
            request: The request being authorized.
            view: The view it is bound for, named in the refusal so an operator
                reading the log knows which surface was reached for.

        Returns:
            `True` when the user holds any required role.

        """
        held = granted_roles(request.user)
        if held & self.required_roles:
            return True
        logger.warning(
            REFUSAL_EVENT,
            # `CPM-AD-13`: "logged with the acting user identity". The username
            # rather than the primary key, because an operator reading this is
            # about to go and ask somebody a question -- and `str()` so an
            # anonymous request logs `AnonymousUser` rather than raising.
            actor=str(getattr(request.user, "username", request.user)),
            view=type(view).__name__,
            path=request.path,
            required=sorted(self.required_roles),
            held=sorted(held),
        )
        return False


def requires_roles(*roles: str) -> type[RolePermission]:
    """Return a permission class requiring any of these roles.

    A factory rather than eight hand-written subclasses, because the subclass is one
    line of data and writing it out is how one of them comes to differ. The class it
    mints carries a name a traceback and a DRF schema can read.

    Args:
        *roles: The role slot names, from `PRODUCT_ROLES`.

    Returns:
        A `RolePermission` subclass declaring them.

    Raises:
        ValueError: When no role is named, or a name is not one of the three.
            Refused where the class is built -- at import, on the module declaring
            the surface -- rather than at the first request, because a permission
            class requiring a role that does not exist refuses *everybody*, and a
            surface nobody can reach looks exactly like a surface nobody uses.

    """
    named = frozenset(roles)
    if not named:
        message = (
            "a permission class was asked to require no role at all, which would refuse every request "
            "including a fully authorized one. A surface readable by every role declares AnyProductRole; "
            "CPM-AD-13 has no third state."
        )
        raise ValueError(message)
    unknown = sorted(named - set(PRODUCT_ROLES))
    if unknown:
        message = (
            f"a permission class was asked to require {unknown}, which core/roles.py does not define. The "
            f"roles are {list(PRODUCT_ROLES)}; a class requiring anything else refuses every request, and a "
            f"surface nobody can reach looks exactly like a surface nobody uses."
        )
        raise ValueError(message)
    return type(
        f"Requires{''.join(role.title().replace('_', '') for role in sorted(named))}",
        (RolePermission,),
        {"required_roles": named},
    )


#: What a read surface declares: any of the three roles.
#:
#: `CPM-AD-13` grants read access to evidence to all three, so this is the common
#: case and not a weakening of anything. It still refuses -- an authenticated user in
#: none of the three groups is a real state (the zero-groups sign-in) and one the
#: platform's `IsAuthenticated` floor lets straight through.
AnyProductRole: Final[type[RolePermission]] = requires_roles(*PRODUCT_ROLES)
