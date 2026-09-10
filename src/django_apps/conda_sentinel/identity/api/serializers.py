"""What an identity override accepts, and what it returns.

**The request serializer validates shape, never policy.** Whether a reason is
adequate, whether a name collides, whether the actor may act -- all of that is
`override_identity`'s, and a serializer that re-checked any of it would be a second
place the rule lives. What it does is what a serializer is for: refuse a body that is
not a correction at all, so the service is never handed one.

The one exception is `reason`, which is `required=True` here as well as checked
there. That is not a duplicate rule -- it is the same rule stated where a client can
see it: `CPM-AD-14` makes the justification part of the decision, and an API whose
schema showed it as optional would be advertising a correction this product does not
accept.

**`display_name` distinguishes absent from empty, and the two mean different
things.** Omitting it leaves the stored value alone; sending `""` clears it. `None`
is what `Correction` reads as "leave it", so the field is `required=False` with no
default rather than `allow_null` -- a client that sends `null` is saying the same
thing as one that omits it, and both are honest.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

__all__ = ["CorrectionSerializer", "IdentityOverrideSerializer"]


class CorrectionSerializer(serializers.Serializer[Any]):
    """One human correction of a package's identity."""

    #: Why. Required and non-blank, which the service enforces again -- stated here
    #: so the published schema says so rather than leaving a client to discover it
    #: from a 400.
    reason = serializers.CharField(allow_blank=False)

    #: The corrected name, or omitted to leave the stored one alone. Correcting it is
    #: safe precisely because nothing in this product references a package by its
    #: name (`CPM-AD-3`).
    canonical_name = serializers.CharField(required=False, allow_blank=True, default="")

    #: What a human should be shown. Omit to leave it; send `""` to clear it. The
    #: empty string is not absence here -- it means "there is no display name", which
    #: PRD Appendix A.1's data rules make the honest spelling of missing.
    display_name = serializers.CharField(required=False, allow_blank=True)


class IdentityOverrideSerializer(serializers.Serializer[Any]):
    """The audit row an override wrote.

    Returned rather than the corrected package, on `override_identity`'s own terms:
    the row is what `CPM-FR-32` makes independently queryable, the package is
    reachable through it, and a caller handed only the package could not tell an
    override that changed nothing from one that was never recorded.
    """

    id = serializers.IntegerField()
    package_id = serializers.IntegerField()
    reason = serializers.CharField()

    #: What it was, and what it became, on every field the override may touch. Both
    #: halves, because an audit row that recorded only the new value would leave a
    #: reader unable to tell what was corrected from what was merely restated.
    prior_canonical_name = serializers.CharField(allow_blank=True)
    new_canonical_name = serializers.CharField(allow_blank=True)
    prior_display_name = serializers.CharField(allow_blank=True)
    new_display_name = serializers.CharField(allow_blank=True)
    prior_confidence = serializers.CharField()
    new_confidence = serializers.CharField()

    #: When, and who. `CPM-AD-14`'s whole point is that this write is attributable.
    observed_at = serializers.DateTimeField()
    actor = serializers.CharField(source="actor.username", allow_null=True, default=None)
