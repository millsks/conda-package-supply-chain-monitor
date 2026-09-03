"""The runnable entry point: `python -m config.local_dev.mint <persona-key>`.

Invoked as `pixi run -e dev mint-token <persona-key>`. The `-e dev` is not
optional and it is not a convenience: locality is declared once, in
`[feature.dev.activation.env]` (AD-13 as amended), so the `dev` environment is
what carries `COMPONENT_RUNTIME=local`. A bare `pixi run mint-token` resolves in
`default`, which declares nothing, reads *deployed*, and is refused before a key
is generated or a claim is built. That is the refusal working, not a bug.

**Not a management command**, for the reason `config/local_dev/seed.py` gives: a
management command has to live inside an installed app, the only installed app
package is `django_service`, and `django_service` importing `config.local_dev`
would invert AD-4's dependency direction.

The token is emitted as a structured log event rather than written to stdout on
its own. That is the project rule (`print` is never used), and it also means the
one thing a developer copies out of the terminal is labelled -- a bare line of
base64 in a scrollback is indistinguishable from any other bare line of base64.
"""

from __future__ import annotations

import os
import sys
from typing import Final

import django
import structlog

__all__ = ["main"]

# Named rather than taken from `__name__`: run as `python -m`, this module's
# `__name__` is `__main__`, and a log aggregator would file the minted-token
# event under a name that identifies nothing.
logger: structlog.stdlib.BoundLogger = structlog.get_logger("config.local_dev.mint")

#: What to say when the persona was not named. A `SystemExit` with a usage line
#: rather than a traceback: an omitted argument is a typing mistake, not a
#: contract violation, and the two should not look alike.
_USAGE: Final[str] = "usage: pixi run -e dev mint-token <persona-key>"


def main(argv: list[str] | None = None) -> str:
    """Set up Django, ensure the keypair exists, and mint a token for one persona.

    Args:
        argv: The arguments after the module name. Read from `sys.argv` when
            omitted, which is what the task invocation does; passed explicitly by
            the suite.

    Returns:
        The encoded token, so a caller that imported this rather than running it
        has the value and not only the log line.

    Raises:
        SystemExit: No persona key was given, or the one given is not declared.
        ImproperlyConfigured: The run is not local. Propagated rather than
            rendered as a message and a non-zero exit, for the reason
            `config/local_dev/seed.py` gives: the traceback names the refusal and
            the variable.

    """
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        raise SystemExit(_USAGE)
    persona_key = arguments[0]

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    django.setup()

    # After `django.setup()`: `config.local_dev.tokens` reaches the personas,
    # which reach the mapper, which imports a model -- and a model import before
    # setup is `AppRegistryNotReady`.
    from config.local_dev.keys import ensure_keypair  # noqa: PLC0415 - see above
    from config.local_dev.personas import UnknownPersonaError  # noqa: PLC0415 - see above
    from config.local_dev.personas import persona_keys  # noqa: PLC0415 - see above
    from config.local_dev.tokens import mint_token  # noqa: PLC0415 - see above

    keypair = ensure_keypair()
    try:
        token = mint_token(persona_key)
    # The same reasoning as the missing-argument case above, applied to a
    # mistyped one. `UnknownPersonaError` is a bare `LookupError`, so uncaught it
    # reaches the developer as `LookupError: stff` under a stack through
    # `django.setup()` -- from which they cannot tell whether they mistyped,
    # whether the persona was removed, or whether something is broken. The list
    # of valid keys is one call away, so answer the question rather than posing
    # it. The locality refusal above is deliberately *not* caught this way: that
    # one is a contract violation and reads correctly as a traceback.
    except UnknownPersonaError as unknown:
        message = f"no persona is declared as {persona_key!r}. Declared personas: {', '.join(persona_keys())}"
        raise SystemExit(message) from unknown
    logger.info("local_dev.minting_complete", persona=persona_key, kid=keypair.kid, token=token)
    return token


if __name__ == "__main__":
    main()
