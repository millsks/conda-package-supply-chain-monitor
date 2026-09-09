"""`CPM-AD-22`'s finding key: stable across re-observation, and declared where the evidence is.

The failure this module guards is the one the decision names and is worth stating
again, because nothing about it announces itself: **an accepted finding resurrecting
as new work tomorrow.** Evidence is append-only, so tonight's run inserts a new row
for the advisory it saw yesterday. A key that moved with the row would open a second
item, put an accepted finding back at the top of a queue, and leave the original
sitting there resolved -- with no exception, no log line and nothing failing.

So the cases below are mostly about what the key must **not** change with. Testing
that a key exists is easy and proves nothing; testing that two rows a week apart
produce the same one is the whole of `CPM-APP-S04`'s AC 2.

**The digest is checked for the property it is chosen for, not for its value.** No
case asserts a literal hash: that would pin an implementation detail and fail on any
change to the encoding, which is exactly the change somebody should be free to make.
What is asserted is that different facts give different keys and the same facts give
the same one, which is what a key is for.

Builds model instances without saving: no database, no queries.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Final

import pytest

from conda_sentinel.collectors.match_confidence import MatchConfidence
from conda_sentinel.collectors.models import LicenseFinding
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.collectors.outcomes import MATCHED
from conda_sentinel.core.finding_keys import DIGEST_LENGTH
from conda_sentinel.core.finding_keys import FINDING_KEY_LENGTH
from conda_sentinel.core.finding_keys import FindingKeyed
from conda_sentinel.core.finding_keys import FindingKeyError
from conda_sentinel.core.finding_keys import finding_key_of

#: A package id, used unsaved -- the key is built from the column, not from a row.
A_PACKAGE: Final[int] = 1
ANOTHER_PACKAGE: Final[int] = 2

OBSERVED: Final[datetime] = datetime(2026, 9, 4, 5, 38, tzinfo=UTC)

#: The two tables that can produce work today, and the fields each declares.
#:
#: Written out rather than read from the models, because this is the *claim*: these
#: are the keys `CPM-AD-22` and this story settled on. A model that changed its
#: declaration should fail here and make somebody say why, since changing a key
#: silently re-files every open item in that queue.
DECLARED: Final[dict[type[FindingKeyed], tuple[str, ...]]] = {
    VulnerabilityFinding: ("advisory_id", "affected_range"),
    LicenseFinding: ("normalized_license", "channel"),
}

#: Fields no key may be built from, because they are exactly what changes when the
#: same fact is observed again.
FORBIDDEN_KEY_FIELDS: Final[frozenset[str]] = frozenset({"id", "pk", "observed_at", "trace_id"})


def an_advisory(**overrides: object) -> VulnerabilityFinding:
    """Return an unsaved advisory finding, with every fact its table requires.

    Args:
        **overrides: Fields to vary.

    Returns:
        The instance, unsaved.

    """
    fields: dict[str, object] = {
        "package_id": A_PACKAGE,
        "observed_at": OBSERVED,
        "state": MATCHED,
        "advisory_id": "CVE-2024-23334",
        "severity": "critical",
        "affected_range": "<3.9.2",
        "matched_version": "3.9.1",
        "match_confidence": MatchConfidence.EXACT_VERSION,
    }
    return VulnerabilityFinding(**(fields | overrides))  # type: ignore[arg-type]


def a_licence(**overrides: object) -> LicenseFinding:
    """Return an unsaved licence finding.

    Args:
        **overrides: Fields to vary.

    Returns:
        The instance, unsaved.

    """
    fields: dict[str, object] = {
        "package_id": A_PACKAGE,
        "observed_at": OBSERVED,
        "state": "normalized",
        "channel": "conda-forge",
        "raw_license": "Apache 2.0",
        "normalized_license": "Apache-2.0",
        "detection_method": "recognised-spelling",
    }
    return LicenseFinding(**(fields | overrides))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# What the key must survive. This is AC 2.
# ---------------------------------------------------------------------------


def test_a_re_observation_a_week_later_has_the_same_key() -> None:
    """The whole point. `CPM-AD-2` inserts; the key must not move with the row.

    A key that changed here would open a second item every night, and the reviewer
    who accepted the finding on Monday would meet it again on Tuesday.
    """
    assert an_advisory().finding_key() == an_advisory(observed_at=OBSERVED - timedelta(days=7)).finding_key()


def test_upgrading_the_package_does_not_change_the_key() -> None:
    """A package moved from 3.9.1 to 3.9.15 while an advisory is open is one finding.

    `matched_version` is deliberately not a key field. Including it would produce a
    second item the moment somebody upgraded *towards* the fix without reaching it --
    punishing the person who did the work with duplicate work.
    """
    assert an_advisory().finding_key() == an_advisory(matched_version="3.9.15").finding_key()


def test_rescoring_an_advisory_does_not_change_the_key() -> None:
    """A source that re-scores high to critical has changed how urgent one finding is.

    Not created another. `severity` drives the priority bucket, which is re-derived
    every run; it has no business in the identity of the work.
    """
    assert an_advisory().finding_key() == an_advisory(severity="high").finding_key()


def test_tidying_a_licence_spelling_does_not_change_the_key() -> None:
    """`Apache 2.0` and `Apache-2.0` are one compliance question.

    Keying on `raw_license` would open a second review item the day a source tidied
    its metadata, and a reviewer would be asked to decide the same thing twice.
    """
    assert a_licence().finding_key() == a_licence(raw_license="Apache-2.0").finding_key()


# ---------------------------------------------------------------------------
# What the key must distinguish. Without these the case above is satisfied by
# returning a constant.
# ---------------------------------------------------------------------------


def test_two_advisories_on_one_package_are_two_findings() -> None:
    """Otherwise one item would stand for every vulnerability a package ever has."""
    assert an_advisory().finding_key() != an_advisory(advisory_id="CVE-2025-00000").finding_key()


def test_one_advisory_on_two_packages_is_two_findings() -> None:
    """Two packages exposed by one advisory are two pieces of work.

    Which is why the package is always part of the key, whatever a table declares.
    """
    assert an_advisory().finding_key() != an_advisory(package_id=ANOTHER_PACKAGE).finding_key()


def test_a_different_affected_range_is_a_different_finding() -> None:
    """A re-scoped advisory is a different claim about which versions are exposed.

    `CPM-AD-22` names the range as part of the key for this reason: the advisory
    saying "<3.9.2" and the advisory saying "<4.0" are not the same question about
    this package, even under one identifier.
    """
    assert an_advisory().finding_key() != an_advisory(affected_range="<4.0").finding_key()


def test_the_same_licence_on_two_channels_is_two_findings() -> None:
    """One package can carry different licences on different channels."""
    assert a_licence().finding_key() != a_licence(channel="internal").finding_key()


def test_two_tables_never_collide() -> None:
    """The table is part of the key, so an advisory and a licence cannot share an item.

    Contrived to make the point: two findings whose declared facts are identical
    strings still belong to different queues and different work.
    """
    first, _ = finding_key_of("vulnerability_findings", A_PACKAGE, [("a", "b")])
    second, _ = finding_key_of("license_findings", A_PACKAGE, [("a", "b")])

    assert first != second


def test_the_encoding_is_not_ambiguous_across_field_boundaries() -> None:
    """The reason the digest is over a length-prefixed encoding rather than a join.

    Any separator can appear inside an advisory identifier or a version range, so a
    joined string makes `("ab", "c")` and `("a", "bc")` the same key. Length-prefixing
    removes the question instead of answering it with a refusal callers would have to
    handle.
    """
    first, _ = finding_key_of("t", A_PACKAGE, [("x", "ab"), ("y", "c")])
    second, _ = finding_key_of("t", A_PACKAGE, [("x", "a"), ("y", "bc")])

    assert first != second


def test_field_order_is_part_of_the_key() -> None:
    """A table that reorders its declaration has changed what it calls one finding.

    It should get different keys and a visible re-filing, rather than silently
    merging two kinds of work under one item.
    """
    first, _ = finding_key_of("t", A_PACKAGE, [("x", "1"), ("y", "2")])
    second, _ = finding_key_of("t", A_PACKAGE, [("y", "2"), ("x", "1")])

    assert first != second


# ---------------------------------------------------------------------------
# The declarations themselves.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("model", "expected"), sorted(DECLARED.items(), key=lambda entry: entry[0].__name__))
def test_each_table_declares_the_key_this_story_settled_on(
    model: type[FindingKeyed], expected: tuple[str, ...]
) -> None:
    """Changing a key silently re-files every open item in that queue.

    So the declaration is pinned here and a change has to be argued for, rather than
    landing as a one-line diff nobody reads as a data migration.

    Args:
        model: The evidence model.
        expected: The fields it must declare.

    """
    assert expected == model.FINDING_KEY_FIELDS


@pytest.mark.parametrize("model", sorted(DECLARED, key=lambda entry: entry.__name__), ids=lambda m: m.__name__)
def test_no_key_field_is_one_that_changes_on_re_observation(model: type[FindingKeyed]) -> None:
    """The whole mechanism fails if a key field is one that moves with the row.

    Args:
        model: The evidence model.

    """
    offending = FORBIDDEN_KEY_FIELDS & set(model.FINDING_KEY_FIELDS)

    assert offending == set(), f"{model.__name__} keys on {sorted(offending)}, which changes every observation"


@pytest.mark.parametrize("model", sorted(DECLARED, key=lambda entry: entry.__name__), ids=lambda m: m.__name__)
def test_every_declared_key_field_is_a_real_column(model: type[FindingKeyed]) -> None:
    """A field name that is not a column produces a key over an empty string, silently.

    Args:
        model: The evidence model.

    """
    columns = {field.name for field in model._meta.get_fields()}  # noqa: SLF001 - a model's own metadata

    assert set(model.FINDING_KEY_FIELDS) <= columns, sorted(set(model.FINDING_KEY_FIELDS) - columns)


# ---------------------------------------------------------------------------
# The shape of the key, and the refusals.
# ---------------------------------------------------------------------------


def test_the_key_is_readable_at_the_front_and_exact_at_the_back() -> None:
    """Both halves earn their place: the prefix is for a person, the digest for exactness.

    A pure digest tells a reviewer reading a queue nothing about what they are
    looking at; a spelled-out natural key is unbounded and a column is not.
    """
    key, facts = an_advisory().finding_key()
    table, package, digest = key.split(":")

    assert table == "vulnerability_findings"
    assert package == str(A_PACKAGE)
    assert len(digest) == DIGEST_LENGTH
    assert "CVE-2024-23334" in facts


def test_the_key_fits_its_column() -> None:
    """Bounded by construction, and asserted because the column has a width.

    The longest realistic key is a long table name plus a large package id plus the
    digest, and it has to fit whatever any source ever puts in a version range --
    which is the point of not spelling the facts into the key.
    """
    key, _ = an_advisory(affected_range=">=1.0,<2.0 || >=2.1,<3.0 || " * 40).finding_key()

    assert len(key) <= FINDING_KEY_LENGTH


def test_a_table_that_declares_no_key_field_is_refused() -> None:
    """Loudly, at the point of asking, rather than by filing everything under one item.

    A key over the package alone is the opposite failure to the one this mechanism
    prevents, and just as quiet: one item standing for every advisory a package has.
    """
    with pytest.raises(FindingKeyError, match=r"no key fields"):
        finding_key_of("t", A_PACKAGE, [])


def test_a_declared_field_the_table_does_not_have_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The declaration error that would otherwise produce a key over an empty string.

    Which would be stable, and identical for every row -- so every finding on a
    package would collapse into one item and nothing would say why.

    **Patched onto the real model rather than declared as a subclass**, and the
    reason is a defect this case introduced the first time it was written: defining a
    model in a test body registers it in the app registry for the rest of the
    session, and `test_migration_completeness.py` then sees a model with no migration
    -- so an unrelated audit failed in the full suite and passed when run alone.

    Args:
        monkeypatch: pytest's patcher, which restores the declaration.

    """
    monkeypatch.setattr(
        VulnerabilityFinding,
        "FINDING_KEY_FIELDS",
        ("advisory_id", "a_column_that_does_not_exist"),
    )

    with pytest.raises(FindingKeyError, match=r"a_column_that_does_not_exist"):
        an_advisory().finding_key()


def test_a_blank_value_still_produces_a_key() -> None:
    """A finding whose key field is empty is still one finding, and still needs an item.

    An advisory with no range is unusual and not impossible, and refusing it here
    would mean the work never reaches a queue at all -- silence being the worst of
    the available answers.
    """
    key, facts = finding_key_of("t", A_PACKAGE, [("x", "")])

    assert key
    assert facts == "x="
