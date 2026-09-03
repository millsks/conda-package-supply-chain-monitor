"""The Bearer credential: a DRF authentication class over PyJWT and the key store.

FR-5 asks for "a DRF `BaseAuthentication` subclass validating
`Authorization: Bearer <JWT>` against JWKS, verifying signature, `iss`, `aud` and
`exp`, with lazy retrieval and `kid`-keyed caching". This is that class, and it is
deliberately thin: `jwks.KEY_STORE` owns every question about key material and
`mapper` owns every question about identity and access. What is left here is the
translation between a JWT and those two, plus turning any refusal into DRF's 401.

**No mapping logic of its own.** AD-10 assigns `resolve_user` to every
authentication and `sync_once_per_epoch` to the first sighting of a `jti`, and
this class calls exactly those two in that order. It reads no group claim, sets
neither of the two flags the claims confer, derives no username and decides no
sync frequency. The `jti` rule has one home: a token with no `jti` arrives here as a
`ClaimsRejected` from `sync_once_per_epoch` and is translated like any other
refusal. Re-checking it here would be a second copy of a security rule, and two
copies is one that can be written without.

**Algorithms come from configuration, never from the token.** `ALGORITHMS` is an
explicit allowlist. Taking `alg` from the token's own header is the `alg=none`
and algorithm-confusion family of attacks, in which the attacker chooses how
their signature is checked.

**R-2, recorded here so it is not mistaken for an oversight.** Bearer revocation
latency is the token's lifetime: AD-10 syncs once per `jti`, so a group revoked
at the IdP is honoured until the token expires. Nothing in this class shortens
that window and nothing should try. A shorter TTL on the JWKS cache has no effect
on it -- that governs key material, not authorization -- and a per-request
re-sync reintroduces exactly the `auth_user_groups` write amplification AD-10
exists to prevent. Token lifetime is the IdP's policy lever.

**Why `authenticate_header` is not optional.** DRF answers 403 rather than 401
when no authenticator offers a `WWW-Authenticate` challenge. Without the method
below, every acceptance criterion in this story that says "rejected with 401"
would be answered with 403 instead, and the class would look correct from the
inside.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import jwt
import structlog
from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from jwt.exceptions import DecodeError
from jwt.exceptions import ExpiredSignatureError
from jwt.exceptions import InvalidAlgorithmError
from jwt.exceptions import InvalidAudienceError
from jwt.exceptions import InvalidIssuerError
from jwt.exceptions import InvalidKeyError
from jwt.exceptions import InvalidSignatureError
from jwt.exceptions import InvalidTokenError
from jwt.exceptions import MissingRequiredClaimError
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from config.authorization.exceptions import ClaimsRejected
from config.authorization.exceptions import JWKSKeyUnavailable
from config.authorization.jwks import KEY_STORE
from config.authorization.mapper import resolve_user
from config.authorization.mapper import sync_once_per_epoch

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rest_framework.request import Request

    from django_service.users.models import User

__all__ = ["OIDCBearerAuthentication", "OIDCBearerScheme"]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: The scheme this class answers to, compared case-insensitively as RFC 7235
#: requires, and the value of the `WWW-Authenticate` challenge.
_SCHEME: Final = "Bearer"

#: The signature algorithms accepted when none is configured. RS256 alone: it is
#: what the overwhelming majority of IdPs sign with, and an allowlist that
#: guesses wide is an allowlist that admits an algorithm nobody chose.
_DEFAULT_ALGORITHMS: Final[tuple[str, ...]] = ("RS256",)

#: The claims a token must carry to be considered at all. `exp` so an unbounded
#: credential is impossible, `iss` and `aud` so the two checks AC #1 names cannot
#: pass vacuously -- PyJWT verifies an *absent* `aud` against nothing unless it
#: is required, which would admit a token minted for another audience that simply
#: omitted the claim.
_REQUIRED_CLAIMS: Final[list[str]] = ["exp", "iss", "aud"]

#: Every PyJWT verdict that means "this token is not acceptable", each named
#: rather than caught as a base class alone. `InvalidTokenError` closes **its own
#: subtree** -- it is PyJWT's root for a *verdict about the token*, so a version
#: that adds a subclass of it still lands on a 401 rather than escaping as a 500.
#: It does not close the set of things PyJWT raises: `InvalidKeyError` is a
#: `PyJWTError` sibling outside that subtree, and `_KEY_UNUSABLE` below carries
#: the rest. Each is a named type, not a bare `except`, and nothing here is
#: silently swallowed -- every arrival is logged with its concrete class name.
_TOKEN_REFUSED: Final = (
    ExpiredSignatureError,
    InvalidIssuerError,
    InvalidAudienceError,
    InvalidSignatureError,
    InvalidAlgorithmError,
    MissingRequiredClaimError,
    DecodeError,
    InvalidTokenError,
)

#: What a *key* that cannot verify *this* token raises, which is a refusal too.
#: An allowlist naming two algorithm families -- `RS256,ES256` is a supported
#: value of `COMPONENT_OIDC_ALGORITHMS` -- hands `jwt.decode` a published RSA key
#: and a token signed with the other family; PyJWT's key preparation then raises
#: a bare `TypeError` on current versions and `InvalidKeyError` on older ones.
#: Neither is under `InvalidTokenError`, so without these the mismatch escapes as
#: an unauthenticated 500 with a traceback and no refusal event. It is a verdict
#: about a presented credential, so it is a 401 like every other.
_KEY_UNUSABLE: Final = (InvalidKeyError, TypeError)

#: The two together, named once so the `except` around `jwt.decode` reads as the
#: single "this credential is refused" set it is.
_DECODE_REFUSED: Final = (*_TOKEN_REFUSED, *_KEY_UNUSABLE)

#: What a refused caller is told. Deliberately uniform across every refusal: the
#: reason is a log field, and telling an unauthenticated caller which of
#: signature, issuer, audience or expiry failed is a verification oracle.
_REFUSAL_DETAIL: Final = "Invalid or expired bearer token."

#: The refusal reasons this module names itself. PyJWT's and the mapper's own
#: reasons arrive as strings and are logged as they come.
_MALFORMED_HEADER: Final = "authorization header is not a single bearer token"
_NO_KID: Final = "token header carries no kid"

#: How much of a `kid` reaches the log field. The value is attacker-supplied and
#: unbounded -- the mapper next door refuses an over-long identity key for exactly
#: that reason -- and a refusal event is written on an unauthenticated path, so a
#: caller could otherwise put a megabyte of their choosing into every line.
#: Truncated rather than refused: unlike an identity key, this is a log field and
#: not a value anything is decided on, and a token whose `kid` is merely long is
#: already refused by the key store on its merits.
_MAX_LOGGED_KID: Final = 64


class OIDCBearerAuthentication(BaseAuthentication):
    """Verify an `Authorization: Bearer <JWT>` credential against the IdP's JWKS."""

    def authenticate(self, request: Request) -> tuple[User, Mapping[str, Any]] | None:
        """Verify the request's Bearer credential and resolve it to a user.

        Args:
            request: The request being authenticated.

        Returns:
            The user and the verified claims, or None when this request carries
            no Bearer credential for this class to decide. None rather than a
            raise is load-bearing: it is what lets DRF fall through to
            `SessionAuthentication`, and a raise here would refuse every
            session-authenticated request in the component.

        Raises:
            AuthenticationFailed: The credential is present and not acceptable.
                DRF renders this as 401 -- given `authenticate_header` below --
                for every cause alike: a bad signature, a wrong `iss` or `aud`,
                an expired `exp`, an algorithm outside the allowlist, a `kid` no
                key is available for, and every refusal the mapper raises,
                including Story 2.5's missing-`jti` rule and this story's
                deactivated user.

        """
        token = _bearer_token(request)
        if token is None:
            return None

        kid = self._kid(token)
        claims = self._verified_claims(token, kid)
        return self._authorized(claims, kid)

    def authenticate_header(self, request: Request) -> str:
        """Return the `WWW-Authenticate` challenge for a refused request.

        Without this DRF answers 403 rather than 401, because it looks for a
        challenge from the first authenticator and falls back to "forbidden" when
        none offers one. Every "rejected with 401" in this story depends on it.

        Args:
            request: The request being refused. Unused; the challenge is the same
                for every caller, because varying it would tell an
                unauthenticated caller something about itself.

        Returns:
            The scheme name.

        """
        return _SCHEME

    def _kid(self, token: str) -> str:
        """Read the key identifier from the token's unverified header.

        Unverified is not a weakness: the `kid` selects which *published public*
        key the signature is checked against, and a wrong one fails that check a
        line later. Nothing is trusted on the strength of it.

        Args:
            token: The bearer token as presented.

        Returns:
            The `kid` the header declares, stripped. Stripped rather than
            returned as presented: the validation below already reads
            `kid.strip()`, so a padded value that passed it would then miss the
            cache under its padded form and provoke a refetch on every request
            inside the window -- which is the amplification the rate limit exists
            to bound, reached by a route it does not see.

        Raises:
            AuthenticationFailed: The header is unreadable or declares no usable
                `kid`. A token without one cannot be matched to a published key
                at all, so it is refused rather than checked against every key in
                the set -- which would turn one request into N signature
                verifications, at the caller's choosing.

        """
        try:
            header = jwt.get_unverified_header(token)
        except _TOKEN_REFUSED as refusal:
            raise _refused(type(refusal).__name__, kid=None) from refusal
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid.strip():
            raise _refused(_NO_KID, kid=None)
        return kid.strip()

    def _verified_claims(self, token: str, kid: str) -> Mapping[str, Any]:
        """Verify signature, `iss`, `aud` and `exp`, and return the claims.

        Args:
            token: The bearer token as presented.
            kid: The key identifier its header declared.

        Returns:
            The decoded claims, every one of them verified.

        Raises:
            AuthenticationFailed: No key is available for the `kid`, the token
                fails any one of the four checks, or the key the `kid` names
                cannot verify a signature of the algorithm the token carries.

        """
        try:
            key = KEY_STORE.get_signing_key(kid)
        except JWKSKeyUnavailable as unavailable:
            raise _refused(unavailable.reason, kid=kid) from unavailable

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=list(_algorithms()),
                issuer=_issuer(),
                audience=_audience(),
                leeway=_leeway(),
                options={"require": _REQUIRED_CLAIMS},
            )
        except _DECODE_REFUSED as refusal:
            raise _refused(type(refusal).__name__, kid=kid) from refusal
        return claims

    def _authorized(self, claims: Mapping[str, Any], kid: str) -> tuple[User, Mapping[str, Any]]:
        """Hand the verified claims to the mapper and return what it decided.

        The two calls AD-10 prescribes and nothing else: resolve on every
        authentication, sync at the first sighting of the token's `jti`. This
        method contains no mapping logic and must never acquire any -- the
        deactivated-user check, the `jti` rule and the group diff each have one
        home, and it is the mapper.

        Args:
            claims: The verified claims.
            kid: The key identifier, for the refusal event alone.

        Returns:
            The user and the claims, in the pair DRF assigns to `request.user`
            and `request.auth`.

        Raises:
            AuthenticationFailed: The mapper refused the claims.

        """
        try:
            user = resolve_user(claims)
            sync_once_per_epoch(user, claims)
        except ClaimsRejected as refusal:
            raise _refused(refusal.reason, kid=kid) from refusal
        return (user, claims)


def _bearer_token(request: Request) -> str | None:
    """Read the bearer token out of the `Authorization` header.

    Args:
        request: The request being authenticated.

    Returns:
        The token, or None when the header is absent or names another scheme --
        which is what lets DRF fall through to `SessionAuthentication`.

    Raises:
        AuthenticationFailed: The scheme *is* Bearer and what follows it is not a
            single token. The credential was offered to this class and is
            malformed, so falling through would let a broken Bearer header be
            answered by whatever authenticator came next.

    """
    header = request.META.get("HTTP_AUTHORIZATION")
    if not isinstance(header, str) or not header.strip():
        return None
    parts = header.split()
    if parts[0].lower() != _SCHEME.lower():
        return None
    if len(parts) != 2:  # noqa: PLR2004 - the scheme and exactly one token
        raise _refused(_MALFORMED_HEADER, kid=None)
    return parts[1]


def _refused(reason: str, *, kid: str | None) -> AuthenticationFailed:
    """Log one refusal event and build the 401 to raise.

    One event per rejection, at warning, carrying the reason and the `kid`.
    Never the token and never the raw `Authorization` header: both are the
    credential itself, and a credential in a log is a credential that outlives
    its expiry.

    Args:
        reason: Why the credential was refused. PyJWT's exception class name, the
            key store's reason, or the mapper's -- none of which carries a claim
            value.
        kid: The key identifier the token declared, when one was readable. It is
            attacker-supplied and is logged as a field rather than interpolated
            into the message, so a structured consumer can drop it -- and
            truncated to `_MAX_LOGGED_KID` before it becomes one, so a caller
            cannot choose how many bytes each refusal writes.

    Returns:
        The exception for the caller to raise, so the `raise ... from` chain stays
        at the call site and the traceback keeps the original cause.

    """
    logger.warning("authorization.bearer_rejected", reason=reason, kid=None if kid is None else kid[:_MAX_LOGGED_KID])
    return AuthenticationFailed(_REFUSAL_DETAIL)


def _algorithms() -> tuple[str, ...]:
    """Read the signature-algorithm allowlist in force.

    Returns:
        `settings.OIDC_ALGORITHMS`, or RS256 alone. Never the token's own `alg`.
        A bare string is read as a one-entry allowlist rather than iterated: a
        deployment that sets `OIDC_ALGORITHMS = "RS256"` in a settings override
        would otherwise get `('R', 'S', '2', '5', '6')` and refuse every token
        with an `InvalidAlgorithmError` that names nothing. Empty and
        whitespace-only entries are dropped for the same reason, and an allowlist
        that empties out falls back to the default rather than to "none
        permitted", which `jwt.decode` treats as an error rather than as a
        refusal.

    """
    configured: Any = getattr(settings, "OIDC_ALGORITHMS", None)
    if isinstance(configured, str):
        configured = [configured]
    named = tuple(entry.strip() for entry in configured or () if isinstance(entry, str) and entry.strip())
    return named or _DEFAULT_ALGORITHMS


def _issuer() -> str:
    """Read the issuer every token must assert.

    Returns:
        `settings.OIDC_ISSUER` -- AD-23's single trust anchor, the same value the
        JWKS location is derived from. Empty when unconfigured, which refuses
        every token rather than accepting any issuer; the startup refusal for an
        unconfigured issuer is Epic 4's.

    """
    issuer: str = getattr(settings, "OIDC_ISSUER", "") or ""
    return issuer


def _audience() -> str:
    """Read the audience every token must be minted for.

    Returns:
        `settings.OIDC_AUDIENCE`, stripped. Empty when unconfigured, which
        refuses every token: `aud` is in `_REQUIRED_CLAIMS`, so there is no
        configuration under which the check is skipped. Stripped because a
        whitespace-only value is truthy and would be compared against `aud`
        literally, refusing every token while looking configured.

    """
    audience: str = getattr(settings, "OIDC_AUDIENCE", "") or ""
    return audience.strip()


def _leeway() -> float:
    """Read the clock-skew tolerance in force.

    Returns:
        `settings.OIDC_LEEWAY_SECONDS`, defaulting to zero. **Zero is the shipped
        posture and this changes nothing about it** -- the lever exists so a
        deployment whose IdP clock drifts a few seconds can stop seeing
        intermittent 401s, not because the default verification is loosened.
        Raising it extends every token's accepted lifetime past its own `exp` by
        that many seconds, and relaxes `iat`/`nbf` by the same amount, so it is a
        deliberate widening of the credential window rather than a tuning knob.

    """
    return float(getattr(settings, "OIDC_LEEWAY_SECONDS", 0.0))


class OIDCBearerScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """Describe the Bearer credential in the published OpenAPI document.

    The `type: ignore` on the class statement is drf-spectacular's, not this
    module's: registration happens in an unannotated `__init_subclass__`, which
    strict mode reads as a call into untyped code at every subclass. There is no
    way to subclass the extension without it, and narrowing it to the one error
    code keeps everything else about this class checked.

    drf-spectacular resolves an authenticator to a security scheme through a
    registered extension and has none for a `BaseAuthentication` subclass it does
    not ship. Without this it emits `could not resolve authenticator` for every
    view and leaves the scheme out of `components.securitySchemes` entirely --
    so the one document API clients read would describe the session cookie and
    the legacy token while saying nothing about the credential this whole module
    exists to verify.

    It lives beside the class rather than in a module of its own because
    registration happens at class definition: the extension is only in
    drf-spectacular's registry if something imported it, and the one import
    guaranteed to have happened before an authenticator needs resolving is the
    authenticator's own module.
    """

    target_class = OIDCBearerAuthentication
    name = "bearerAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        """Return the OpenAPI security scheme this credential is.

        Args:
            auto_schema: The schema being generated. Unused -- the credential is
                the same on every route, because DRF applies it globally through
                `DEFAULT_AUTHENTICATION_CLASSES`.

        Returns:
            An HTTP bearer scheme declaring `JWT` as its format, which is what
            tells a client the value is a signed token rather than an opaque
            string it should have obtained from this component.

        """
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
