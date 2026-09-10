"""The reader's choice of theme, and the third state that is not a colour.

`static/css/conda-sentinel.css` was written for three states and has been since the
mockups landed: light tokens on bare `:root`, a `prefers-color-scheme: dark` block
guarded by `:root:not([data-theme="light"])`, and `:root[data-theme="dark"]` for an
explicit choice. Nothing ever set `data-theme`, so half of that stylesheet was
unreachable -- the product followed the operating system and offered no way to
disagree with it.

**`auto` is a real choice, not the absence of one.** It is what a reader picks when
they want the product to follow the machine. Collapsing the three into a light/dark
toggle is the common mistake and it is a lossy one: somebody whose laptop switches at
sunset wants the product to switch with it, and a two-state toggle can only record
where they were when they last touched it.

**Light is the default, and that is a product decision rather than a technical one.**
Following the machine would have been the technical default -- it is what the
stylesheet does when nothing overrides it -- and the product owner asked for light.
The reasoning is worth keeping: this product is read beside other operator tooling and
in screenshots pasted into tickets, and a first-time reader who has not chosen should
see the same screen as everybody else describing it. `auto` costs one click and the
control says plainly that it is there.

The cost is stated rather than hidden: a reader on a dark desktop gets a light page
until they say otherwise. That is the trade the default makes, and it is the reason
`auto` stays in the control rather than being the thing you get by not choosing.

**Stored in a cookie, and deliberately not on the user.** A theme is a property of
the screen somebody is looking at, not of who they are: the same person on a bright
monitor and a dark laptop wants different answers, and a column on `User` would make
those two the same answer. It also means the choice works before anybody signs in,
which matters because the sign-in page is a screen too.

**No JavaScript**, which is the product's stance rather than this module's -- and
here that constraint is what makes AC 3 satisfiable rather than a cost. A client-side
toggle cannot know the choice before the document loads, so it paints the default and
corrects it, which is the flash of the wrong theme every `localStorage`
implementation has. A cookie is on the request, so the server renders the right
attribute the first time.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.utils.functional import _StrPromise

__all__ = [
    "AUTO",
    "DEFAULT",
    "THEMES",
    "THEME_COOKIE",
    "THEME_COOKIE_MAX_AGE",
    "THEME_LABELS",
    "THEME_PARAMETER",
    "asserted_theme",
    "theme_of",
]

#: Where the choice is kept.
#:
#: Namespaced, because a component deployed beside another on one host shares a cookie
#: jar with it, and `theme` is the name everybody reaches for first.
THEME_COOKIE: Final[str] = "conda-sentinel-theme"

#: The form field the choice arrives in.
THEME_PARAMETER: Final[str] = "theme"

#: The choice that means "follow the machine".
#:
#: It renders **no** `data-theme` attribute, which is what hands the decision back to
#: the stylesheet's `prefers-color-scheme` block. A value of its own would need a
#: fourth branch in the CSS whose only job was to undo the other three.
AUTO: Final[str] = "auto"

#: What a reader who has not chosen gets. See the module docstring.
#:
#: **Written as an attribute rather than left implicit**, which is the half that is
#: easy to get wrong: the stylesheet's dark block is guarded by
#: `:root:not([data-theme="light"])`, so a default of "light" that rendered *nothing*
#: would still hand a dark-desktop reader the dark palette. The default has to assert
#: itself to be a default at all.
DEFAULT: Final[str] = "light"

#: The three states, in the order the control offers them.
#:
#: Light first, because it is what a reader who has not chosen is already looking at,
#: and a control whose first entry is not the current state reads as though something
#: has been changed. The closed set is also what makes a cookie safe to render into an
#: attribute: a value from outside it is discarded rather than escaped, so nothing a
#: client sends reaches the markup at all.
THEMES: Final[tuple[str, ...]] = (DEFAULT, "dark", AUTO)

#: What the control calls each one.
#:
#: Declared beside the vocabulary rather than in the template, so a fourth state --
#: if one is ever added -- cannot reach the page without a name. A template looping
#: over `THEMES` and titling each value would render whatever string it was given.
THEME_LABELS: Final[dict[str, _StrPromise]] = {
    "light": _("Light"),
    "dark": _("Dark"),
    AUTO: _("Auto"),
}

#: How long a choice is remembered: a year, in seconds.
#:
#: Long, because the alternative is a reader re-picking dark every session, and a
#: preference nobody has to think about is the whole point. Nothing sensitive is in it
#: -- it is one of three words -- so there is no expiry argument pulling the other way.
THEME_COOKIE_MAX_AGE: Final[int] = 365 * 24 * 60 * 60


def theme_of(request: HttpRequest) -> str:
    """Return the theme this reader chose.

    Args:
        request: The request, whose cookies carry the choice.

    Returns:
        One of `THEMES`. `DEFAULT` for a reader who has not chosen, and for a cookie
        holding anything else -- a cookie is client-supplied, and the closed set is
        what keeps an arbitrary string out of the rendered attribute.

    """
    chosen = request.COOKIES.get(THEME_COOKIE, DEFAULT)
    return chosen if chosen in THEMES else DEFAULT


def asserted_theme(request: HttpRequest) -> str:
    """Return what the document element's `data-theme` should say, if anything.

    Args:
        request: The request.

    Returns:
        The chosen theme, or the empty string for `AUTO` -- which the template renders
        as *no attribute at all*. That absence is the mechanism rather than a
        shortcut: `prefers-color-scheme` only decides when nothing has overridden it,
        so writing `data-theme="auto"` would take the decision away from the machine
        and give it to a value the stylesheet has no rule for.

        Everything else, including the default, renders. A default that stayed silent
        would not be a default: the dark media block is guarded by
        `:root:not([data-theme="light"])`, and a dark-desktop reader who has chosen
        nothing would get dark.

    """
    chosen = theme_of(request)
    return "" if chosen == AUTO else chosen
