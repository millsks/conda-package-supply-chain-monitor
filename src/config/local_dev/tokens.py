"""Mint a development Bearer token the real authentication class genuinely verifies.

FR-20's whole point is in the negative space of this module. There is no
`verify_signature=False` path, no settings flag that relaxes audience checking,
no test-only authentication class and no local branch inside
`config/authorization/authentication.py`. What makes the token acceptable is that
it is *correctly signed* by a key the component's configured JWKS location
publishes -- nothing else was softened to let it through. Signature, `iss`, `aud`
and `exp` are all verified by the same code path a token from a real IdP takes.

**The registered claims are read from settings, never written as literals.**
`iss` comes from `settings.OIDC_ISSUER` and `aud` from `settings.OIDC_AUDIENCE`,
which are the exact names `config/authorization/authentication.py` reads through
`_issuer()` and `_audience()`. A literal here would be a second answer to "who
signs these tokens", and the first symptom of the two drifting apart would be a
401 with no diagnosable cause.

**The `jti` is not optional and is not the authentication class's requirement.**
That class requires `exp`, `iss` and `aud`. The `jti` is required a layer deeper,
by `mapper.sync_once_per_epoch`, which refuses a Bearer credential carrying none
(`ClaimsRejected("token carries no jti")`, AD-10) and is what makes authorization
sync happen once per credential rather than once per request. The refusal
surfaces as the same 401.

**The identity and group claims are the personas' and not this module's.**
`build_claims` in `config/local_dev/personas.py` is the sole constructor of
synthetic claims -- the same one local sign-in drives -- so the mapper cannot tell
which path produced the payload. This module adds only the registered claims a
*token* has that a browser session does not.

R-5 stands and is not closed by anything here: synthetic claims never exercise
JWKS retrieval over the network, nor key rotation at the IdP. What is proven
locally is the verification, not the retrieval.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Final

import jwt
import structlog
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config.local_dev.keys import SIGNING_ALGORITHM
from config.local_dev.keys import ensure_keypair
from config.local_dev.keys import load_private_key
from config.local_dev.personas import build_claims
from config.local_dev.personas import get_persona
from config.locality import RUNTIME_ENV_VAR
from config.locality import is_local

__all__ = ["DEFAULT_LIFETIME_SECONDS", "mint_token"]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: How long a minted token lives. Fifteen minutes: long enough to paste into a
#: request by hand, short enough that one left in a shell's history is not a
#: standing credential. A developer who needs longer passes `lifetime_seconds`
#: rather than editing this, and a *negative* value is how the expired-token case
#: is expressed in the suite.
DEFAULT_LIFETIME_SECONDS: Final[int] = 900

#: The refusal, named rather than written at the `raise`, in the shape
#: `config/local_dev/seeding.py` established.
_DEPLOYED_REFUSAL: Final[str] = (
    f"a development token is never minted in a deployed environment. "
    f"{RUNTIME_ENV_VAR} does not declare this run local, and locality fails closed: "
    f"absent or unrecognized means deployed. Locally, run it as `pixi run -e dev mint-token <persona>`."
)


def mint_token(persona_key: str, *, lifetime_seconds: int = DEFAULT_LIFETIME_SECONDS, jti: str | None = None) -> str:
    """Mint a signed development token for a declared persona.

    Args:
        persona_key: The persona to mint for, as declared in
            `config/local_dev/personas.py`.
        lifetime_seconds: How far ahead of now `exp` is set. A negative value
            mints an already-expired token, which is how the rejection case is
            written without a test sleeping through a real lifetime.
        jti: The credential identifier. A fresh one is generated when omitted;
            passing an explicit value is how a second token is made to look like
            the *same* credential epoch rather than a new one.

    Returns:
        The encoded token, ready to present as `Authorization: Bearer <token>`.

    Raises:
        ImproperlyConfigured: The run is not local. Raised before the keypair is
            reached, so a deployed invocation generates nothing.
        UnknownPersonaError: No persona is declared under that key.

    """
    if not is_local():
        raise ImproperlyConfigured(_DEPLOYED_REFUSAL)

    persona = get_persona(persona_key)
    keypair = ensure_keypair()

    issued_at = datetime.now(tz=UTC)
    claims: dict[str, Any] = {
        **build_claims(persona),
        # Read from the settings the authentication class reads. `_audience()`
        # falls back to `OIDC_CLIENT_ID` in `base.py`, and `local.py` fills both
        # where the environment left them unset, so a fresh clone has a real
        # issuer and a real audience to verify against rather than empty strings
        # PyJWT would refuse.
        #
        # The asymmetry is deliberate and mirrors the readers exactly:
        # `authentication._audience()` strips before comparing and
        # `authentication._issuer()` does not. A padded audience minted as
        # written would be compared against its own stripped self and refused;
        # a padded issuer *stripped* here would be compared against the unstripped
        # setting and refused just as surely. Matching each reader is the whole
        # rule -- "read from the same source" means in the same shape, too.
        "iss": settings.OIDC_ISSUER,
        "aud": settings.OIDC_AUDIENCE.strip(),
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=lifetime_seconds),
        # AD-10: a Bearer credential with no `jti` is refused by the mapper's
        # epoch gate, and the gate is what keeps authorization sync to once per
        # credential instead of once per request.
        #
        # A blank value is treated as absent rather than carried through. The
        # mapper reads `jti` and refuses `token carries no jti` for anything
        # empty, so minting `""` would produce a token that cannot authenticate
        # and a 401 whose cause is an argument the caller thought they supplied.
        "jti": jti.strip() if jti and jti.strip() else uuid.uuid4().hex,
    }

    token = jwt.encode(
        claims,
        load_private_key(keypair),
        # The algorithm is stated here and checked against the component's
        # allowlist there. Never `alg` from a header, in either direction.
        algorithm=SIGNING_ALGORITHM,
        headers={"kid": keypair.kid},
    )
    logger.info(
        "local_dev.token_minted",
        persona=persona.key,
        kid=keypair.kid,
        jti=claims["jti"],
        expires_at=claims["exp"].isoformat(),
    )
    return token
