"""The component is a payload, and these are the properties that make it one (FR-38, FR-39).

A payload starts from environment variables alone, under a UID the image has
never seen, on a read-only root filesystem, and writes nothing outside a
temporary directory. AD-15 states those as properties **of the application**
rather than of any image: materialized components ship no Dockerfile at all, so
there is no per-component build in which to fix a component that lacks them. A
component either fits the platform's image pipeline or it acquires an opt-out
from it, which is the failure AD-15 exists to prevent -- a base-image CVE bump
becoming N pull requests.

This repository ships a `Dockerfile` as `machinery` precisely so the claim can be
run rather than believed. `tests/integration/test_image_payload.py` builds it and
drives it under `--user 12345:0 --read-only --tmpfs /tmp`; this module holds the
half that needs no Docker at all -- what the file *declares*, and what the
settings it runs under *resolve to*.

**The stage that ships is the stage that is read.** The payload assertions below
run over `final_stage(...)` rather than over every instruction in the file. A
`USER 1001` and an `ENV HOME=/tmp` in a discarded builder stage say nothing about
the image that ships, and a flat read of a multi-stage file would accept both
while the final stage ran as root with `HOME=/`. The migration scan in
`tests/unit/test_release_stage.py` deliberately does the opposite and reads every
stage, because a migration in a builder stage is still a migration (AD-22 holds
"at any depth"). Two questions, two readings, one parser.

The `COPY`/`ADD` scan is the one payload assertion that also reads every stage.
A configuration file that entered a builder stage is one `COPY --from=` away from
the final image, and the whole point of an enumerated `COPY` is that nothing
decides what enters by accident.

**AC #3 is four legs, and each of them is asserted somewhere.**

* *Static files are collected at build and served by the application.* The
  `Dockerfile` runs `collectstatic` at build time and
  `whitenoise.middleware.WhiteNoiseMiddleware` serves the result, so nothing
  writes to `STATIC_ROOT` at run time and no sidecar or shared volume is needed.
  The build-time collection is asserted here directly -- deleting that `RUN`
  would otherwise pass this whole module -- and proven by the integration module,
  which finds `staticfiles/` already populated in a container that has written
  nothing.
* *User media is a non-goal.* FR-25 puts it out of scope, and the settings still
  declare `MEDIA_ROOT`, `MEDIA_URL` and a `static()` media route. That is a
  recorded residue rather than a contradiction this story resolves -- see
  `test_no_resolved_route_serves_anything_out_of_media_root` below, which asserts
  what is actually true today, against this repository's own URLconf.
* *Logs go to the event stream.* Structured JSON on stdout, no files and no
  rotation (Consistency Conventions). Asserted on the *resolved handler classes*
  rather than on a string, because a `LOGGING` dict is data and a substring
  search over it would pass a handler class that merely spells itself
  differently.
* *Sessions are database-backed.* This module asserts the property AC #2 depends
  on -- the resolved store *is* the database store, so nothing is written to
  local disk and nothing is per-replica.
  `tests/unit/test_session_settings.py` owns the declaration side: that
  `SESSION_ENGINE` is set in `base.py`, once, in no other settings module, and
  outside every AD-24 region.

**The `MEDIA_ROOT` residue, recorded rather than fixed.** `MEDIA_ROOT` is
`str(APPS_DIR / "media")` and `src/config/urls.py` mounts
`static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)` at the end of
`urlpatterns`. Read as a declaration, that is a writable path inside the source
tree, which contradicts AC #2. Read as behaviour, it is inert in a deployed
component -- `django.conf.urls.static.static` returns an empty list whenever
`DEBUG` is false, so this repository's *resolved* `urlpatterns` mount no media
route, and no model in any installed application declares a `FileField`, so the
`default` `FileSystemStorage` is never asked to write anything anywhere. Both
halves are asserted below. Removing the `MEDIA_*` surface belongs to Epic 7's
object-storage story under FR-25; this module's job is to make the residue loud
rather than to take that decision.

**Disposition `machinery`, and this is the one place in Epic 5 where that is
true.** Every other test module in this epic is `core` and runs inside every
materialized combination's gate. This one cannot: its subject is the
`Dockerfile`, which never travels (AD-15), so a materialized component would run
it against a file that is deliberately not there. It is `machinery` for the same
reason its subject is, and Epic 7 lists both explicitly in `accelerator.toml` --
AD-2's input reconciliation fails a path claimed by no disposition, and defaulting
to `machinery` is not the same as declaring it.

These are unit tests. They read two repository files and import settings modules;
no Docker, no network, no database.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import re
import shlex
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.apps import apps
from django.conf import settings as active_settings
from django.db import models
from django.urls import Resolver404
from django.urls import get_resolver
from django.urls import resolve
from django.utils.module_loading import import_string

from config.locality import LOCAL as LOCAL_RUNTIME
from config.locality import RUNTIME_ENV_VAR
from tests.dockerfile import DOCKERFILE
from tests.dockerfile import DOCKERIGNORE
from tests.dockerfile import EXECUTING_INSTRUCTIONS
from tests.dockerfile import final_stage
from tests.dockerfile import instruction_lines
from tests.payload import BUILD_SCAFFOLDING_VARIABLES
from tests.payload import DOT_ENV_TOGGLE
from tests.payload import SETTINGS_PREFIX
from tests.payload import is_configuration_name
from tests.pixi_manifest import REPO_ROOT
from tests.settings_import import BASE_SETTINGS
from tests.settings_import import LOCAL_SETTINGS
from tests.settings_import import PRODUCTION_SETTINGS
from tests.settings_import import SETTINGS_MODULES
from tests.settings_import import TEST_SETTINGS
from tests.settings_import import evicted_settings_modules
from tests.settings_import import import_settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

# The temporary directory the platform mounts, and the only path this payload is
# permitted to write to. Written once, as the policy it is, rather than as a
# literal at each assertion.
TEMPORARY_DIRECTORY: Final[str] = "/tmp"  # noqa: S108

# The two modules that are imported under a *local* runtime, because that is the
# only runtime they are ever loaded under. `local.py` is what stage-1 condition 1
# refuses by name, and both it and `test.py` keep `ModelBackend` in
# `AUTHENTICATION_BACKENDS`, which condition 2a refuses -- correctly, and only
# when the run declares itself deployed. Importing them as if they were deployed
# would be asserting that a local settings module passes the deployed contract,
# which is a claim Epic 4 spends nine conditions denying.
#
# Nothing below depends on the choice: `LOGGING` is composed from the same
# `build_logging_config` call whichever runtime is declared, and locality is read
# by the refusal contract rather than by the logging configuration.
LOCAL_RUNTIME_SETTINGS: Final[frozenset[str]] = frozenset({LOCAL_SETTINGS, TEST_SETTINGS})

# The environment a *deployed* `config.settings.production` import needs, which
# is the stage-1 roster plus the two values `production.py` reads directly. It is
# the same set the Dockerfile supplies inline on its `collectstatic` line, and
# that is not a coincidence: the build has to satisfy the refusal contract for
# the same reason a deployment does, because `run_stage_one` is the last
# statement of the module either one imports.
#
# The names come from `tests/payload.py` rather than being written again here,
# so this module and the integration module cannot disagree about what the
# roster is; only the values are local, and they resolve nowhere on purpose.
# `.invalid` is reserved by RFC 2606, and the stage-1 trust-anchor condition is
# syntactic (AD-23), so nothing fetches this -- a fetchable value would only
# invite a test that fetched it.
DEPLOYED_ENVIRONMENT: Final[dict[str, str]] = {
    "DJANGO_SECRET_KEY": "x" * 50,
    "DJANGO_ADMIN_URL": "probe-admin/",
    "DATABASE_URL": "postgres://user:pw@db:5432/app",
    "COMPONENT_OIDC_ISSUER": "https://idp.example.invalid/realms/component",
    "COMPONENT_IDENTITY_CLAIM": "sub",
    "COMPONENT_GROUP_CLAIM": "groups",
    "COMPONENT_STAFF_GROUP": "platform-staff",
    "COMPONENT_SUPERUSER_GROUP": "platform-superuser",
}

# The instruction that declares who the container runs as, and the two values
# that mean root -- by name and by number. A platform assigns an arbitrary UID
# and this value is the floor rather than the expectation, but a floor of root is
# not a floor.
USER_INSTRUCTION: Final[str] = "USER"
ROOT_IDENTITIES: Final[frozenset[str]] = frozenset({"root", "0"})

# The instruction that declares a writable path the component depends on. AC #2
# permits exactly one, and in practice this file declares none: the platform
# mounts `/tmp` as a tmpfs and needs no declaration to do it.
VOLUME_INSTRUCTION: Final[str] = "VOLUME"

# The instruction that sets image environment, and the variable an arbitrary UID
# has no answer for. There is no `/etc/passwd` entry for a platform-assigned UID,
# so `getpwuid` fails and every tool resolving `$HOME` falls back to `/` -- which
# is read-only. `HOME` under the temporary directory is what keeps that from
# being a start-up failure.
ENV_INSTRUCTION: Final[str] = "ENV"
HOME_VARIABLE: Final[str] = "HOME"

# The instruction that declares where the application lives, read rather than
# written as a literal: the group-0 assertion below has to name the tree it is
# about, and deriving it from `WORKDIR` means renaming the directory moves the
# assertion with it instead of quietly emptying it.
WORKDIR_INSTRUCTION: Final[str] = "WORKDIR"

# The two instructions that bring files into the image. `ADD` is here because it
# is `COPY` with more reach, not less: `ADD .env ./` and `ADD https://host/
# settings.ini /app/` both put a configuration file in the image, and a scan that
# read only `COPY` would walk past either.
FILE_INSTRUCTIONS: Final[frozenset[str]] = frozenset({"COPY", "ADD"})

# A source that is the whole build context, or a directory. Both defeat a scan
# that matches on the final path component: `COPY . .` names nothing and carries
# everything, and `COPY deploy/ /app/` carries whatever is inside `deploy/`.
#
# The point of the Dockerfile's enumerated `COPY` is that the enumeration is the
# assertion's subject -- `.dockerignore` is a second line of defence and not the
# thing deciding what enters the image. So a directory source is refused unless
# it is named here, and exactly one is: the source root, which is what the image
# is.
WHOLE_CONTEXT_SOURCES: Final[frozenset[str]] = frozenset({".", "./", "..", "../", "/", "*"})
SOURCE_ROOT: Final[str] = "src"
PERMITTED_DIRECTORY_SOURCES: Final[frozenset[str]] = frozenset({SOURCE_ROOT})
STAGE_SOURCE_FLAG: Final[str] = "--from="

# The build-stage step whose absence would make three assertions in this module
# vacuous, matched as a word. AC #3's static leg lives on it: `collectstatic` at
# build is what makes `STATIC_ROOT` read-only at run time, and deleting the
# instruction would leave "no ENV bakes the build scaffolding" true because
# nothing supplies any.
COLLECTSTATIC_INVOCATION: Final[re.Pattern[str]] = re.compile(r"(?<![\w.-])collectstatic(?![\w.-])")

# How an arbitrary UID reaches a tree it was never named in, matched on the
# instruction that grants it rather than assumed from the fact that the container
# starts. It would start anyway: the default 0755 on a root-owned tree already
# lets any UID read it, so removing both instructions below breaks nothing
# visible and quietly ends the arbitrary-UID claim for any file the build creates
# with a tighter mode.
#
# The mode is asserted as well as the group, and that is the half AC #2 needs.
# `g=u` copies the *owner's* bits, and for a root-owned tree that includes write
# -- so an arbitrary UID in group 0 could rewrite the application it is running,
# on an image whose comment says "read access, not write". `g=rX` is the mode
# that means what the comment says: read everywhere, execute only where the owner
# has it, which is what the conda environment's binaries and directories need.
GROUP_ZERO_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"\bchgrp\s+(?:-\S+\s+)*0\s+(\S+)")
GROUP_MODE_GRANT: Final[re.Pattern[str]] = re.compile(r"\bchmod\s+(?:-\S+\s+)*g=([A-Za-z]*)\s+(\S+)")
READ_MODE_LETTER: Final[str] = "r"
PERMITTED_GROUP_MODE_LETTERS: Final[frozenset[str]] = frozenset({"r", "x", "X"})

# What `.dockerignore` must keep out of the build context, and why each one is
# load-bearing rather than tidy. An enumerated `COPY` cannot bring in what never
# reached the context, and these are the entries whose removal would put local
# state within reach of one: the git history hatch-vcs would read, the two
# configuration families, the generated signing keypair, the local database, and
# the byte-code caches that exist under `src/` in any tree that has run the
# suite.
#
# Spelled exactly as the file spells them, `**/` forms included, because the
# `**/` is the part that is easy to lose: a `.dockerignore` pattern is matched
# against the path relative to the context root, so a bare `.env` excludes `.env`
# and not `src/config/.env`.
REQUIRED_DOCKERIGNORE_ENTRIES: Final[tuple[str, ...]] = (
    ".git/",
    ".env",
    "**/.env",
    ".env.*",
    "**/.env.*",
    ".envs/",
    "**/.envs/",
    ".local-dev-keys/",
    "db.sqlite3",
    "__pycache__/",
    "**/__pycache__/",
)

# The session backend a deployed component resolves to, named by module so the
# store class can be compared rather than the dotted string. AC #2's
# zero-writable-path claim is about behaviour, and the behaviour is the store
# class's -- an engine reached under a different dotted name that resolved to the
# same store would be the same answer, and one that resolved to a different store
# would be a different answer whatever it was called.
DATABASE_SESSION_BACKEND: Final[str] = "django.contrib.sessions.backends.db"

# The dictConfig keys a handler can declare its implementation under, and the
# stdlib base class every file-writing handler in the standard library derives
# from -- `RotatingFileHandler`, `TimedRotatingFileHandler` and
# `WatchedFileHandler` included. Asserting on the resolved class rather than on
# the string is what makes that inheritance count.
#
# **Both keys, because `dictConfig` honours both.** `{"()": "logging.handlers.
# RotatingFileHandler", "filename": ...}` is a handler that writes a file, and a
# reader that looked only at `class` would drop it silently. The `()` idiom is
# already live in this repository -- `src/config/settings/production.py` declares
# `require_debug_false` with it -- so this is a spelling the codebase uses, not
# one it might.
#
# `logging` is imported here to *inspect* a class, which is the one use of it
# this project has: nothing in `src/` emits through the standard library, and
# `config/observability/logging.py` builds a structlog pipeline whose only
# handler is a `StreamHandler` on stdout.
HANDLER_CLASS_KEY: Final[str] = "class"
HANDLER_FACTORY_KEY: Final[str] = "()"
HANDLERS_KEY: Final[str] = "handlers"
FILE_HANDLER_BASE: Final[type[logging.Handler]] = logging.FileHandler

# The applications a deployed component installs that the suite's own registry
# does not, and the reason the `FileField` scan below can still claim to cover
# "every installed application". `production.py` appends `anymail`, so a scan of
# the *test* settings' registry is a scan of a smaller set than the one that
# ships.
#
# Recorded by name rather than accommodated silently, and paired with a proof:
# the case below requires each of these to ship no `models` module at all, so an
# application that starts declaring models fails here rather than going unscanned
# behind a claim in a docstring.
PRODUCTION_ONLY_APPLICATIONS: Final[frozenset[str]] = frozenset({"anymail"})
MODELS_MODULE: Final[str] = "models"

# The view `django.conf.urls.static.static` mounts, and the keyword it is given
# the directory under. Asserted against the resolved URLconf rather than by
# calling `static()` here: calling it would assert a property of *Django*, and
# `src/config/urls.py` could mount an unconditional `serve` on the next line
# without this module noticing.
DOCUMENT_ROOT_KEYWORD: Final[str] = "document_root"
MEDIA_PROBE_FILENAME: Final[str] = "payload-probe.txt"

# A multi-stage file whose builder stage satisfies every payload assertion and
# whose final stage satisfies none of them. The parser's stage awareness is the
# only thing between this shape and a green module, and the real `Dockerfile` is
# single-stage -- so nothing else in this file would notice a `final_stage` that
# had stopped splitting.
MULTI_STAGE_DOCKERFILE: Final[str] = (
    "FROM example/base:1 AS builder\n"
    "USER 1001\n"
    "ENV HOME=/tmp\n"
    "WORKDIR /app\n"
    "\n"
    "FROM example/base:1\n"
    "WORKDIR /app\n"
    "USER root\n"
    "ENV HOME=/\n"
    "VOLUME /var/lib/component\n"
)


@pytest.fixture(scope="module")
def instructions() -> list[tuple[int, str, str]]:
    """Return every parsed instruction in the Dockerfile, across every stage.

    Read through `tests/dockerfile.py` rather than by a second parse, so this
    module and `tests/unit/test_release_stage.py` cannot disagree about what an
    instruction is -- a continuation, a heredoc body or an `ONBUILD` prefix read
    differently by two readers is a line one of them never scans.

    A missing file yields no instructions rather than an error. Reading it here
    would make every case in this module fail during *setup* with a
    `FileNotFoundError`, including the one case written to explain what a missing
    `Dockerfile` means -- so the guard that carries the AD-15 message would never
    be the thing that reported it.

    Returns:
        One entry per instruction as (line number, instruction, arguments), and
        an empty list when the file is absent.
    """
    if not DOCKERFILE.is_file():
        return []
    return instruction_lines(DOCKERFILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def payload_instructions(instructions: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    """Return the instructions of the stage the image actually ships.

    Args:
        instructions: Every parsed instruction in the file.

    Returns:
        The instructions from the last `FROM` onward -- see this module's
        docstring for why the payload properties are read off that stage and the
        migration scan is not.
    """
    return final_stage(instructions)


@pytest.fixture(autouse=True)
def _evict_settings_modules() -> Iterator[None]:
    """Drop freshly imported settings modules around each case, and restore structlog.

    The body lives in `tests/settings_import.py` because
    `tests/unit/test_settings.py` needs the identical thing, and because the
    structlog half is easy to leave out: `base.py` calls `configure_structlog()`
    at module scope, so a module that re-imports four settings modules across a
    dozen cases silently reconfigures the process-wide pipeline for whatever runs
    after it.

    Yields:
        Control to the test.
    """
    yield from evicted_settings_modules()


def _import_settings(name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import one settings module fresh, under the runtime it is actually loaded in.

    `base.py` and `production.py` are imported with `COMPONENT_RUNTIME` deleted
    rather than set, because absent is how a deployment spells itself and
    locality fails closed (AD-13). `production.py`'s `run_stage_one` call is
    therefore judged by every condition here exactly as it is in the image, which
    is why the roster is supplied at all. `local.py` and `test.py` are imported
    local, for the reason `LOCAL_RUNTIME_SETTINGS` records.

    Args:
        name: The settings module to import.
        monkeypatch: The environment is set through it, so it is restored.

    Returns:
        The freshly imported module.
    """
    return import_settings(
        name,
        monkeypatch,
        environment=DEPLOYED_ENVIRONMENT,
        runtime_variable=RUNTIME_ENV_VAR,
        runtime=LOCAL_RUNTIME if name in LOCAL_RUNTIME_SETTINGS else None,
    )


def _arguments_of(instructions: list[tuple[int, str, str]], instruction: str) -> list[tuple[int, str]]:
    """Return every occurrence of one instruction as (line number, arguments).

    Args:
        instructions: The parsed instructions.
        instruction: The instruction to select, upper-cased.

    Returns:
        The matching entries, in file order.
    """
    return [(number, arguments) for number, head, arguments in instructions if head == instruction]


def _tokens(arguments: str) -> list[str]:
    """Split one instruction's arguments into tokens, in either form Docker permits.

    The JSON-array form (`COPY ["a", "b"]`, `VOLUME ["/tmp"]`) is not shell
    syntax, so it is stripped of its punctuation before splitting rather than
    handed to `shlex` as-is -- which would leave the brackets and quotes attached
    to the first and last token and make every comparison below miss.

    Args:
        arguments: The instruction's arguments, continuations already joined.

    Returns:
        The tokens, with surrounding quotes and JSON punctuation removed.
    """
    stripped = arguments.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1].replace(",", " ")
    try:
        return [token.strip("\"'") for token in shlex.split(stripped)]
    except ValueError:
        # An unbalanced quote is a malformed instruction rather than a payload
        # property, and swallowing the split would silently unscan the line.
        # Returning the raw text keeps whatever it names visible to the callers.
        return [stripped]


def _image_environment(instructions: list[tuple[int, str, str]]) -> dict[str, str]:
    """Return the environment the built image carries, as `ENV` declares it.

    Both spellings are read. The modern form sets any number of `KEY=value`
    pairs in one instruction -- which is what the file uses, across a
    continuation -- and the legacy form sets exactly one variable from `ENV KEY
    value`. A reader that handled only the first would report `HOME` as unset in
    an image that set it the other way.

    Later declarations win, because that is what Docker does.

    Args:
        instructions: The parsed instructions.

    Returns:
        Variable name -> value, for every variable any `ENV` sets.
    """
    environment: dict[str, str] = {}
    for _number, arguments in _arguments_of(instructions, ENV_INSTRUCTION):
        tokens = _tokens(arguments)
        if tokens and "=" not in tokens[0]:
            environment[tokens[0]] = " ".join(tokens[1:])
            continue
        for token in tokens:
            name, separator, value = token.partition("=")
            if separator:
                environment[name] = value
    return environment


def _inline_variables(arguments: str) -> set[str]:
    """Return every variable one shell instruction assigns inline.

    `RUN DJANGO_SECRET_KEY=... pixi run collectstatic` supplies a value for the
    duration of that command and leaves nothing in the image. That is the whole
    distinction between build scaffolding and configuration, and it is only real
    while something asserts that the scaffolding is *there* as well as that it is
    not baked -- an `ENV`-free file that supplies nothing inline satisfies the
    second assertion by having no subject.

    Args:
        arguments: The instruction's arguments.

    Returns:
        The names assigned, which is a superset of the leading assignments: a
        `NAME=value` anywhere in the command is close enough for an assertion
        that the roster is supplied, and narrowing it would only invite a form
        that slipped past.
    """
    assigned: set[str] = set()
    for token in _tokens(arguments):
        name, separator, _value = token.partition("=")
        if separator and name.isidentifier():
            assigned.add(name)
    return assigned


def _application_root(instructions: list[tuple[int, str, str]]) -> str:
    """Return the directory the image declares as its application root.

    Args:
        instructions: The parsed instructions of the shipping stage.

    Returns:
        The last `WORKDIR`'s value, or an empty string when none is declared.
    """
    declared = _arguments_of(instructions, WORKDIR_INSTRUCTION)
    if not declared:
        return ""
    tokens = _tokens(declared[-1][1])
    return tokens[0] if tokens else ""


def _is_inside_temporary_directory(path: str) -> bool:
    """Report whether a path is the temporary directory or lies under it.

    A prefix comparison that requires the separator, so that `/tmpfiles` is not
    read as being inside `/tmp` -- which is the shape of near-miss that makes a
    zero-writable-path assertion pass over a writable path.

    Args:
        path: The path as the Dockerfile spells it.

    Returns:
        True when the path is `/tmp` itself or a descendant of it.
    """
    return path == TEMPORARY_DIRECTORY or path.startswith(f"{TEMPORARY_DIRECTORY}/")


def _copied_sources(instructions: list[tuple[int, str, str]]) -> list[tuple[int, str, bool]]:
    """Return every host path any `COPY` or `ADD` names, with where it came from.

    The last operand of either instruction is the destination inside the image,
    which names nothing about the build context and is not a source this scan is
    about.

    Args:
        instructions: The parsed instructions.

    Returns:
        (line number, source, whether the instruction takes it from another
        build stage) for each source, in file order.
    """
    sources: list[tuple[int, str, bool]] = []
    for number, head, arguments in instructions:
        if head not in FILE_INSTRUCTIONS:
            continue
        tokens = _tokens(arguments)
        flags = [token for token in tokens if token.startswith("--")]
        operands = [token for token in tokens if not token.startswith("--")]
        from_stage = any(flag.startswith(STAGE_SOURCE_FLAG) for flag in flags)
        sources.extend((number, source, from_stage) for source in operands[:-1])
    return sources


def _resolved_handler_classes(
    configuration: dict[str, Any],
) -> tuple[dict[str, type[logging.Handler]], list[str]]:
    """Return each declared log handler's class, imported, and every one that could not be read.

    Args:
        configuration: One settings module's `LOGGING` dictConfig.

    Returns:
        (handler name -> the class it declares, descriptions of the handlers
        whose declaration this scan cannot resolve to a class). The second is
        returned rather than skipped: a handler the scan cannot read is a
        handler the file-based assertion never applied to, which is the silence
        an assertion of absence must not be able to produce.
    """
    handlers = configuration.get(HANDLERS_KEY, {})
    resolved: dict[str, type[logging.Handler]] = {}
    unreadable: list[str] = []
    for name, handler in handlers.items():
        if isinstance(handler, dict):
            declared = handler.get(HANDLER_CLASS_KEY, handler.get(HANDLER_FACTORY_KEY))
        else:
            declared = None
        candidate = import_string(declared) if isinstance(declared, str) else declared
        if isinstance(candidate, type) and issubclass(candidate, logging.Handler):
            resolved[str(name)] = candidate
        else:
            unreadable.append(f"{name} = {handler!r}")
    return resolved, unreadable


def _resolved_routes() -> Iterator[Any]:
    """Yield every leaf route in this repository's resolved URLconf.

    The resolver's own patterns rather than a re-import of `config.urls`: what
    matters is what a deployed component actually serves, and the resolver is
    what serves it. Nested `include()`s are walked, because a media route
    mounted inside one is a media route.

    Yields:
        Each `URLPattern`, at any depth.
    """
    pending: list[Any] = list(get_resolver().url_patterns)
    while pending:
        entry = pending.pop()
        nested = getattr(entry, "url_patterns", None)
        if nested is None:
            yield entry
        else:
            pending.extend(nested)


#: The directory `pixi run` writes its per-task cache entry into, relative to the
#: application root. Named here because two assertions read it and because the
#: Dockerfile instruction that redirects it is otherwise unattributable.
TASK_CACHE_DIRECTORY: Final[str] = "/app/.pixi/task-cache-v0"


def test_the_dockerfile_exists_and_parses_to_instructions(instructions: list[tuple[int, str, str]]) -> None:
    """Every assertion in this module holds over nothing if the file is not read.

    `Dockerfile` is `machinery` and this repository is the one place it exists
    (AD-15), so its absence here is a defect rather than a state to accommodate
    -- unlike `tests/unit/test_release_stage.py`, whose Dockerfile case is
    written to be copied into a materialized component where the file is
    correctly gone.

    A file that parsed to no instruction at all would satisfy "no COPY brings a
    configuration file", "no VOLUME outside /tmp" and every other absence
    asserted below, which is the vacuous green this guard exists to prevent. The
    fixture returns an empty list rather than raising for exactly this reason:
    the message below is the one a missing file should produce, and it can only
    be produced by a case that runs.
    """
    assert DOCKERFILE.is_file(), (
        f"{DOCKERFILE} does not exist. This repository ships a Dockerfile as `machinery` so the harness "
        f"can verify the FR-38/FR-39 payload properties (AD-15); without it every assertion in this module "
        f"passes by having nothing to read."
    )
    assert instructions, f"{DOCKERFILE.name} exists but parses to no instruction at all"


def test_the_pixi_task_cache_is_kept_out_of_the_application_root(
    instructions: list[tuple[int, str, str]],
) -> None:
    """The one write `pixi run` performs that is not the task's own, redirected in the image.

    `pixi run <task>` writes `.pixi/task-cache-v0/<env>-<task>-<hash>.json` when
    the task completes, *after* the task's exit status is known -- so when the
    write fails, pixi exits non-zero with the task's output already printed. A
    `manage migrate` that applied every migration and reported success still
    failed the release stage that way, with `Permission denied (os error 13)`
    under the image's `g=rX` tree and `Read-only file system (os error 30)` under
    `--read-only`.

    No pixi flag or environment variable relocates it: `PIXI_CACHE_DIR` and
    `RATTLER_CACHE_DIR` govern the package caches, `--frozen` and `--no-install`
    govern solving. The image links the directory into `/tmp` instead.

    Asserted here as well as in `tests/integration/test_image_payload.py` because
    the integration case needs Docker and this one does not, and because the
    instruction is the kind a later reader deletes as inscrutable -- it looks like
    a stray symlink until the failure it prevents is in front of you.

    The link must target `/tmp` itself, not a path beneath it: the platform mounts
    a fresh tmpfs there, so a link to `/tmp/<anything>` dangles, and `mkdir` on a
    name occupied by a dangling symlink fails with `File exists (os error 17)`
    rather than following it.
    """
    linked = [
        (line, body)
        for line, instruction, body in instructions
        if instruction == "RUN" and TASK_CACHE_DIRECTORY in body and "ln -s" in body
    ]

    assert linked, (
        f"no RUN instruction links {TASK_CACHE_DIRECTORY} out of the application root. Without it "
        f"`pixi run <task>` fails after the task succeeds, on any read-only or group-read-only tree."
    )
    assert any(f"ln -s {TEMPORARY_DIRECTORY} {TASK_CACHE_DIRECTORY}" in body for _line, body in linked), (
        f"{TASK_CACHE_DIRECTORY} is linked somewhere other than {TEMPORARY_DIRECTORY} itself: "
        f"{[body for _line, body in linked]}. A target beneath {TEMPORARY_DIRECTORY} does not exist "
        f"when the platform mounts it as a fresh tmpfs, and pixi then fails with os error 17."
    )


def test_the_payload_assertions_read_the_stage_the_image_ships() -> None:
    """A builder stage is not the payload, and a flat read cannot tell the difference.

    The real `Dockerfile` is single-stage, so every payload case in this module
    would read identically against a `final_stage` that had stopped splitting --
    and a multi-stage rewrite that put `USER 1001` and `ENV HOME=/tmp` in a
    discarded builder while shipping root with `HOME=/` would pass the lot.

    This is that shape, driven through the same helpers the real cases use. What
    the parser must report is the *final* stage's answers: root, `/`, and a
    volume outside the temporary directory.
    """
    shipped = final_stage(instruction_lines(MULTI_STAGE_DOCKERFILE))
    heads = [head for _number, head, _arguments in shipped]
    assert heads.count("FROM") == 1, f"final_stage returned more than one stage: {shipped}"

    environment = _image_environment(shipped)
    assert environment.get(HOME_VARIABLE) == "/", (
        f"final_stage read {HOME_VARIABLE}={environment.get(HOME_VARIABLE)!r}, which is the builder stage's "
        f"answer. A discarded stage's ENV is not the image's."
    )
    identities = [_tokens(arguments)[0] for _number, arguments in _arguments_of(shipped, USER_INSTRUCTION)]
    assert identities == ["root"], f"final_stage read {identities}, which is the builder stage's USER"
    volumes = [path for _number, arguments in _arguments_of(shipped, VOLUME_INSTRUCTION) for path in _tokens(arguments)]
    assert volumes == ["/var/lib/component"], f"final_stage did not read the shipping stage's VOLUME: {volumes}"


def test_no_copy_or_add_instruction_brings_a_configuration_file_into_the_image(
    instructions: list[tuple[int, str, str]],
) -> None:
    """AC #1: no configuration file is present, because none is ever copied in.

    "Starts from environment variables alone" is a property with two failure
    modes, and only one of them is visible at run time. A component that reads a
    `.env` fails loudly if it is missing; a component whose image *contains* one
    starts perfectly and is configured by a file nobody named in a deployment
    manifest. The second is the one this catches, and it catches it at the point
    the file enters rather than at the point something reads it.

    **Three ways in, and each of them is a way a narrower scan misses.** `ADD` is
    `COPY` with more reach and would carry `.env` or a remote `settings.ini` past
    a scan that read only `COPY`. `.env.production` is neither the name `.env`
    nor the suffix `.env`, which is why `tests/payload.py` matches the family as
    a prefix. And a *directory* source names nothing about what is inside it:
    `COPY . .` and `COPY deploy/ /app/` both satisfy a scan that reads the final
    path component, while carrying whatever the context holds.

    That last one is why the enumeration in the `Dockerfile` is the subject here.
    `.dockerignore` is a second line of defence and not the thing deciding what
    enters the image -- a `COPY . .` would make it the only one, and an ignore
    file is a list of what somebody thought of.

    Every stage, not only the shipping one. A configuration file that entered a
    builder is one `COPY --from=` away from the final image, and this is the
    scan that is supposed to see it arrive.

    `component.toml` is copied and is not an exception. It is the component's own
    declaration -- source that travels, which the materializer rewrites per
    combination -- rather than a configuration of this deployment. The same goes
    for `pixi.toml` and `pyproject.toml`: what must be absent is a file that
    *configures* a running component, not every file that happens to hold
    key-value pairs.
    """
    offenders: list[str] = []
    for number, source, from_stage in _copied_sources(instructions):
        normalized = source.rstrip("/") or source
        name = normalized.rpartition("/")[2]
        inside_source_tree = normalized == SOURCE_ROOT or normalized.startswith(f"{SOURCE_ROOT}/")

        if is_configuration_name(name):
            offenders.append(f"line {number}: copies {source!r}, which is configuration")
        elif name.startswith(SETTINGS_PREFIX) and not inside_source_tree:
            offenders.append(f"line {number}: copies {source!r}, a settings file outside {SOURCE_ROOT}/")

        if source in WHOLE_CONTEXT_SOURCES:
            offenders.append(f"line {number}: copies {source!r}, which is the whole build context")
        elif not from_stage and normalized not in PERMITTED_DIRECTORY_SOURCES and (REPO_ROOT / normalized).is_dir():
            offenders.append(f"line {number}: copies the directory {source!r}, whose contents are not enumerated")

    assert not offenders, (
        f"these {DOCKERFILE.name} COPY/ADD instructions bring configuration into the image, or bring in "
        f"more than they name: {offenders}. FR-38: a component's configuration is exclusively "
        f"environmental, and an image carrying a configuration file starts correctly while being configured "
        f"by something no deployment manifest names."
    )


def test_the_image_declares_a_numeric_non_root_user(payload_instructions: list[tuple[int, str, str]]) -> None:
    """AC #2: the component runs as a non-root user, declared as a number.

    Two separate things, and the second is the one that is easy to get wrong.

    *Non-root*, because a payload that needs root cannot run on a platform that
    assigns UIDs, and `USER 0` is the same declaration as `USER root` written so
    that a name comparison misses it.

    *Numeric*, because a name has to resolve through `/etc/passwd` and a
    platform-assigned UID has no entry there. The number is what the container
    runtime actually applies, and the group-0 permissions the image grants are
    what make an arbitrary UID able to read a tree it was never named in. This
    declared value is therefore the floor rather than the expectation -- but a
    floor of root is not a floor.
    """
    declared = _arguments_of(payload_instructions, USER_INSTRUCTION)
    assert declared, (
        f"the stage {DOCKERFILE.name} ships declares no {USER_INSTRUCTION} instruction, so the image runs "
        f"as root. FR-39: the component runs under an arbitrary non-root UID."
    )

    offenders: list[str] = []
    for number, arguments in declared:
        tokens = _tokens(arguments)
        identity = tokens[0] if tokens else ""
        user = identity.partition(":")[0]
        if user in ROOT_IDENTITIES:
            offenders.append(f"line {number}: {USER_INSTRUCTION} {identity!r} is root")
        elif not user.isdigit():
            offenders.append(f"line {number}: {USER_INSTRUCTION} {identity!r} is a name, not a UID")

    assert not offenders, (
        f"these {DOCKERFILE.name} {USER_INSTRUCTION} instructions do not declare a numeric non-root UID: "
        f"{offenders}. A name needs an /etc/passwd entry, which a platform-assigned UID does not have."
    )


def test_the_application_tree_is_readable_through_group_zero(
    payload_instructions: list[tuple[int, str, str]],
) -> None:
    """AC #2: the mechanism that makes an arbitrary UID work, asserted rather than assumed.

    The platform assigns a UID the image has never seen and puts it in group 0.
    There is no `/etc/passwd` entry for it and no way to chown for it in advance,
    so the only thing that can grant access ahead of time is the group.

    **Why this needs its own case.** Removing `chgrp -R 0 /app && chmod -R g=rX
    /app` breaks nothing visible: a root-owned tree is 0755 by default, so an
    arbitrary UID can already read most of it and the container still starts and
    serves. The mechanism would rot silently while the arbitrary-UID claim stayed
    in the documentation -- and the first file the build created with a tighter
    mode would take the component down on a platform nobody could reproduce.

    **And the mode is asserted, not only the group.** `chmod -R g=u` copies the
    *owner's* bits to the group, which for a root-owned tree includes write: an
    arbitrary UID in group 0 could then rewrite the application it is running,
    under an image whose comment says "read access, not write". `g=rX` is that
    comment expressed as a mode -- read everywhere, execute only where the owner
    already has it, which is what the conda environment's binaries and its
    directories need.
    """
    root = _application_root(payload_instructions)
    assert root, f"{DOCKERFILE.name} declares no {WORKDIR_INSTRUCTION}, so there is no application root to grant"

    executed = " ".join(
        arguments for _number, head, arguments in payload_instructions if head in EXECUTING_INSTRUCTIONS
    )
    assigned = [match for match in GROUP_ZERO_ASSIGNMENT.finditer(executed) if match.group(1) == root]
    assert assigned, (
        f"{DOCKERFILE.name} never puts {root} in group 0. A platform that assigns UIDs guarantees group 0 "
        f"and nothing else, so the group is the only thing that can grant access to a tree the image could "
        f"not have chowned in advance -- and without it `--user 12345:0` reads whatever the default mode "
        f"happens to allow."
    )

    granted = [match for match in GROUP_MODE_GRANT.finditer(executed) if match.group(2) == root]
    assert granted, (
        f"{DOCKERFILE.name} puts {root} in group 0 but grants the group no mode on it, so the ownership "
        f"change grants nothing that the default permissions did not already."
    )
    offenders = sorted(
        f"chmod g={match.group(1)!r}"
        for match in granted
        if READ_MODE_LETTER not in match.group(1) or not set(match.group(1)) <= PERMITTED_GROUP_MODE_LETTERS
    )
    assert not offenders, (
        f"these {DOCKERFILE.name} instructions grant group 0 a mode on {root} that is not read-and-traverse: "
        f"{offenders}. AC #2 says the component declares no writable path beyond a temporary directory, and "
        f"`g=u` on a root-owned tree copies the owner's *write* bit -- so the arbitrary UID could rewrite "
        f"the application it is running. Permitted letters: {sorted(PERMITTED_GROUP_MODE_LETTERS)}."
    )


def test_home_is_a_temporary_directory(payload_instructions: list[tuple[int, str, str]]) -> None:
    """AC #2: an arbitrary UID has no home, so the image gives it one that is writable.

    This is the least obvious of the arbitrary-UID accommodations and the one
    that fails the most confusingly. A platform-assigned UID has no
    `/etc/passwd` entry, so `getpwuid` raises and everything resolving `$HOME`
    falls back to `/` -- which is read-only. The failure surfaces as a
    permission error from whichever tool asked first, with nothing in the message
    about UIDs or filesystems.

    `HOME` under the temporary directory is the fix, and it is the same one leg
    of the zero-writable-path claim: the writable path is `/tmp` and there is not
    a second one.
    """
    environment = _image_environment(payload_instructions)
    home = environment.get(HOME_VARIABLE)
    assert home is not None, (
        f"{DOCKERFILE.name} sets no {HOME_VARIABLE} in the stage it ships. An arbitrary UID has no "
        f"/etc/passwd entry and therefore no home directory, so every tool that resolves it falls back to a "
        f"read-only root."
    )
    assert _is_inside_temporary_directory(home), (
        f"{DOCKERFILE.name} sets {HOME_VARIABLE}={home!r}, which is not inside {TEMPORARY_DIRECTORY}. "
        f"AC #2: the component declares no writable path beyond a temporary directory."
    )


def test_no_volume_is_declared_outside_the_temporary_directory(
    payload_instructions: list[tuple[int, str, str]],
) -> None:
    """AC #2: the component declares no writable path beyond a temporary directory.

    A `VOLUME` is a declaration that the component depends on a writable path,
    and each of the three that would be reached for has already been answered
    somewhere else: static files are collected at build and served by WhiteNoise,
    logs go to the event stream as JSON on stdout with no files and no rotation,
    and user media is a non-goal (FR-25). A fourth reason to add one is a
    component that is not a payload.

    `/tmp` itself is permitted and is not declared: the platform mounts it as a
    tmpfs, and an image that declared it would be asking a runtime to do
    something it already does.
    """
    offenders = [
        f"line {number}: {VOLUME_INSTRUCTION} {path!r}"
        for number, arguments in _arguments_of(payload_instructions, VOLUME_INSTRUCTION)
        for path in _tokens(arguments)
        if not _is_inside_temporary_directory(path)
    ]
    assert not offenders, (
        f"these {DOCKERFILE.name} {VOLUME_INSTRUCTION} instructions declare a writable path outside "
        f"{TEMPORARY_DIRECTORY}: {offenders}. Static is collected at build and served by the application, "
        f"logs go to the event stream, user media is a non-goal (FR-25) and sessions are database-backed."
    )


def test_the_build_collects_static_and_supplies_its_scaffolding_inline(
    payload_instructions: list[tuple[int, str, str]],
) -> None:
    """AC #3's static leg, and the subject the next case is about.

    Two assertions, and the first is what keeps the second from being about
    nothing. `collectstatic` at **build** time is the whole of "static files are
    collected at build and served by the application": it is why `STATIC_ROOT` is
    read-only in a running component, why there is no sidecar and no shared
    volume, and why the manifest `whitenoise.storage.CompressedManifestStaticFilesStorage`
    resolves every `{% static %}` through is already in the image. Deleting that
    `RUN` leaves this whole module green otherwise -- and makes the case below
    pass by having no variables to find.

    The second is that the refusal contract's roster is supplied *inline* on that
    line. `collectstatic` runs under `config.settings.production`, which is the
    only settings module declaring the manifest storage, and importing it runs
    stage 1 -- so the roster has to be satisfiable while the manifest is written.
    Supplied inline it lasts for one command; promoted to `ENV` it is a secret in
    every layer. The case below asserts the second half of that; this asserts
    there is a first half.
    """
    collecting = [
        (number, arguments)
        for number, head, arguments in payload_instructions
        if head == "RUN" and COLLECTSTATIC_INVOCATION.search(arguments)
    ]
    assert collecting, (
        f"{DOCKERFILE.name} runs no build-time collectstatic. AC #3's static leg is that static files are "
        f"collected at build and served by the application -- without it the component would have to "
        f"collect at start-up, which is a write under a read-only root, or be served by a sidecar, which is "
        f"a second thing to deploy."
    )

    supplied: set[str] = set()
    for _number, arguments in collecting:
        supplied |= _inline_variables(arguments)
    missing = sorted(BUILD_SCAFFOLDING_VARIABLES - supplied)
    assert not missing, (
        f"the build-stage collectstatic supplies none of {missing} inline. Those values are what let "
        f"`config.settings.production` import at build time -- stage 1 of the refusal contract runs on that "
        f"import -- and supplying them inline rather than as ENV is the distinction the next case asserts. "
        f"Supplied nowhere, that case has no subject."
    )


def test_no_env_instruction_bakes_the_variables_the_build_supplies_inline(
    payload_instructions: list[tuple[int, str, str]],
) -> None:
    """AC #1: build scaffolding stays on the build line and never becomes image environment.

    Promoting the roster to `ENV` is one line, it makes the `RUN` shorter, and it
    bakes a secret key and a database URL into every layer of the image and into
    whatever registry it is pushed to. It would also make the component start
    successfully with *no* configuration supplied, which is FR-38 inverted:
    configuration would be coming from the image rather than from the
    environment, and nobody would notice until the day someone changed a
    deployment variable and nothing happened.

    The subject is asserted by the case above -- that the variables are supplied
    inline at all -- so this one cannot pass by finding nothing to check.
    """
    baked = sorted(BUILD_SCAFFOLDING_VARIABLES.intersection(_image_environment(payload_instructions)))
    assert not baked, (
        f"{DOCKERFILE.name} sets these as image environment: {baked}. They are build scaffolding for the "
        f"build-stage collectstatic, supplied inline on that RUN; baked as ENV they are a secret in a "
        f"registry and a component configured by its image rather than by its environment (FR-38)."
    )


def test_no_env_instruction_makes_the_payload_configurable_by_a_file(
    payload_instructions: list[tuple[int, str, str]],
) -> None:
    """AC #1: the image carries no switch that turns the payload back into a file-read.

    `src/config/settings/base.py` reads `.env` from `BASE_DIR` whenever
    `DJANGO_READ_DOT_ENV_FILE` is set, and that is the one variable that defeats
    every other assertion in this module at once. An `ENV DJANGO_READ_DOT_ENV_FILE=True`
    copies no configuration file, bakes no secret, declares no volume and
    contains nothing anybody would call configuration -- and the component then
    looks for a file at every start, which a mounted `.env` or a later layer can
    supply. FR-38 says configuration is exclusively environmental; a component
    that reads a file *because* of an environment variable is not that.
    """
    environment = _image_environment(payload_instructions)
    assert DOT_ENV_TOGGLE not in environment, (
        f"{DOCKERFILE.name} sets {DOT_ENV_TOGGLE}={environment.get(DOT_ENV_TOGGLE)!r} as image environment. "
        f"src/config/settings/base.py reads a `.env` beside the source whenever it is set, so the payload "
        f"becomes file-configurable without the image carrying a single configuration file -- which is "
        f"FR-38 defeated by the one variable no other assertion here looks at."
    )


def test_the_dockerignore_keeps_local_state_out_of_the_build_context() -> None:
    """AC #1's other half: an enumerated COPY cannot bring in what never reached the context.

    `.dockerignore` is read by the daemon and by nothing else, so nothing else in
    this suite would notice an entry going missing -- and the entries here are
    not tidiness. `.env` and `.envs/` are configuration FR-38 forbids;
    `.local-dev-keys/` is a generated signing keypair, and a private key in an
    image is a private key in a registry; `db.sqlite3` is a real local database
    sitting at the repository root, which would ship as a writable credential
    store inside the payload; `.git/` is the history hatch-vcs would otherwise
    read, which the build supplies as an `ARG` instead.

    **The `**/` forms are the part that is easy to get wrong**, and they are
    asserted by literal for that reason. A `.dockerignore` pattern is matched
    against the path *relative to the context root*, unlike `.gitignore`, so a
    bare `.env` excludes `./.env` and nothing else -- `src/config/.env` would
    reach the image through `COPY src ./src`. The same goes for `__pycache__/`:
    a working tree that has run the suite has a dozen of them under `src/`.
    """
    assert DOCKERIGNORE.is_file(), (
        f"{DOCKERIGNORE} does not exist. The Dockerfile's enumerated COPY is the first line of defence and "
        f"this file is the second; without it the build context carries whatever the working tree does."
    )
    declared = {
        line.strip() for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines() if not line.startswith("#")
    }
    missing = [entry for entry in REQUIRED_DOCKERIGNORE_ENTRIES if entry not in declared]
    assert not missing, (
        f"{DOCKERIGNORE.name} no longer excludes {missing}. Each of these is local state or history that "
        f"must never enter an image, and a `**/` form is not interchangeable with its root-anchored "
        f"spelling: docker matches the pattern against the path relative to the context root, so the bare "
        f"form excludes the repository root's copy only."
    )


@pytest.mark.parametrize("name", SETTINGS_MODULES)
def test_no_settings_module_declares_a_file_based_log_handler(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC #3's logs leg: the event stream, with no files and no rotation.

    Asserted on the *resolved handler class* rather than on the dotted string,
    and the difference is not stylistic. `logging.FileHandler` is the base class
    of `RotatingFileHandler`, `TimedRotatingFileHandler` and
    `WatchedFileHandler`, so one `issubclass` check covers every file-writing
    handler the standard library has -- and a project-local subclass of any of
    them, which no string comparison would catch.

    **Both dictConfig spellings, and a handler in neither fails loudly.** A
    handler can name its implementation under `class` or under the `()` factory
    key, and `dictConfig` builds either. `{"()": "logging.handlers.RotatingFileHandler",
    "filename": ...}` writes a file; a reader that looked only at `class` would
    drop it from the scan and report nothing. The `()` idiom is live in this
    repository -- `production.py` declares `require_debug_false` with it -- so a
    handler declared that way is a spelling in use rather than one to imagine.
    A declaration this scan cannot resolve to a handler class is reported instead
    of skipped, because a skipped handler is one this assertion never applied to.

    All four settings modules, including `local.py`, which declares no `LOGGING`
    of its own and inherits `base.py`'s through `from .base import *`. A handler
    added by inheritance writes to a file exactly as much as one added directly.

    `production.py` additionally declares `mail_admins`, and it is not a file
    handler: `django.utils.log.AdminEmailHandler` sends mail. That it survives
    this assertion is the point -- an assertion that failed on any handler other
    than `console` would be asserting a roster rather than a property.
    """
    module = _import_settings(name, monkeypatch)
    resolved, unreadable = _resolved_handler_classes(module.LOGGING)
    assert not unreadable, (
        f"{name} declares log handlers this scan cannot resolve to a class: {unreadable}. A handler names "
        f"its implementation under `class` or under the `()` factory key; one that does neither is a "
        f"handler the file-based assertion below never applied to."
    )
    assert resolved, f"{name} declares no log handler at all, so this assertion holds over nothing"

    offenders = sorted(
        f"{handler} = {klass.__module__}.{klass.__qualname__}"
        for handler, klass in resolved.items()
        if issubclass(klass, FILE_HANDLER_BASE)
    )
    assert not offenders, (
        f"{name} declares file-based log handlers: {offenders}. Logs are the event stream -- structured "
        f"JSON on stdout, no files, no rotation -- which is one of the four legs of AC #3's "
        f"zero-writable-path claim."
    )


def test_the_session_store_is_the_database_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC #3's sessions leg, asserted as the acceptance criterion states it.

    **What holds today, and why.** `config/settings/base.py` sets
    `SESSION_ENGINE` explicitly to the database-backed engine, and
    `production.py` inherits it through `from .base import *`. Story 5.7 landed
    that line; before it, what resolved was Django's own global default, which is
    the same string. The difference is not cosmetic -- "it happens to default
    correctly" and "we set it" are different degrees of guarantee, and only one of
    them survives a Django release note -- which is why the setting's *presence*
    is now asserted here rather than fallen back from.

    **What `test_session_settings.py` owns and this does not.** That the value is
    declared in `base.py` and in no other settings module, exactly once, outside
    every AD-24 region, is that module's. This one asks the payload question AC
    #2 and AC #3 depend on: what the resolved store class *is*, so that a
    project-local engine reached under a different dotted path is still the right
    answer.

    **Why the property is stated as an identity rather than as a denial.** AC #3
    says sessions are database-backed. Refusing only the file store would pass
    `django.contrib.sessions.backends.cache` over the LocMem cache -- per-replica
    sessions, so a user's session depends on which replica answered, which is
    exactly the NFR-3 statelessness failure the criterion exists to prevent --
    and would pass `signed_cookies` too. So the assertion is that the resolved
    store *is* the database store.

    Asserted against the resolved store class rather than the dotted name,
    because a project-local engine subclassing it is the same answer reached
    under a different name.
    """
    module = _import_settings(PRODUCTION_SETTINGS, monkeypatch)
    engine = getattr(module, "SESSION_ENGINE", None)

    assert engine is not None, (
        "config/settings/production.py composes no SESSION_ENGINE at all. Falling back to "
        "django.conf.global_settings here would make this case pass on Django's default, which is the "
        "same string -- and FR-44's whole point is that the component states the engine rather than "
        "inheriting it (AD-31)."
    )
    store = importlib.import_module(engine).SessionStore
    database_store = importlib.import_module(DATABASE_SESSION_BACKEND).SessionStore

    assert issubclass(store, database_store), (
        f"the resolved session engine {engine!r} is not the database-backed store. NFR-3: nothing is shared "
        f"through local disk or process memory across replicas, and sessions are database-backed in every "
        f"combination -- a file store is a writable path AC #2 denies, and a cache or cookie store is "
        f"per-replica or client-held, so a user's session would depend on which replica answered."
    )


def test_no_resolved_route_serves_anything_out_of_media_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recorded `MEDIA_ROOT` residue, asserted against this repository's own URLconf.

    `src/config/urls.py` ends `urlpatterns` with
    `*static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)`, and
    `MEDIA_ROOT` is a directory inside the source tree. Read as a declaration
    that is a writable path in the payload, which contradicts AC #2 -- and it is
    still there, because FR-25 puts user media out of scope and Epic 7's
    object-storage story owns removing the surface. This story records the
    residue rather than resolving it.

    **Asserted against the resolver, not against `static()`.** Calling
    `django.conf.urls.static.static` here and checking that it returns `[]` under
    `DEBUG=False` asserts a property of *Django*: it would stay green while
    `src/config/urls.py` mounted an unconditional `re_path(r"^media/(?P<path>.*)$",
    serve, {"document_root": settings.MEDIA_ROOT})` on the next line, which is a
    live writable media route in a deployed component. So what is read is this
    repository's resolved `urlpatterns` -- what it actually serves.

    Both directions. Nothing resolves under `MEDIA_URL`, and no route anywhere in
    the URLconf is handed `MEDIA_ROOT` as a document root -- the second catches a
    media route mounted at some other prefix, which is the same writable path
    reached by a different URL.

    `production.py` never turns `DEBUG` on, which is asserted too: the media
    route's inertness is entirely downstream of it, and the suite's own settings
    are checked as well, because a `DEBUG` on here would make the resolver
    assertions vacuous in the other direction.
    """
    module = _import_settings(PRODUCTION_SETTINGS, monkeypatch)
    assert module.DEBUG is False, (
        "config.settings.production composed DEBUG on, which mounts the media route it is otherwise inert behind."
    )
    assert active_settings.DEBUG is False, (
        "the suite is running with DEBUG on, so the resolved URLconf below is the debug one and the "
        "assertions over it say nothing about a deployed component."
    )

    with pytest.raises(Resolver404):
        resolve(f"{active_settings.MEDIA_URL}{MEDIA_PROBE_FILENAME}")

    serving = sorted(
        f"{getattr(route, 'pattern', route)}"
        for route in _resolved_routes()
        if (getattr(route, "default_args", None) or {}).get(DOCUMENT_ROOT_KEYWORD) == active_settings.MEDIA_ROOT
    )
    assert not serving, (
        f"these resolved routes serve {active_settings.MEDIA_ROOT!r}: {serving}. MEDIA_ROOT is inside the "
        f"source tree, so a live media route is a writable path in the payload (AC #2). FR-25 puts user "
        f"media out of scope and Epic 7 owns removing the MEDIA_* surface; until then its inertness is what "
        f"stands in for its absence."
    )


def test_the_model_scan_covers_every_application_a_deployed_component_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `FileField` scan below says "every installed application", so this makes that true.

    `django.apps.apps` is the registry of the settings module the *suite* runs
    under, and `production.py` installs one application the suite does not:
    `INSTALLED_APPS += ["anymail"]`. A `FileField` on a production-only
    application would therefore be invisible to a scan whose docstring claims to
    cover everything -- the residue arriving through exactly the dependency route
    that docstring says it is watching for.

    So the difference is enumerated rather than assumed, and each application in
    it has to ship no `models` module at all. That is a stronger statement than
    "it has no file field today": an application with no models cannot acquire
    one without this case failing, which is what makes the exemption safe to
    leave in a list.
    """
    module = _import_settings(PRODUCTION_SETTINGS, monkeypatch)
    scanned = {configuration.name for configuration in apps.get_app_configs()}
    unscanned = sorted(set(module.INSTALLED_APPS) - scanned)
    assert unscanned == sorted(PRODUCTION_ONLY_APPLICATIONS), (
        f"a deployed component installs {unscanned}, which the suite's own app registry does not, and the "
        f"recorded set is {sorted(PRODUCTION_ONLY_APPLICATIONS)}. The FileField scan reads the registry, so "
        f"an application outside it is one the scan's own docstring claims to cover and does not."
    )

    modelled: list[str] = []
    for application in unscanned:
        try:
            found = importlib.util.find_spec(f"{application}.{MODELS_MODULE}")
        except ModuleNotFoundError:
            modelled.append(f"{application} (not importable, so nothing here can read its models)")
            continue
        if found is not None:
            modelled.append(f"{application}.{MODELS_MODULE}")
    assert not modelled, (
        f"these production-only applications ship models the registry scan never sees: {modelled}. Either "
        f"install them in the suite's settings or scan them directly -- a recorded exemption is only safe "
        f"while the application it exempts has no models to declare."
    )


def test_no_installed_model_writes_user_media() -> None:
    """The other half of the residue: nothing ever asks the default storage to write.

    `production.py`'s `STORAGES["default"]` is `FileSystemStorage`, whose location
    defaults to `MEDIA_ROOT`. That is Epic 7's to replace under FR-25 and risk
    R-1, and it is harmless today for a reason worth asserting rather than
    assuming: no model in any installed application declares a `FileField`, so
    the default storage is never handed anything to save. The moment one does,
    the component acquires a writable path inside the payload and this case says
    so.

    Every installed application, not only this component's own -- and the case
    above is what makes that claim true rather than merely written, by requiring
    that the applications a deployed component installs and the suite does not
    ship no models at all. A `FileField` on a third-party model writes to the
    same storage and would be the same breach arriving through a dependency.

    `ImageField` needs no separate mention: it is a `FileField` subclass, and
    `isinstance` is what makes that true here rather than a name comparison that
    would have to enumerate them.
    """
    offenders = sorted(
        f"{model._meta.label}.{field.name} ({type(field).__name__})"  # noqa: SLF001
        for model in apps.get_models()
        for field in model._meta.get_fields()  # noqa: SLF001
        if isinstance(field, models.FileField)
    )
    assert not offenders, (
        f"these model fields write through the default storage, which is FileSystemStorage rooted at "
        f"MEDIA_ROOT: {offenders}. User media is a non-goal (FR-25) and MEDIA_ROOT is inside the source "
        f"tree, so a saved file is a write into the payload -- the writable path AC #2 denies. Epic 7's "
        f"object-storage story owns the default backend; nothing may start writing before it lands."
    )


def test_the_settings_import_helper_reads_the_environment_it_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fresh imports above are only as good as the environment they are given.

    `tests/settings_import.py` clears the whole `DJANGO_*`/`COMPONENT_*` surface
    before applying the caller's, and that clearing is invisible: a developer
    with `DJANGO_DEBUG=True` exported would otherwise get a different `DEBUG`, a
    different composed `LOGGING` renderer, and a different answer from an
    assertion that never mentioned either -- while the gate, whose environment is
    clean, stayed green.

    So the ambient variable is set here deliberately and the import is required
    to ignore it. `BASE_SETTINGS` rather than `production.py`, because `DEBUG` is
    composed in `base.py` and this is a question about the helper rather than
    about the refusal contract.
    """
    monkeypatch.setenv("DJANGO_DEBUG", "True")
    module = _import_settings(BASE_SETTINGS, monkeypatch)
    assert module.DEBUG is False, (
        "a fresh settings import read DJANGO_DEBUG out of the ambient environment. The helper clears the "
        "DJANGO_*/COMPONENT_* surface first precisely so a developer's shell cannot change what these "
        "assertions are made against."
    )
