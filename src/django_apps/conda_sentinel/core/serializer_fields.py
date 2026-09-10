"""The field a derived status is serialized through, and the one thing it refuses.

`CPM-AD-24` says a derived status is emitted as its `OutcomeState` value on every
read surface, and `CPM-APP-S07`'s AC 5 says what that means for JSON: never `null`,
never `""`, never a boolean. `APP.07-API-001` is the test id on it and `R-01` the
risk it closes.

**The failure is not a serializer that lies. It is a serializer that is convenient.**
`unknown` is one of `CPM-FR-5`'s five outcomes and it is the load-bearing one -- it
is how this product says "nobody established anything here". Every ordinary
serialization habit destroys it. `allow_null=True` turns it into `null`, which every
client reads as "no data". A `BooleanField` over "is this package vulnerable" turns
five states into two, and the three it loses are the three that mean *we do not
know*. `required=False` drops the key, and a key that is absent is a key a client
defaults.

So this is a `CharField` that cannot be talked into any of them, and that **raises**
rather than emitting a falsy value. Raising is the right severity: every status
column in this product is non-null with a sentinel default, so a blank one arriving
here is not a missing value -- it is a bug upstream, and `CG-3` says a refusal is
loud. A silently empty status in an API response is the failure that gets noticed a
quarter later, in somebody's dashboard, as a package that looked fine.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from typing import Any
from typing import Final

from rest_framework import serializers

__all__ = ["FALSY_STATUS", "StatusField", "StatusSerializationError"]

#: What a status that came out unusable is reported as.
FALSY_STATUS: Final[str] = (
    "{field!r} serialized {value!r} as a derived status. Every status column in this product is non-null with a "
    "sentinel default, so this is a defect upstream rather than a missing value -- and `unknown` is a state "
    "CPM-FR-5 makes load-bearing, not an absence a client may read as clean."
)


class StatusSerializationError(ValueError):
    """A derived status reached the wire as something other than its value.

    A named exception rather than an assertion, so the sweep in
    `tests/unit/django_apps/test_api_contract_audit.py` can provoke it and so a
    500 traceback names the rule that was broken rather than a `ValueError` from
    somewhere in DRF.
    """


class StatusField(serializers.CharField):
    """A derived status, emitted verbatim or not at all.

    Declared once and used by every serializer that carries a status, which is what
    makes AC 5 checkable: the audit sweeps every serializer in the product for a field
    whose name says status and asserts it is one of these, rather than trusting six
    modules to have each chosen `CharField` over `BooleanField`.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Refuse the three options that would defeat the field.

        Args:
            **kwargs: DRF's field options. `allow_null`, `allow_blank` and
                `required=False` are fixed here rather than merely defaulted --
                passing any of them is a `TypeError`, because a field that could be
                talked out of its own rule would be a comment rather than a
                mechanism.

        Raises:
            TypeError: When a caller passes any of the three.

        """
        forbidden = sorted({"allow_null", "allow_blank", "required"} & set(kwargs))
        if forbidden:
            message = (
                f"StatusField fixes {', '.join(forbidden)}: CPM-APP-S07 AC 5 forbids a derived status reaching a "
                f"client as null, blank or absent."
            )
            raise TypeError(message)
        super().__init__(allow_null=False, allow_blank=False, required=True, **kwargs)

    def to_representation(self, value: Any) -> str:
        """Return the status verbatim.

        Args:
            value: What the projection produced.

        Returns:
            The value's string form, which for every status in this product is
            already the `OutcomeState` value the policy engine wrote.

        Raises:
            StatusSerializationError: When the value is falsy -- `None`, `""`, or a
                boolean `False` that some future refactor substituted for a state.

        """
        if not value or not isinstance(value, str):
            raise StatusSerializationError(FALSY_STATUS.format(field=self.field_name, value=value))
        return value
