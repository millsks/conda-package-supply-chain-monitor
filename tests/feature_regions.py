"""How the suite reads AD-24's feature-owned regions, in one place.

AD-24 delimits a feature-owned span of a file with paired line comments spelled
exactly `# feature:<name>` and `# /feature:<name>`, and permits **no other
sub-file removal mechanism** -- not a conditional import, not settings-module
inheritance, not a `try`/`except ImportError` probe. The materializer removes a
region's lines; everything outside every region travels into all six
combinations. So "is this line inside a region?" is a question about what a
component will actually contain, and more than one module needs to ask it.

`tests/unit/startup/test_feature_scoped_refusals.py` asks it of
`src/config/startup/stage_one.py`: a condition's definition and its roster entry
must both fall inside the same feature's pair, because an entry left outside one
survives into a combination whose definition has gone -- a `NameError` at
settings import rather than a missing check. Story 5.7's
`tests/unit/test_session_settings.py` asks the complement of it about
`src/config/settings/base.py`: `SESSION_ENGINE` must fall inside **no** region,
because FR-44's point is that session behaviour cannot vary by toggle and an
assignment inside a region is an assignment the materializer removes from every
component that did not select that region's feature.

The parser lived in the refusals module until this story needed the same
question answered about a different file. A private second copy would have been
the fourth reader of the same comment syntax, and this repository's established
answer to that is promotion rather than duplication -- `tests/pixi_manifest.py`
(Story 5.5) and `tests/dockerfile.py` (Story 5.6) were both lifted out of a test
module exactly this way, and for the reason AD-26 gives about predicates: two
readers that can disagree about where a region *is* let a line escape one
module's assertion while satisfying the other's. Nothing about the parse changed
in the move.

**What this deliberately does not answer.** The substring-matching
`FEATURE_MARKERS` tuples in `tests/unit/test_component_declaration.py` and
`tests/unit/test_process_model.py` stay where they are. Those ask a *positional*
question about TOML -- where a marker sits relative to a table header, and which
task assignments fall between the pair -- against stripped lines rather than
source text, and folding them in here would be a refactor of Story 5.1's and
5.2's work rather than of this story's.

Balance and non-nesting are not checked here either. `_regions` is lenient about
an imbalanced pair on purpose: detecting one is
`test_feature_scoped_refusals.py::TestTheFeatureRegionMarkers`'s job, and a
helper that raised would make that module fail during *collection* instead of
reporting which file is malformed.

This is a helper module, not a collected one. `[tool.pytest.ini_options]
python_files` matches `test_*.py` and `tests.py`, so nothing here is collected,
and it sits at `tests/` rather than under `tests/unit/` because a collected test
module is not a helper library and importing one from another ties two files'
collection together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: AD-24's delimiters, matched as whole lines in the file's own comment syntax.
#: Anchored so that the same text quoted inside a module docstring -- where the
#: region declarations are recorded until Epic 7 authors `accelerator.toml` -- is
#: not read as a marker. That is the same distinction Story 8.3's stripper has to
#: make, which is why it is made the same way here.
MARKER: Final = re.compile(r"^[ \t]*#[ \t]*(?P<closing>/?)feature:(?P<feature>[A-Za-z0-9_-]+)[ \t]*$")


@dataclass(frozen=True, slots=True)
class Region:
    """One balanced marker pair, and the lines it encloses.

    Attributes:
        feature: The feature named by both markers.
        first_line: 1-indexed line just after the opening marker.
        last_line: 1-indexed line just before the closing marker.

    """

    feature: str
    first_line: int
    last_line: int

    def encloses(self, line: int) -> bool:
        """Report whether a 1-indexed source line falls inside this region.

        Args:
            line: The line to test.

        Returns:
            True when the line is strictly between the two markers.

        """
        return self.first_line <= line <= self.last_line


def marker_events(source: str) -> list[tuple[int, bool, str]]:
    """Every marker line in one file, in file order.

    Args:
        source: The file's text.

    Returns:
        Tuples of 1-indexed line number, whether the marker closes a region, and
        the feature it names.

    """
    events: list[tuple[int, bool, str]] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        match = MARKER.match(line)
        if match is not None:
            events.append((line_number, bool(match["closing"]), match["feature"]))
    return events


def regions(source: str) -> list[Region]:
    """Pair the markers up into regions.

    Written to be lenient about imbalance rather than to detect it -- detection is
    `test_every_marker_pair_is_balanced_and_never_nested`'s, and a helper that
    raised would make that test fail during collection instead of reporting.

    Args:
        source: The file's text.

    Returns:
        One entry per closed pair, in the order the pairs close.

    """
    open_at: dict[str, int] = {}
    paired: list[Region] = []
    for line_number, closing, feature in marker_events(source):
        if closing:
            opened = open_at.pop(feature, None)
            if opened is not None:
                paired.append(Region(feature, opened + 1, line_number - 1))
        elif feature not in open_at:
            open_at[feature] = line_number
    return paired
