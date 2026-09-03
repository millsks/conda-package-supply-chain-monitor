"""This package's refusals, in one module so no caller has to know where they live.

FR-8 puts every authorization decision behind one mapper, and AD-4 keeps that
mapper free of any protocol. A refusal therefore has to leave here as a plain
Python exception: the DRF Bearer class (Story 2.7) turns it into DRF's 401, the
allauth adapter (Story 2.6) turns it into allauth's, and Epic 3's local sign-in
route turns it into a form error. None of those translations can live in the
mapper without pinning it to one caller, which is why nothing in this package
imports `rest_framework` or raises `AuthenticationFailed`.

`ClaimsRejected` is one exception type, not a hierarchy. The callers do not
branch on the *kind* of refusal -- every one of them answers 401 -- so a
hierarchy would be structure nothing reads. `reason` carries the detail instead,
and it is the string the caller logs.

`JWKSKeyUnavailable` is a *separate* type rather than another `ClaimsRejected`
reason, and the distinction is real: nothing is wrong with the claims when the
key store cannot produce a signing key. The token may be perfectly good and the
IdP unreachable, or the `kid` may be one no rotation has ever published. It
lives here rather than in `jwks.py` because `authentication.py` catches it, and
one exceptions module for the package is what keeps a caller from importing the
key store to name an exception.
"""

from __future__ import annotations

__all__ = ["ClaimsRejected", "JWKSKeyUnavailable"]


class ClaimsRejected(Exception):  # noqa: N818
    """A set of claims cannot be mapped onto a user.

    Named for what happened rather than with the `Error` suffix ruff's N818
    prefers: this is the refusal half of an authorization decision, and callers
    read it as "these claims were rejected". The suffix would make it look like
    a fault in the component when it is a verdict about the token.

    Attributes:
        reason: Why the claims were refused, in a form fit for a log event. It
            never carries a claim *value* -- an identity key or an email in a
            refusal message is the token leaking into the log.

    """

    def __init__(self, reason: str) -> None:
        """Record the reason and pass it to `Exception` as the message.

        Args:
            reason: Why the claims were refused.

        """
        super().__init__(reason)
        self.reason = reason


class JWKSKeyUnavailable(Exception):  # noqa: N818
    """No verification key is available for the `kid` a token presented.

    Named for the state rather than with the `Error` suffix ruff's N818 prefers,
    for the reason `ClaimsRejected` gives: it is a verdict about what the key
    store can supply right now, not a fault in the component. Three distinct
    situations produce it and the caller answers all three the same way, with a
    401 -- the `kid` was never published, the refetch that would have found it
    was refused by the rate limit, or the IdP could not be reached.

    Attributes:
        reason: Why no key could be produced, in a form fit for a log event. It
            never carries the token or the `Authorization` header; the `kid` is
            logged as its own field by the caller.

    """

    def __init__(self, reason: str) -> None:
        """Record the reason and pass it to `Exception` as the message.

        Args:
            reason: Why no key could be produced.

        """
        super().__init__(reason)
        self.reason = reason
