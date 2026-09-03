"""The local sign-in route's name and path prefix, declared exactly once.

AD-21 fixes both as constants and requires them to be *declared* in one place:
"its URL name and path prefix are fixed constants". Every other module -- the
package's own URLconf, the project URLconf, the views, the tests -- imports
these names rather than spelling them, so a rename is one edit and a second
declaration site is a test failure rather than a discovery.

**These two constants move into `accelerator.toml` in Epic 7 without changing
their meaning.** epics.md records the sequencing: they are among the declarations
"authored in a single module in an earlier epic and moved into `accelerator.toml`
in Epic 7". This module is that single module, and the move is a relocation of
the declaration rather than a redefinition of it -- which is why both are plain
module-level strings with no computation, no environment read and no settings
lookup. Anything derived here would have to be re-derived there, and a value that
is re-derived is a value that can come out different.

**Why the prefix is not under `accounts/`.** AD-21 uses that exact case as its
worked failure: a local sign-in route mounted under `/accounts/` "would otherwise
satisfy this AD and pass an allowlist that already permits `/accounts/` for
allauth". The prefix is therefore its own segment, sharing nothing with the
allauth mount, so the component's own credential path is enumerable separately
from the identity provider's.

The prefix is only ever half the story. Epic 4's stage-2 predicate refuses this
route by resolving the view callable's owning module (AD-26), never by matching
either of these strings, because a rename would defeat a string match while the
route stayed live.
"""

from __future__ import annotations

from typing import Final

__all__ = ["LOCAL_SIGNIN_PATH_PREFIX", "LOCAL_SIGNIN_URL_NAME"]

#: The URL name the sign-in route is reversible by. The index route is named
#: from it rather than declared beside it, so the two cannot drift apart.
LOCAL_SIGNIN_URL_NAME: Final[str] = "local_persona_signin"

#: The path prefix the package's URLconf is included at, trailing slash
#: included, as `path()` expects. Its own segment, sharing nothing with the
#: allauth mount, and deliberately not a segment any deployed component has a
#: reason to serve. The leading underscore is a *convention* that makes an
#: accidental collision with a tenant app's routes unlikely, and nothing more:
#: URL routing reserves no character, so a tenant app remains free to mount this
#: prefix and shadow it. Epic 4's enumeration of the credential surface is what
#: would notice.
LOCAL_SIGNIN_PATH_PREFIX: Final[str] = "_local/"
