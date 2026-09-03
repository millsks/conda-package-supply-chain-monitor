"""The FR-17 authentication allowlist and AD-8's contributable surface: one declaration.

The nine refusal conditions are a denylist -- refuse these known-bad states --
and a denylist cannot by construction catch a credential path invented next
year. FR-17 inverts that: the component's authentication surface must match an
approved set *exactly*, so a path added later fails the build until somebody
adds it deliberately, which is the moment a human decides whether it belongs.

**One declaration, not two.** AD-26 is explicit that the FR-17 allowlist and
AD-8's permitted-contribution surface are the same declaration, "so adding a
credential path and adopting an app are checked by one mechanism rather than two
that can disagree". They are one file and one set of names here, and
`GOVERNED_SETTING_KEYS` is the mechanical join between the halves: every settings
key this allowlist governs is a key AD-8 refuses a contribution to. A future edit
that widened one half without the other fails
`tests/unit/startup/test_allowlist_declaration.py` rather than producing two
lists that quietly disagree.

**Where it lives, and why it is not the carrier.** `src/config/startup/` holds the
authoritative copy; Epic 7 adds a *mirror* in `accelerator.toml` with a gate test
asserting the two are equal (AD-26, the AD-20 precedent). The carrier is
`machinery` and never travels, while AD-8's composition step runs at settings
import inside a materialized component that does not have it -- so the carrier
cannot be the runtime authority for a rule that must execute there. Epic 9
extends this declaration; it never forks it.

**The rosters hold dotted paths, and the tests resolve them.** The skeleton this
module replaced declared them as resolved objects, on the reasoning that a string
comparison passes against a name that no longer resolves. The reasoning is right
and the location was not: `stage_one.py` found the same wall from the other side
-- resolving an authentication backend during settings composition raises
`AppRegistryNotReady` -- and AD-8's composition step will import this module at
exactly that moment. So the *declaration* holds strings, which are importable
everywhere, and the *test* resolves both sides and compares objects, which is
where the guarantee actually belongs.
`tests/unit/startup/test_authentication_allowlist.py` fails on a dotted path that
does not resolve, so nothing is lost by moving the resolution one layer out.

**Scoping is not the predicate.** `ALLOWED_AUTHENTICATION_ROUTE_SCOPES` says which
route prefixes the allowlist has authority over; the permitted view packages say
what may be routed there. AD-21 states the failure that separation exists for: "a
route named `local_persona_login` mounted under `/accounts/` would otherwise
satisfy this AD and pass an allowlist that already permits `/accounts/` for
allauth". Any implementation that allowlists a prefix and stops looking is wrong.
Business routes a developer adds fall under no scope and are not judged -- an
allowlist covering every route would break the build on the first feature anyone
wrote, and would be deleted within a week.

Nothing here imports Django, reads the environment, or resolves a dotted path at
module scope. The one prefix that is environment-parameterized -- the admin mount,
which `production.py` takes from `DJANGO_ADMIN_URL` -- names the setting it comes
from and is supplied by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from typing import cast

from config.local_dev.constants import LOCAL_SIGNIN_PATH_PREFIX

__all__ = [
    "ADMIN_ROUTE_PREFIX_SETTING",
    "ALLOWED_API_AUTHENTICATION_CLASSES",
    "ALLOWED_AUTHENTICATION_BACKENDS",
    "ALLOWED_AUTHENTICATION_ROUTE_PREFIXES",
    "ALLOWED_AUTHENTICATION_ROUTE_SCOPES",
    "CONTRIBUTABLE_KEYS",
    "FORBIDDEN_CONTRIBUTABLE_KEYS",
    "FRAMEWORK_VIEW_MACHINERY",
    "GOVERNED_SETTING_KEYS",
    "AuthenticationRouteScope",
]


# ---------------------------------------------------------------------------
# The settings-side surface.
# ---------------------------------------------------------------------------

#: The authentication backends a deployed component is permitted to install.
#:
#: Allauth's and nothing else: authentication is the identity provider's (FR-4).
#: `django.contrib.auth.backends.ModelBackend` is deliberately absent -- it is
#: stage 1's condition 2, state a -- and `base.py` no longer declares it, so the
#: base a deployed component inherits already matches this set. `local.py` and
#: `test.py` add it back for persona sign-in, which is the one place a local
#: username-and-password path is permitted and the one place stage 1 does not
#: look.
#:
#: Note that allauth's backend *is* a `ModelBackend` subclass. That is why the
#: refusal condition compares dotted paths rather than testing `issubclass`, and
#: why this roster does too: the two halves of the same fact, spelled the same
#: way, so neither can be satisfied by a spelling the other rejects.
ALLOWED_AUTHENTICATION_BACKENDS: Final[frozenset[str]] = frozenset(
    {
        "allauth.account.auth_backends.AuthenticationBackend",
    }
)

#: The DRF default authentication classes a component is permitted to install.
#:
#: The credential the provider issues, and the session its interactive flow
#: establishes. `rest_framework.authentication.TokenAuthentication` is absent for
#: the reason the whole static-token surface is gone (FR-6, Story 2.8): a token
#: minted locally is a credential the IdP does not own and cannot revoke.
ALLOWED_API_AUTHENTICATION_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "config.authorization.authentication.OIDCBearerAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    }
)

#: Which settings key each roster above is the approved contents of.
#:
#: This mapping is the join AD-26 asks for. Every value in it is required to be a
#: member of `FORBIDDEN_CONTRIBUTABLE_KEYS` below, which is the mechanical proof
#: that the FR-17 half and the AD-8 half cannot drift into contradiction: a key
#: whose contents FR-17 fixes exactly cannot also be a key an adopted app may
#: contribute to, because a contribution would be an entry FR-17 never approved.
GOVERNED_SETTING_KEYS: Final[dict[str, str]] = {
    "ALLOWED_AUTHENTICATION_BACKENDS": "AUTHENTICATION_BACKENDS",
    "ALLOWED_API_AUTHENTICATION_CLASSES": "DEFAULT_AUTHENTICATION_CLASSES",
}


# ---------------------------------------------------------------------------
# The route-side surface.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthenticationRouteScope:
    """One route prefix the allowlist has authority over, and what may be routed there.

    Attributes:
        key: A stable identifier for the scope, independent of the prefix so that
            an environment-parameterized prefix still has one name to refer to.
        permitted_view_packages: The packages whose modules may define a view
            routed under this prefix, as dotted paths. Matched against the
            *defining module* of the view callable -- exactly, or as a dotted
            prefix so any submodule counts -- which is the predicate
            `stage_two.py` already resolves views by. An empty set means the
            prefix is reserved: nothing may be routed there at all.
        why: One line on why this prefix is the component's own authentication
            surface. Carried in the record rather than in a comment beside it so
            that the mirror Epic 7 writes into `accelerator.toml` carries the
            reason with the rule.
        prefix: The literal route prefix, trailing slash included as `path()`
            writes it, or None when the prefix comes from a setting.
        prefix_setting: The settings key the prefix is read from, or None when it
            is a literal. Exactly one of `prefix` and `prefix_setting` is set.
        suffix: Appended to whichever of the two supplied the base. It exists for
            the admin mount, whose *location* is environment-parameterized while
            the credential routes beneath it are Django's own fixed names, so
            `ADMIN_URL` plus `login/` is one prefix built from a variable part
            and a fixed one rather than two declarations.

    """

    key: str
    permitted_view_packages: frozenset[str]
    why: str
    prefix: str | None = None
    prefix_setting: str | None = None
    suffix: str = ""

    def resolve_prefix(self, setting_values: dict[str, str]) -> str:
        """Return this scope's route prefix, reading a setting when it is parameterized.

        Args:
            setting_values: The settings this declaration names, by key. The
                caller supplies them so that nothing here imports
                `django.conf.settings` -- a module the AD-8 composition step will
                import during settings composition cannot read the settings it is
                helping to compose.

        Returns:
            The route prefix, trailing slash included.

        Raises:
            KeyError: When the scope names a setting the caller did not supply.
                Raised rather than defaulted: a missing admin URL would silently
                narrow the allowlist's scope to nothing, which is the failure
                mode an allowlist exists to prevent.

        """
        if self.prefix_setting is None:
            # `__post_init__` refuses a record declaring neither, so the literal is
            # present here. Cast rather than assert: an `assert` disappears under
            # `python -O`, and a raise would be a branch no input can reach, which
            # a reader would miscount as coverage.
            return cast("str", self.prefix) + self.suffix
        return setting_values[self.prefix_setting] + self.suffix

    def __post_init__(self) -> None:
        """Reject a record that names both a literal prefix and a setting, or neither.

        Raises:
            ValueError: When `prefix` and `prefix_setting` are not exactly one of
                the two. A record with both would have a prefix that ignores its
                setting; a record with neither would have no prefix at all and
                would silently judge nothing. `ValueError` rather than the refusal
                type because this module imports no Django and because a malformed
                record is a programming error in a literal, never a state any
                environment can produce -- see `OTHER_RAISE_ALLOWANCE` in
                `tests/unit/startup/test_no_softening.py`.

        """
        if (self.prefix is None) == (self.prefix_setting is None):
            message = f"scope {self.key!r} must declare exactly one of prefix and prefix_setting"
            raise ValueError(message)


#: The settings key the admin mount's prefix is read from. `base.py` defaults
#: `ADMIN_URL` to `admin/` and `production.py` takes it from `DJANGO_ADMIN_URL`,
#: so the prefix is genuinely environment-parameterized and a literal here would
#: be wrong in every component that moved it.
ADMIN_ROUTE_PREFIX_SETTING: Final[str] = "ADMIN_URL"

#: Django's own `as_view()` machinery, permitted under every scope.
#:
#: `stage_two._view_candidates` yields the `functools.wraps` chain beneath a
#: routed callable, and for every class-based view that chain includes the
#: `View.as_view.<locals>.view` closure, whose defining module is
#: `django.views.generic.base`. It is an artifact of how the walk recognizes
#: views rather than a view anybody routed, and it confers no credential path of
#: its own, so it is permitted everywhere rather than repeated in each scope.
FRAMEWORK_VIEW_MACHINERY: Final[frozenset[str]] = frozenset({"django.views.generic"})

#: The route prefixes the component itself owns for authentication, admin login
#: and token issuance -- and nothing else. Two of them are reserved rather than
#: populated, which is the point: a prefix with an empty permitted set fails on
#: anything mounted there, where an undeclared prefix would not be looked at.
#:
#: **The admin mount as a whole is deliberately not a scope.** `ADMIN_URL` carries
#: every installed app's `ModelAdmin` views -- `django_celery_beat.admin`,
#: `django.contrib.auth.admin`, the contenttypes shortcut, and whatever an adopted
#: app registers -- so a scope over the whole mount would have to permit a package
#: list that grew with `INSTALLED_APPS`, and would break the build on the first app
#: anyone adopted. That is AC #2's "an allowlist covering every route would be
#: deleted within a week", displaced one prefix down. What is in scope is admin
#: *login*, which is what AC #2 names and what is stable: two fixed routes beneath
#: a parameterized mount.
ALLOWED_AUTHENTICATION_ROUTE_SCOPES: Final[tuple[AuthenticationRouteScope, ...]] = (
    AuthenticationRouteScope(
        key="allauth",
        prefix="accounts/",
        permitted_view_packages=frozenset({"allauth"}),
        why=(
            "The identity provider's interactive flow. `config/urls.py` mounts `allauth.urls` here, "
            "which is the prefix AD-21's worked evasion exploits: permitting the prefix is not "
            "permitting everything mounted under it."
        ),
    ),
    AuthenticationRouteScope(
        key="admin-login",
        prefix_setting=ADMIN_ROUTE_PREFIX_SETTING,
        suffix="login/",
        permitted_view_packages=frozenset({"django.contrib.admin"}),
        why=(
            "Admin login. FR-7 forces it through allauth rather than Django's own credential form, "
            "and stage 1 refuses a deployed component where `DJANGO_ADMIN_FORCE_ALLAUTH` is not true; "
            "what this scope adds is that nothing else may be routed at the address the admin's own "
            "credential form occupies."
        ),
    ),
    AuthenticationRouteScope(
        key="admin-password-change",
        prefix_setting=ADMIN_ROUTE_PREFIX_SETTING,
        suffix="password_change/",
        permitted_view_packages=frozenset({"django.contrib.admin"}),
        why=(
            "The admin's own password-change form, which accepts a local credential and sets one. "
            "In scope for the same reason the login route is, and separately declared because it "
            "survives FR-7 forcing sign-in through the provider."
        ),
    ),
    AuthenticationRouteScope(
        key="local-sign-in",
        prefix=LOCAL_SIGNIN_PATH_PREFIX,
        permitted_view_packages=frozenset(),
        why=(
            "Reserved. The local persona sign-in module ships in every component and is mounted only "
            "where locality is local (AD-21, 'shipping is not mounting'), so a deployed component that "
            "routes anything here has a credential path the provider neither owns nor can revoke. "
            "The prefix is declared once in `config.local_dev.constants` and imported, never respelled."
        ),
    ),
    AuthenticationRouteScope(
        key="token-issuance",
        prefix="api/auth-token/",
        permitted_view_packages=frozenset(),
        why=(
            "Reserved. The prefix the reference application minted static tokens at before Story 2.8 "
            "deleted the route, the app and the class. Kept in scope with nothing permitted so that "
            "re-mounting the surface at the address it used to occupy fails here as well as at stage 2."
        ),
    ),
)

#: The literal prefixes among the scopes above, in declaration order.
#:
#: Derived rather than written out, so it cannot fall out of step with the scopes
#: it summarizes. The admin prefixes are absent by construction -- they are read
#: from `ADMIN_ROUTE_PREFIX_SETTING` and have no literal to list.
ALLOWED_AUTHENTICATION_ROUTE_PREFIXES: Final[tuple[str, ...]] = tuple(
    scope.prefix + scope.suffix for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES if scope.prefix is not None
)


# ---------------------------------------------------------------------------
# AD-8's contributable surface. Declared here; enforced by Epic 9.
# ---------------------------------------------------------------------------

#: The settings keys an adopted app may contribute to, by explicit key.
#:
#: AD-8 requires this to be "closed and enumerated by explicit key, never by
#: namespace", because a namespace is a rule that admits keys nobody has read.
#: Every entry here is a whole settings key, and
#: `tests/unit/startup/test_allowlist_declaration.py` fails on an entry that
#: looks like a prefix.
#:
#: `NAVIGATION_REGISTRY` is on the surface for a stated reason, and the reason
#: belongs beside it: it is the one contributable key rendered on every page, and
#: it is permitted where `MIDDLEWARE` and `AUTHENTICATION_BACKENDS` are refused
#: because **it confers presentation and never authorization**. An entry is data,
#: never markup -- a label, a URL *name*, and an optional permission the renderer
#: filters on -- labels are auto-escaped, and no entry carries raw HTML. It is
#: contributed to append-only in adopted-app-list order, exactly like
#: `INSTALLED_APPS`.
#:
#: An adopted app's *own* namespaced settings are not listed and are not omitted
#: by oversight: they are the app's own declaration site rather than a shared key
#: two apps could both write, so they are not what a closed list of shared keys
#: is about. Epic 9 Story 9.4 fixes their shape when the composition step exists.
CONTRIBUTABLE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "DATABASES",
        "DATABASE_ROUTERS",
        "INSTALLED_APPS",
        "NAVIGATION_REGISTRY",
        "CELERY_BEAT_SCHEDULE",
        "CELERY_IMPORTS",
        "CELERY_TASK_ROUTES",
    }
)

#: The global-default keys refused whether or not the base already sets them.
#:
#: AD-8 gives the reason directly: "introducing a new key is permitted" would
#: otherwise hand an adopted app authorization over every API request. These four
#: are refused as a class, not as a judgement about any particular app, and the
#: two the FR-17 rosters govern are here by requirement rather than by
#: coincidence -- see `GOVERNED_SETTING_KEYS`.
FORBIDDEN_CONTRIBUTABLE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "AUTHENTICATION_BACKENDS",
        "DEFAULT_AUTHENTICATION_CLASSES",
        "DEFAULT_PERMISSION_CLASSES",
        "MIDDLEWARE",
    }
)
