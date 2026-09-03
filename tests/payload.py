"""What "a configuration file" is, and what may never be image environment, in one place.

Two modules assert FR-38's "configuration is exclusively environmental" and they
assert it at two different points. `tests/unit/test_payload_properties.py`
asserts it at the point a file *enters*: no `COPY` or `ADD` in the `Dockerfile`
names one. `tests/integration/test_image_payload.py` asserts it against the
finished artefact: nothing matching in the built image, whatever put it there.

Two definitions of "a configuration file" is the failure this module exists to
prevent, and it is not hypothetical -- the two started out disagreeing. The
entry-point scan looked for `.env`, `.envs`, `*.cfg`, `*.ini` and a `settings*`
outside the source tree; the in-image search looked only for `.env` and `.envs`.
A `settings.ini` written by a `RUN`, or inherited from the base image, satisfied
both: the first never saw it because no `COPY` named it, and the second never
looked for it. One definition, imported by both, is what closes that.

**The `.env` family, and why it is a prefix rather than a name.** `.env.production`
matches neither the name `.env` nor the suffix `.env`, and it is exactly as much
of a configuration file as either. The prefix covers `.env`, `.env.local`,
`.envs/` and whatever the next convention is called.

**Where the definition is deliberately narrowed, and why that is not a hole.**
`*.cfg`, `*.ini` and `settings*` are configuration when *this component* carries
them and are ordinary content when a dependency does. `/app/.pixi` is the conda
environment `pixi install --locked` built from the lock file, and the packages in
it ship their own `setup.cfg`, `tox.ini` and `settings.py` by the hundred; none
of those arrived through the build context and none of them configures this
deployment. `/app/src` is the source tree, where the settings *package* lives --
which is source that travels, not a configuration of this deployment, and is the
same carve-out the entry-point scan makes with `SOURCE_ROOT`.

The `.env` family is narrowed by nothing. A `.env` inside a dependency's
directory is still a file this payload can be configured from, and there is no
legitimate reason for one to exist anywhere in the image.

This is a helper module, not a collected one -- see `tests/pixi_manifest.py`,
`tests/dockerfile.py` and `tests/settings_import.py`, which sit here for the same
reason.
"""

from __future__ import annotations

from typing import Final

#: The application root inside the image, and the two subtrees of it whose
#: `*.cfg`/`*.ini`/`settings*` content is somebody else's -- see the module
#: docstring. `/app/.pixi` is what the lock file installed; `/app/src` is this
#: component's own source.
IMAGE_APPLICATION_ROOT: Final[str] = "/app"
INSTALLED_ENVIRONMENT_ROOT: Final[str] = "/app/.pixi"
IMAGE_SOURCE_ROOT: Final[str] = "/app/src"

#: The `.env` family, matched as a prefix on the file's own name. Covers `.env`,
#: `.env.production` and `.envs` with one rule.
ENVIRONMENT_FILE_PREFIX: Final[str] = ".env"

#: The two extensions Python configuration conventionally uses -- `setup.cfg`,
#: `tox.ini`, `.coveragerc`'s ini form -- plus the `.env` suffix for the
#: `component.env` spelling. A settings file smuggled in under any of them would
#: configure the component from disk while every other assertion stayed green.
CONFIGURATION_SUFFIXES: Final[tuple[str, ...]] = (".env", ".cfg", ".ini")

#: A file whose name begins this way is a settings file. The settings *package*
#: is source and lives under the source root, which is why the callers pair this
#: with a source-tree carve-out rather than banning the prefix outright.
SETTINGS_PREFIX: Final[str] = "settings"

#: `.toml` is deliberately in none of the above. `pixi.toml`, `pyproject.toml`
#: and `component.toml` are all copied and all belong in the image: they are
#: source that travels, and `component.toml` in particular is the component's own
#: declaration rather than a configuration of this deployment.
PERMITTED_DECLARATION_SUFFIX: Final[str] = ".toml"

#: The `find -name` patterns that select every name the predicates below can
#: return True for. Deliberately wider than the predicates -- `find` does the
#: cheap half inside the container and the predicates do the narrowing here,
#: where the reasons can be written down.
CONFIGURATION_FIND_PATTERNS: Final[tuple[str, ...]] = (".env*", "*.env", "*.cfg", "*.ini", "settings*")

#: The stage-1 roster a deployed `config.settings.production` import needs, by
#: name. The `Dockerfile` supplies every one of them *inline* on its build-stage
#: `collectstatic` line, because importing that settings module runs stage 1 of
#: the refusal contract and the whole roster has to be satisfiable while the
#: manifest is written.
#:
#: Baked as `ENV` they would be a secret key and a database URL in every layer of
#: the image and in whatever registry it is pushed to -- and the component would
#: start successfully with *no* configuration supplied, which is FR-38 inverted.
BUILD_SCAFFOLDING_VARIABLES: Final[frozenset[str]] = frozenset(
    {
        "DJANGO_SECRET_KEY",
        "DJANGO_ADMIN_URL",
        "DATABASE_URL",
        "COMPONENT_OIDC_ISSUER",
        "COMPONENT_IDENTITY_CLAIM",
        "COMPONENT_GROUP_CLAIM",
        "COMPONENT_STAFF_GROUP",
        "COMPONENT_SUPERUSER_GROUP",
    }
)

#: The variable that turns the payload back into a file-configured component
#: without carrying a single configuration file itself. `src/config/settings/
#: base.py` reads `.env` from `BASE_DIR` whenever it is set, so an `ENV
#: DJANGO_READ_DOT_ENV_FILE=True` makes the image look for one at every start --
#: and every other assertion in this suite stays green, because the file that
#: would be read need never have been in the image at all. A mounted one would do.
DOT_ENV_TOGGLE: Final[str] = "DJANGO_READ_DOT_ENV_FILE"

#: Everything an `ENV` instruction may not set, and everything the built image's
#: resolved `Config.Env` may not carry. The second is wider than the first on
#: purpose: a variable inherited from the base image or promoted from an `ARG`
#: satisfies every assertion made about the `Dockerfile`'s own text.
#:
#: `DJANGO_SETTINGS_MODULE` is deliberately absent. FR-38 makes configuration
#: environmental and the settings module is the platform's to name (see
#: `docs/deployment.md`): an `ENV DJANGO_SECRET_KEY` is a baked secret, while an
#: `ENV DJANGO_SETTINGS_MODULE` would merely be a default the platform overrides.
FORBIDDEN_IMAGE_VARIABLES: Final[frozenset[str]] = BUILD_SCAFFOLDING_VARIABLES | {DOT_ENV_TOGGLE}


def is_configuration_name(name: str) -> bool:
    """Report whether one file's own name is a configuration file's.

    The `settings*` rule is deliberately not here: it needs to know *where* the
    file is, because the settings package is source and is copied with the rest
    of it. `is_component_configuration` pairs the two.

    Args:
        name: The file's final path component.

    Returns:
        True for the `.env` family and for the configuration suffixes.
    """
    return name.startswith(ENVIRONMENT_FILE_PREFIX) or name.endswith(CONFIGURATION_SUFFIXES)


def is_component_configuration(path: str) -> bool:
    """Report whether one absolute path inside the image is this component's configuration.

    The `.env` family counts anywhere. The suffix and `settings*` rules are
    narrowed to the component's own tree, for the reason the module docstring
    records: the conda environment and the source package are full of files that
    match by name and configure nothing about this deployment.

    Args:
        path: The absolute path, as `find` reported it inside the container.

    Returns:
        True when the file is configuration this payload could be started from.
    """
    name = path.rstrip("/").rpartition("/")[2]
    if name.startswith(ENVIRONMENT_FILE_PREFIX):
        return True
    if _is_somebody_elses(path):
        return False
    return name.endswith(CONFIGURATION_SUFFIXES) or name.startswith(SETTINGS_PREFIX)


def _is_somebody_elses(path: str) -> bool:
    """Report whether a path lies in the installed environment or the source tree.

    Args:
        path: The absolute path inside the image.

    Returns:
        True when the file belongs to a dependency pixi installed or to the
        component's own source package rather than to its configuration.
    """
    return any(path == root or path.startswith(f"{root}/") for root in (INSTALLED_ENVIRONMENT_ROOT, IMAGE_SOURCE_ROOT))
