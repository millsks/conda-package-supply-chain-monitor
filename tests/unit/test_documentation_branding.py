"""`CPM-DOCS-S02`: the documentation site looks like the product it documents.

Four criteria, and the one that decides the implementation is AC 1: the palette is
**mapped onto Material's own variables**, not applied to its components. A stylesheet
that restyled `.md-nav__link` directly would work today and break on Material's next
minor release — and the breakage would be a documentation site nobody notices is
broken, because nobody has it open when they deploy.

**AC 4 is the one worth arguing about.** `CPM-FR-5` makes five outcome states
distinguishable and `CPM-AD-24` emits each verbatim, so that `unknown` means the same
thing on a screen, in a CSV and in a JSON response. Documentation that set `unknown`
as an ordinary word would make, in prose, exactly the mistake the export rule forbids
in a file — a reader would take it for a hedge rather than for the state this product
asserts.

**Asserted against the sources, not the built site**, which took one correction.
Reading `site/index.html` meant skipping when it was absent, and
`tests/unit/test_suite_policy.py` bans a skip in a test body -- a skipped case reads
in a report as a gate that ran. It is also the wrong split of labour: `pixi run docs`
is `mkdocs build --strict` and is already in the gate, so *that* it renders is proven
there. What is proven here is that the declarations exist to render.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest
import yaml

#: The repository root, from this file rather than from a layout assumption.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MKDOCS: Final[Path] = REPO_ROOT / "mkdocs.yml"
STYLESHEET: Final[Path] = REPO_ROOT / "docs" / "stylesheets" / "conda-sentinel.css"
FRONT_PAGE: Final[Path] = REPO_ROOT / "docs" / "index.md"

#: The name of the accelerator this component was generated from.
#:
#: Matched as a phrase rather than on "accelerator" alone: that is an ordinary word
#: which could legitimately appear in prose, and flagging it would make this a sweep
#: people learn to work around.
ANOTHER_PRODUCT: Final[str] = "django 15-factor"

#: This product's name.
THIS_PRODUCT: Final[str] = "conda-sentinel"

#: Material's own variables, which the palette is assigned to rather than around.
#:
#: A handful rather than all of them: these are the ones that decide whether a page
#: reads as this product — the accent, the page ground, and the body colour. A file
#: that set none of them is one that restyled components instead, which is the failure
#: this checks for.
MAPPED_ONTO_MATERIAL: Final[tuple[str, ...]] = (
    "--md-primary-fg-color",
    "--md-accent-fg-color",
    "--md-default-bg-color",
    "--md-typeset-color",
)

#: The five states `CPM-FR-5` makes distinguishable, as the stylesheet spells them.
#:
#: Four classes for five states: `not_found` and `not_applicable` share `unknown`'s
#: treatment because all three are the product declining to assert a verdict, and a
#: reader distinguishing them by colour would be reading a distinction the palette
#: cannot carry. The *word* is what distinguishes them, which is the point.
STATE_CLASSES: Final[tuple[str, ...]] = ("ok", "warn", "crit", "unknown")


def stylesheet() -> str:
    """Return the stylesheet's source.

    Returns:
        Its text, with whitespace collapsed so a declaration written across two lines
        reads the same as one written across one.

    """
    return re.sub(r"\s+", " ", STYLESHEET.read_text(encoding="utf-8"))


def front_page() -> str:
    """Return the front page's source.

    Returns:
        Its markdown. The source rather than the built page: see the module docstring
        -- `pixi run docs` proves it renders, and it is already in the gate.

    """
    return FRONT_PAGE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC 1: the product's palette, type and mark.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variable", MAPPED_ONTO_MATERIAL)
def test_the_palette_is_mapped_onto_materials_own_variables(variable: str) -> None:
    """AC 1, and the decision the whole file rests on.

    Assigning to Material's variables leaves the theme doing its job and changes only
    the colours. Restyling its components would work today and break on its next minor
    release — and a broken documentation site is one nobody notices, because nobody
    has it open when they deploy.

    Args:
        variable: The Material variable that must be assigned.

    """
    assert f"{variable}:" in stylesheet(), (
        f"{variable} is never assigned, so the theme's own colour for it stands. CPM-DOCS-S02 maps the "
        f"product's palette onto Material rather than restyling Material's components."
    )


def test_the_stylesheet_is_linked_and_not_merely_written() -> None:
    """A stylesheet declared and not linked is the failure a source check cannot see.

    `extra_css` is one line in `mkdocs.yml` and its absence produces a site that looks
    exactly like an unbranded one — which is indistinguishable from having done
    nothing, and is what this case exists to tell apart.
    """
    config = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))

    assert "stylesheets/conda-sentinel.css" in config.get("extra_css", [])
    assert STYLESHEET.is_file(), f"{STYLESHEET} is registered in extra_css and does not exist"


def test_the_site_uses_the_products_own_faces() -> None:
    """IBM Plex, which is the product's. Declared in both places, and both are needed.

    `mkdocs.yml` is what makes Material fetch the faces; the stylesheet is what names
    the fallback stack, so a site read offline stays legible rather than dropping to a
    serif nobody chose.
    """
    config = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))
    source = stylesheet()

    assert config["theme"]["font"]["text"] == "IBM Plex Sans"
    assert config["theme"]["font"]["code"] == "IBM Plex Mono"
    assert '--md-text-font: "IBM Plex Sans"' in source
    assert "ui-sans-serif" in source, "the face is named with no fallback, so an offline read loses it"


def test_the_brand_mark_is_the_applications_own() -> None:
    """The `cs` glyph from the product's top bar.

    Built in CSS rather than shipped as an image: it is two letters on a rounded
    square, and an SVG would be a second asset to keep in step with a colour that
    already comes from a token.
    """
    source = stylesheet()

    assert 'content: "cs"' in source
    assert "var(--cs-accent)" in source


# ---------------------------------------------------------------------------
# AC 2: the front page is about this product.
# ---------------------------------------------------------------------------


def test_the_front_page_describes_this_product() -> None:
    """AC 2. It opened with "Django 15-Factor Base — a Django application accelerator".

    The site was titled Conda-Sentinel and its front page described a different
    product, which is the single most confusing thing a documentation site can do:
    a reader concludes they are in the wrong place and leaves.

    Both halves — it names this product, and it names no other. Asserting only the
    absence would pass on a page naming nothing at all, which is a different failure
    with the same symptom.
    """
    page = FRONT_PAGE.read_text(encoding="utf-8").lower()

    assert THIS_PRODUCT in page
    assert ANOTHER_PRODUCT not in page


def test_no_page_on_the_site_is_titled_for_another_product() -> None:
    """The site's own name, which `mkdocs.yml` puts on every tab."""
    config = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))

    assert config["site_name"] == "Conda-Sentinel"
    assert ANOTHER_PRODUCT not in config["site_description"].lower()


# ---------------------------------------------------------------------------
# AC 3: both schemes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["default", "slate"])
def test_the_palette_is_defined_in_both_schemes(scheme: str) -> None:
    """AC 3. A page rendered in the other scheme must not fall back to Material's.

    The failure this catches is partial: a palette defined once looks right in one
    scheme and reverts to indigo in the other, and whoever wrote it only ever looked
    at the one their machine was in.

    Args:
        scheme: Material's scheme attribute value.

    """
    source = stylesheet()

    assert f'[data-md-color-scheme="{scheme}"]' in source
    block = source.split(f'[data-md-color-scheme="{scheme}"]', 1)[1]
    assert "--md-primary-fg-color:" in block.split("}", 1)[0]


def test_a_reader_can_choose_a_scheme() -> None:
    """A palette that honours a preference and cannot be told otherwise is half a feature.

    Two entries with toggles, which is what gives Material its control — the same
    three-state shape the application's own has (`CPM-APP-S11`), reached differently
    because the two are read in separate tabs and are deliberately not reconciled.
    """
    config = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))
    palette = config["theme"]["palette"]

    assert len(palette) == len(["light", "dark"])
    assert all("toggle" in entry for entry in palette), palette


# ---------------------------------------------------------------------------
# AC 4: an outcome state reads as a state.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", STATE_CLASSES)
def test_every_outcome_state_has_a_treatment_of_its_own(state: str) -> None:
    """AC 4. `unknown` set as an ordinary word reads as a hedge, not as a finding.

    Which is, in prose, the mistake `CPM-AD-24` forbids in an export — and prose is
    where somebody first learns what the five states mean, so getting it wrong here
    costs more than getting it wrong once on a screen.

    Args:
        state: The class the stylesheet must define.

    """
    assert f".cs-state.{state}" in stylesheet()


def test_the_front_page_shows_the_states_as_states() -> None:
    """Declared and used, because a class nobody applies is a class nobody sees.

    The front page is where a reader meets the five for the first time, so it is the
    page that has to show rather than tell.
    """
    used = re.findall(r'class="cs-state ([a-z]+)"', front_page())

    assert len(used) >= len(STATE_CLASSES), used
    assert "unknown" in used, used
    assert set(used) <= set(STATE_CLASSES), sorted(set(used) - set(STATE_CLASSES))
