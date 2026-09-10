"""One spelling of the search parameter, and one declaration of the control.

`CPM-APP-S18` AC 4. The search now appears on ten surfaces -- the health table, the
JSON API, three queues and six reports -- and every one of them reads a parameter out
of a query string and renders a box back. Ten literals is ten chances to spell it
differently, and the failure is quiet: a reviewer's bookmarked URL simply stops
narrowing on the one page whose view reads `?query=` instead, and shows the whole
report under a heading that says nothing about it.

**The control has the same problem in the template layer.** Three declarations of the
same `<input>` drift, and the field that matters is `maxlength`: `CPM-APP-S17` caught
that one before it shipped, where a box accepting more than `search_term` will keep
turns a long paste into "no search at all", under an input still showing the reader's
text.

Reads source and template files. No database, no rendering, no requests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from conda_sentinel.surface.search import SEARCH_PARAM

#: The application's own source, and the templates the service renders.
SURFACE_ROOT: Final[Path] = Path(__file__).resolve().parents[3] / "src" / "django_apps" / "conda_sentinel" / "surface"
TEMPLATE_ROOT: Final[Path] = (
    Path(__file__).resolve().parents[3] / "src" / "django_service" / "templates" / "conda_sentinel"
)

#: The one module allowed to say what the parameter is called.
THE_DECLARING_MODULE: Final[str] = "search.py"

#: The one template allowed to declare the input.
THE_DECLARING_TEMPLATE: Final[str] = "_searchbox.html"


def surface_modules() -> list[Path]:
    """Return every Python module under `surface/`.

    Returns:
        The paths, sorted so a failure names the same file on every runner.

    """
    return sorted(SURFACE_ROOT.rglob("*.py"))


def templates() -> list[Path]:
    """Return every product template.

    Returns:
        The paths, sorted.

    """
    return sorted(TEMPLATE_ROOT.glob("*.html"))


def test_the_roots_this_audit_walks_actually_hold_something() -> None:
    """Because a sweep over an empty directory passes and proves nothing.

    The failure this prevents is a move: `surface/` or the template directory
    relocating, and every case below going green over nothing.
    """
    assert surface_modules() != []
    assert templates() != []
    assert any(path.name == THE_DECLARING_MODULE for path in surface_modules())
    assert any(path.name == THE_DECLARING_TEMPLATE for path in templates())


@pytest.mark.parametrize("module", surface_modules(), ids=lambda path: path.name)
def test_no_module_but_one_spells_the_parameter_itself(module: Path) -> None:
    """Ten literals is ten chances to spell it differently.

    The symptom is a page that quietly stops narrowing while its heading says
    nothing is filtered -- which reads as a broken search on one screen rather than
    as a typo in one module.

    Args:
        module: The module under test.

    """
    if module.name == THE_DECLARING_MODULE:
        return
    source = module.read_text(encoding="utf-8")

    for literal in (f'"{SEARCH_PARAM}"', f"'{SEARCH_PARAM}'"):
        assert literal not in source, (
            f"{module.name} spells the search parameter itself; import SEARCH_PARAM from surface/search.py"
        )


@pytest.mark.parametrize("template", templates(), ids=lambda path: path.name)
def test_no_template_but_one_declares_the_search_input(template: Path) -> None:
    """Three copies of one `<input>` drift, and the field that drifts is the bound.

    A box accepting more than the server will keep turns a long paste into no search
    at all: the whole inventory comes back, under an input still showing the text
    the reader typed. `CPM-APP-S17` caught exactly that in the health template.

    Args:
        template: The template under test.

    """
    if template.name == THE_DECLARING_TEMPLATE:
        return
    markup = template.read_text(encoding="utf-8")

    assert 'type="search"' not in markup, (
        f"{template.name} declares its own search input; include conda_sentinel/_searchbox.html"
    )
    assert f'name="{SEARCH_PARAM}"' not in markup, (
        f"{template.name} hard-codes the parameter name; render {{{{ search_param }}}}"
    )


def test_the_declaring_template_renders_the_bound_rather_than_a_number() -> None:
    """The half the case above cannot see: the partial itself could hard-code it.

    Every other template is clean because it includes this one, so a literal here
    would be a literal everywhere and nothing above would notice.
    """
    markup = (TEMPLATE_ROOT / THE_DECLARING_TEMPLATE).read_text(encoding="utf-8")

    assert "{{ search_max_length }}" in markup
    assert "{{ search_param }}" in markup
    assert 'maxlength="128"' not in markup
