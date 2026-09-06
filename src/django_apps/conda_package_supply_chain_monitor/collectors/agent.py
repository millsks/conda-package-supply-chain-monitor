"""What this product calls itself on the wire, declared once for every collector.

Every source `CPM-EP-CURRENCY` reads asks for a `User-Agent`, and some enforce
one: GitHub requires it and asks that it identify the caller, PyPI asks the same
of anything that reads its JSON API at volume. A source owner deciding whether
to block a caller, and an operator reading an access log, both need to know
*which deployment* issued a request rather than only which product -- so the
identity carries the distribution name, the version the running build reports,
and a way to reach the owner, which is the form GitHub's own guidance asks for
and the form every other well-behaved crawler uses.

**It is here rather than in the first collector that needed it, and that is
`CPM-AD-7`'s doing.** A collector "never imports another collector", so the
second collector could not have read the string off the first; a second copy
would have been two spellings of one identity, drifting apart on the day one of
them was edited. Shared pieces move to a shared home, and this is the home for
the one every collector's `headers` declaration reads.

**The distribution name is spelled here rather than imported from
`django_service.__init__`**, which reads the same metadata: a domain application
importing the reference application would invert the dependency direction the
second import root exists to keep straight, for one string and a `try`.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version
from typing import Final

__all__ = [
    "DISTRIBUTION_NAME",
    "PROJECT_URL",
    "UNKNOWN_VERSION",
    "USER_AGENT",
    "distribution_version",
]

#: This product's distribution name, its home, and the version to report when the
#: distribution metadata cannot be found. The name is `pyproject.toml`'s
#: `[project] name`.
DISTRIBUTION_NAME: Final[str] = "conda-package-supply-chain-monitor"
PROJECT_URL: Final[str] = "https://github.com/millsks/conda-package-supply-chain-monitor"
UNKNOWN_VERSION: Final[str] = "0.0.0"


def distribution_version() -> str:
    """Return this product's version, as the installed distribution reports it.

    Returns:
        The version `hatch-vcs` derived from the git tag at build time, or
        `UNKNOWN_VERSION` in a checkout that was never installed. The fallback is
        a real state rather than a defensive one -- a source tree imported without
        an editable install has no distribution metadata -- and it is exercised
        rather than pragma'd out, on the terms `tests/unit/test_package_version.py`
        argues for the same fallback in `django_service`.

    """
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return UNKNOWN_VERSION


#: What every collector calls itself on the wire: the distribution name, the
#: version the running build reports, and a way to reach the owner. Declared by
#: each collector in its `headers`, merged and sent by the base, never by a
#: collector itself (`CPM-AD-20`, `CPM-AD-27`).
USER_AGENT: Final[str] = f"{DISTRIBUTION_NAME}/{distribution_version()} (+{PROJECT_URL})"
