"""The django_service application package.

The version is derived from git tags at build time by hatch-vcs, so it is read
back from the installed distribution metadata rather than hardcoded here.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version

try:
    __version__ = version("conda-package-supply-chain-monitor")
except PackageNotFoundError:  # not installed, e.g. a bare checkout
    __version__ = "0.0.0"

__version_info__ = tuple(int(num) if num.isdigit() else num for num in __version__.replace("-", ".", 1).split("."))
