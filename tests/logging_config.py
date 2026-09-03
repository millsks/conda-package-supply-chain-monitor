"""What "the component manages no log files" means, stated once.

Both `tests/unit/test_observability_logging.py` -- over the dictionaries
`build_logging_config` returns for its callers -- and `tests/unit/test_settings.py`
-- over the one `config/settings/production.py` builds and then amends for
itself -- assert this property. Two copies of the answer to "what counts as a
file handler" would be two answers waiting to drift apart, and the deployed
configuration is the only one where the difference would matter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

#: Substrings of every stdlib handler class that opens a file, rotates one, or
#: hands records to a syslog daemon. Matched on the class name rather than on an
#: allow-list of one, so a handler added later is caught by what it does.
FILE_HANDLER_MARKERS = ("File", "Rotating", "Watched", "SysLog")


def assert_writes_no_files(config: dict[str, Any]) -> None:
    """Assert no handler in a built logging configuration writes to a file.

    Args:
        config: A `logging.config.dictConfig` mapping, as `build_logging_config`
            returns it or as a settings module amends it.

    """
    for name, handler in config["handlers"].items():
        handler_class = str(handler.get("class", ""))
        offending = [marker for marker in FILE_HANDLER_MARKERS if marker in handler_class]
        assert not offending, f"handler {name!r} is a file handler: {handler_class}"
        assert "filename" not in handler, f"handler {name!r} names a file: {handler.get('filename')!r}"
