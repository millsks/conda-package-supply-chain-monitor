"""The allauth seam: an interactive sign-in, resolved and synced by the mapper.

AD-11 is the whole design of this module: "the allauth adapter resolves through
the mapper too; `SocialAccount` is bookkeeping, not authority." So what lives
here is a translation, not a decision. The adapter reads the claims the provider
returned, hands them to `config.authorization.mapper`, and connects allauth's
bookkeeping to whichever user the mapper chose. Every question about *who this
is* and *what they may do* is answered in one place, and it is not this one.

**Why `pre_social_login` and not `populate_user`.** `populate_user` runs only
when allauth is instantiating a *new* user, so authorization placed there would
be applied once, at first sighting, and never again -- a person's access at the
IdP could change every day and the component would never notice.
`pre_social_login` runs on every social login, which is the frequency AD-10
assigns to an interactive credential epoch. Story 2.5 AC #5 states the rule; this
is where it lands in code.

**Why it lives in `config` rather than in `django_service`.** AD-4 lets `config`
import `django_service` and forbids the reverse. The adapter must call the
mapper, and the mapper is this package's, so an adapter under `django_service`
could not reach it. AD-29 permits the move: `django_service` is `core` in its
entirety, but anything inside it that is not enumerated as guaranteed surface is
internal and may move without a version bump.

**A refusal has no 401 to return here.** The interactive flow is a browser
redirect chain, so `ClaimsRejected` becomes an `ImmediateHttpResponse` carrying
403 -- allauth's own way for an adapter to stop the flow and answer directly.
The Bearer path answers 401 instead, and that translation is Story 2.7's; the
mapper itself raises a protocol-free exception precisely so the two can differ.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import structlog
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.http import HttpResponseForbidden

from config.authorization.exceptions import ClaimsRejected
from config.authorization.mapper import resolve_user
from config.authorization.mapper import sync_for_interactive

if TYPE_CHECKING:
    from collections.abc import Mapping

    from allauth.socialaccount.models import SocialLogin
    from django.http import HttpRequest
    from django.http import HttpResponse

__all__ = ["OIDCSocialAccountAdapter", "claims_from"]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: The two envelopes allauth's OIDC provider puts the claims inside. Its
#: `complete_login` builds `{"userinfo": ..., "id_token": ...}` and stores that
#: as `extra_data`, so the claims are one level down rather than at the top --
#: reading `extra_data` flat would find no identity key at all against a real
#: IdP. Ordered so the userinfo document wins a disagreement, which is the
#: precedence allauth's own provider applies, while claims the ID token carries
#: alone still survive: an IdP is free to assert the group claim in only one of
#: the two, and dropping either would refuse every sign-in at that IdP.
_ID_TOKEN_ENVELOPE = "id_token"  # noqa: S105 - an envelope key in a dict, not a credential
_USERINFO_ENVELOPE = "userinfo"

#: What the browser is told when the mapper refuses. Deliberately says nothing
#: about *which* refusal: the reason is a log field, and a claim value or a
#: configured claim name rendered into a page is the token's contents leaking to
#: whoever triggered the refusal.
_REFUSAL_BODY = "Sign-in was refused."


def claims_from(sociallogin: SocialLogin) -> Mapping[str, Any]:
    """Read the claims an interactive login carried, out of allauth's envelopes.

    Shape only -- this makes no decision about identity or access and must never
    grow one. Its whole job is that `extra_data` for the `openid_connect`
    provider is a two-key envelope rather than the claims themselves.

    Args:
        sociallogin: The login allauth is part-way through completing. Read-only;
            nothing here mutates it or its account.

    Returns:
        The claims as a flat mapping. The ID token's claims overlaid by the
        userinfo document's, so neither source is lost and userinfo wins a
        disagreement. When neither envelope is present -- a provider that stores
        the claims flat, and every hand-built `SocialLogin` in the test suite --
        `extra_data` is returned as it stands.

    """
    extra_data: Mapping[str, Any] = getattr(sociallogin.account, "extra_data", None) or {}
    envelopes = [extra_data.get(name) for name in (_ID_TOKEN_ENVELOPE, _USERINFO_ENVELOPE)]
    present = [envelope for envelope in envelopes if isinstance(envelope, dict)]
    if not present:
        return extra_data
    flattened: dict[str, Any] = {}
    for envelope in present:
        flattened.update(envelope)
    return flattened


# django-allauth ships no `py.typed` marker and no stub package exists for it on
# conda-forge, so `ignore_missing_imports` resolves every allauth name to `Any`
# and strict mode refuses the subclass. The base classes are real; only their
# types are missing upstream. `warn_unused_ignores` removes this the moment
# allauth starts publishing types.
class OIDCSocialAccountAdapter(DefaultSocialAccountAdapter):  # type: ignore[misc]
    """Route every interactive sign-in through the one mapper (AD-11)."""

    def is_open_for_signup(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
    ) -> bool:
        """Report whether registration through a social provider is permitted.

        Args:
            request: The request asking to sign up.
            sociallogin: The provider login being completed.

        Returns:
            The value of the ``ACCOUNT_ALLOW_REGISTRATION`` setting.

        """
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def pre_social_login(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
    ) -> None:
        """Resolve the login through the mapper and attach allauth's bookkeeping to it.

        Runs on every social login, before allauth decides whether it is looking
        at a signup or a sign-in -- which is what makes the mapper the authority
        rather than a first-sighting hook.

        Args:
            request: The callback request the provider redirected to.
            sociallogin: The login allauth is completing. Its account is
                connected to the user the mapper chose, so allauth's
                `SocialAccount` row records what happened rather than deciding
                it.

        Raises:
            ImmediateHttpResponse: The mapper refused the claims. Interactive
                sign-in has no 401 to answer with, so the refusal leaves as a
                403 and allauth returns it without completing the login.

        """
        claims = claims_from(sociallogin)
        try:
            user = resolve_user(claims)
            sync_for_interactive(user, claims)
        except ClaimsRejected as refusal:
            # Handled and reported, never swallowed. `reason` is the mapper's
            # own refusal string and carries no claim value; the person is told
            # nothing beyond "refused" (see `_REFUSAL_BODY`).
            logger.warning("authorization.interactive_login_refused", reason=refusal.reason)
            raise ImmediateHttpResponse(self.refusal_response(request)) from refusal
        sociallogin.connect(request, user)

    def refusal_response(self, request: HttpRequest) -> HttpResponse:
        """Build the response a refused interactive sign-in is answered with.

        A method rather than a literal so a deployment that wants a branded page
        or a redirect can override it without reimplementing the hook above --
        and so overriding it cannot accidentally change *when* a refusal happens.

        Args:
            request: The callback request being refused. Unused here; it is what
                an override would render against.

        Returns:
            A 403. Not a redirect back to the login route, which would send the
            browser round the provider again and answer a permanent refusal with
            an endless loop.

        """
        return HttpResponseForbidden(_REFUSAL_BODY)
