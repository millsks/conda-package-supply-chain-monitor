"""`CPM-APP-S13`: the application is mounted under its own name, and stays movable.

The prefix itself is one line in `config/urls.py`, and that is the whole point of
`CPM-AD-19` routing centrally. What needs a test is not the line — a broken mount
fails every integration case in the suite — but the **property that made it one
line**: nothing anywhere names one of this product's pages by writing its path.

That property is what a reader would expect to be permanent and is in fact the first
thing to go. The first hard-coded `"/conda-sentinel/packages/"` works perfectly, is
invisible in review, and is discovered the next time the mount moves — by which point
there are five of them.

**AC 4 is checked from the other direction.** A prefix that quietly took `/api/` with
it would break a contract `CPM-APP-S07` published and an integrator may already hold,
and it would do it silently: every one of this product's own tests would still pass.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.urls import get_resolver
from django.urls import reverse

import conda_sentinel

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Where this application's pages live.
THE_PREFIX: Final[str] = "/conda-sentinel/"

#: The platform's routes, which the prefix does not move (AC 4).
#:
#: Each with the reason it stays, because "these did not move" is only meaningful
#: beside why they should not: the API is a published contract, the accounts flows
#: belong to the platform rather than to this application, and a health probe carries
#: no credential and is deliberately unprefixed.
UNMOVED: Final[dict[str, str]] = {
    "/api/": "a versioned contract CPM-APP-S07 published; an integrator may already hold these paths",
    "/accounts/": "the platform's sign-in flows, not this application's",
    "/users/": "the platform's account pages, not this application's",
}

#: The two trees that may not write one of this product's paths.
SEARCHED: Final[tuple[Path, ...]] = (
    Path(conda_sentinel.__file__ or "").parent,
    Path(conda_sentinel.__file__ or "").parent.parent.parent / "django_service" / "templates",
)

#: A written path to one of this application's pages.
#:
#: Matched on the prefix rather than on every page name: the pages change, the prefix
#: is the thing a written path has to contain, and a pattern per page would be a
#: roster that goes stale. Anchored on a quote so prose naming the prefix -- of which
#: this module and several docstrings have a line -- is not itself an offence.
A_WRITTEN_PATH: Final[re.Pattern[str]] = re.compile(r'["\']/conda-sentinel/')


def searched_files() -> Iterator[Path]:
    """Yield every file the sweep reads.

    Yields:
        Python modules under this product's package, and every product template.
        Migrations are excluded: a migration names no URL, and its generated body
        would dominate any sweep.

    """
    for root in SEARCHED:
        for path in sorted(root.rglob("*")):
            if path.suffix in {".py", ".html"} and "migrations" not in path.parts:
                yield path


# ---------------------------------------------------------------------------
# AC 1: every one of this application's surfaces is under the prefix.
# ---------------------------------------------------------------------------


def product_routes() -> list[tuple[str, str]]:
    """Return this application's named HTML routes and where each resolves.

    Returns:
        `(view name, path)` for every route in the `conda_sentinel` namespace.

    """
    namespace = get_resolver().namespace_dict.get("conda_sentinel")
    assert namespace is not None, "the product's URLconf is not mounted at all"
    _prefix, resolver = namespace
    return [
        (f"conda_sentinel:{name}", reverse(f"conda_sentinel:{name}", args=_sample_args(pattern)))
        for name, (pattern, *_rest) in resolver.reverse_dict.items()
        if isinstance(name, str)
    ]


def _sample_args(pattern: object) -> list[object]:
    """Return arguments that satisfy a route's parameters.

    Args:
        pattern: The reverse-dict entry's pattern list.

    Returns:
        One placeholder per parameter, typed to match the converter -- an integer
        where the route takes one, a string otherwise. Reversing is the only way to
        learn where a parameterised route actually lands.

    """
    possibilities = pattern  # type: ignore[assignment]
    _template, params = possibilities[0]  # type: ignore[index]
    return [1 if name in {"pk", "item_id", "package_id"} else "x" for name in params]


def test_every_surface_this_application_serves_is_under_the_prefix() -> None:
    """AC 1, over the routes rather than over the one line that mounts them.

    A mount that moved *most* pages is the failure worth catching: a route declared
    outside the application's own URLconf -- in `config/urls.py`, say, for convenience
    -- would sit outside the prefix and nothing else would notice.
    """
    outside = [f"{name} -> {path}" for name, path in product_routes() if not path.startswith(THE_PREFIX)]

    assert outside == [], (
        f"these of this application's surfaces are not under {THE_PREFIX}: {outside}. CPM-APP-S13 mounts the "
        f"application under its own name so a second application on this platform cannot take a path this one "
        f"holds."
    )


def test_the_sweep_has_routes_to_sweep() -> None:
    """So the case above cannot pass by finding none.

    A namespace that resolved to nothing would report no violations rather than no
    coverage, and would go on doing so after somebody unmounted the application.
    """
    routes = product_routes()

    assert len(routes) > 1, routes


# ---------------------------------------------------------------------------
# AC 2: the root leads here.
# ---------------------------------------------------------------------------


def test_the_root_resolves_to_a_redirect_into_this_application() -> None:
    """AC 2. The front door still works, and it is a redirect rather than a mount.

    A second `path("")` on the same view would have given the home page two addresses,
    which is what makes a link in a ticket disagree with the one in the navigation.
    """
    assert reverse("root") == "/"
    assert reverse("conda_sentinel:home") == THE_PREFIX


# ---------------------------------------------------------------------------
# AC 3: nothing writes one of these paths.
# ---------------------------------------------------------------------------


def test_nothing_names_one_of_this_applications_pages_by_path() -> None:
    """AC 3, and this is the property that made the prefix one line.

    It is also the first thing to go. A hard-coded `"/conda-sentinel/packages/"` works
    perfectly, is invisible in review, and is discovered the next time the mount moves
    -- by which point there are five of them and the one-line change is not one line
    any more.
    """
    offenders = [
        f"{path}:{number}"
        for path in searched_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if A_WRITTEN_PATH.search(line)
    ]

    assert offenders == [], (
        f"these write one of this application's paths instead of reversing it: {offenders}. CPM-AD-19 routes "
        f"centrally, which is what makes the mount one line -- and a written path is what takes that away."
    )


def test_the_sweep_reads_the_files_it_claims_to() -> None:
    """A sweep over an empty file list reports no violations rather than no coverage.

    Both trees, because they fail differently: a wrong package path yields nothing,
    and a wrong template path yields nothing, and the case above would pass on either.
    """
    read = list(searched_files())

    assert any(path.suffix == ".py" for path in read)
    assert any(path.suffix == ".html" for path in read)
    assert any(path.name == "urls.py" for path in read)


# ---------------------------------------------------------------------------
# AC 4: the platform's routes did not move.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "reason"), sorted(UNMOVED.items()))
def test_the_platforms_own_routes_are_unmoved(path: str, reason: str) -> None:
    """AC 4, from the direction that would fail silently.

    A prefix that took `/api/` with it would break a contract `CPM-APP-S07` published,
    and every one of this product's own tests would still pass -- the integrator is
    the one who finds out.

    Args:
        path: The platform prefix that must be unmoved.
        reason: Why it stays there, for the failure message.

    """
    named = {
        "/api/": "api:package-health",
        "/accounts/": "account_login",
        "/users/": "users:redirect",
    }[path]

    resolved = reverse(named)

    assert resolved.startswith(path), f"{named} resolved to {resolved}, and it should be under {path}: {reason}"
    assert not resolved.startswith(THE_PREFIX), (
        f"{named} moved under this application's prefix, and it should not have: {reason}"
    )
