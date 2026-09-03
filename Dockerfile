# This Dockerfile is `machinery` under AD-2 and **never travels**.
#
# Materialized components ship no Dockerfile at all (AD-15): the buildpack and
# golden-base path is the default, and a component that genuinely needs its own
# build is a deliberate departure rather than the norm. Every component acquiring
# an opt-out from the platform image pipeline is the failure AD-15 exists to
# prevent -- it turns a base-image CVE bump into N pull requests.
#
# So why does this file exist? Because FR-38 and FR-39 are properties of the
# *application* -- it starts from environment variables alone, under an arbitrary
# non-root UID, writing nothing outside a temporary directory -- and a property
# nobody can run is a property nobody has verified. This image is the harness's
# subject: `tests/integration/test_image_payload.py` builds it, runs it under
# `--user 12345:0 --read-only --tmpfs /tmp`, and asserts those properties instead
# of assuming them. It is not the deployment artefact and nothing in this
# repository pushes it anywhere.
#
# **AD-2 obligation, recorded here because here is where it applies.** Unlisted
# paths default to `machinery`, so this file is already non-travelling. It must
# nonetheless be listed *explicitly* as `machinery` when Epic 7 authors
# `accelerator.toml`, because AD-2's input reconciliation fails a path claimed by
# no disposition. The same goes for `.dockerignore` beside it.
#
# **AD-32 governs the one shape that inherits it.** "Use this template" produces
# a fork of the base rather than a generated component, and that fork carries
# `accelerator.toml`, the materializer and this Dockerfile -- so it can opt out
# of the image pipeline where a materialized component cannot. That is R-4, and
# it is accepted rather than mitigated.
#
# **AD-22, and it holds at every depth.** No instruction in this file applies
# migrations, at build time or at start-up. That is a release-stage step the
# deployment repository performs once per database before new pods serve, and
# `tests/unit/test_release_stage.py::test_no_dockerfile_instruction_migrates`
# fails the gate on any RUN, ENTRYPOINT, CMD or HEALTHCHECK here that does --
# including one hidden after a `&&` on the second line of a continuation.
#
# **AD-14, and it is why the CMD is what it is.** The deployment repository
# invokes `pixi run <process>`. The image's CMD is `pixi run web` rather than a
# bare gunicorn command, or the image and the process model would declare two
# different things and the deployment repository would be following the wrong
# one.

# The base is pinned by digest rather than by tag, which is NFR-5's determinism
# requirement applied to the one input a lock file cannot cover. This digest is
# the multi-arch index for `0.70.2-trixie`: Debian 13, `pixi 0.70.2` at
# /usr/local/bin/pixi, and no ENTRYPOINT, CMD, USER, WORKDIR or ENV of its own.
# 0.70.2 is exactly the floor `pixi.toml [workspace] requires-pixi = ">=0.70.2"`
# names.
#
# `--platform=linux/amd64` is a constraint and not a preference. `pixi.lock`
# declares linux-64, osx-arm64 and win-64 and no linux-aarch64, so
# `pixi install --locked` cannot resolve on an arm64 base at all; linux-64 is
# also the only Linux platform where gunicorn and uvicorn-worker are declared
# ([target.linux-64.dependencies]) and therefore the only one where the `web`
# task resolves. On an arm64 developer machine this builds under emulation and
# is slow. That is the cost of a lock file that means something.
FROM --platform=linux/amd64 ghcr.io/prefix-dev/pixi@sha256:f32bc1b96d4aacb8bc0cc3c4b731eceb3dd3606f48ec56ed8f61b9a737c5db58

# The version, supplied rather than derived, because `.dockerignore` excludes
# `.git/` and hatch-vcs reads `dynamic = ["version"]` off git tags. A pipeline
# passes the real version with `--build-arg`; the default is hatch-vcs's own
# `fallback-version` from pyproject.toml, so an unset ARG produces the same
# answer the build backend would have produced for a tagless tree rather than a
# different one. hatch-vcs wraps setuptools-scm, which is why the variable the
# RUN below exports is spelled the way it is.
ARG COMPONENT_VERSION=0.0.0

WORKDIR /app

# Named files rather than `COPY . .`, and the enumeration is the assertion's
# subject: no `.env`, no settings file outside `src/`, no `.cfg` or `.ini`, no
# secret. FR-38 makes configuration exclusively environmental.
#
# `component.toml` is in the list and is *not* an exception to that. It is the
# component's own declaration -- source that travels, which the materializer
# rewrites per combination -- and copying the source tree includes it. What must
# be absent is a file that *configures* this deployment.
#
# README.md and LICENSE are here because pyproject.toml names both, and the
# editable self-install below is built from that file.
COPY pixi.toml pixi.lock pyproject.toml component.toml manage.py README.md LICENSE ./
COPY src ./src

# One install, from the lock file, with no solve. `--locked` is NFR-5: a solve at
# build time produces a different component from the one the gate tested, which
# makes the lock file decorative. The download cache is removed in the same layer
# rather than a later one, because a later `rm` leaves the bytes in the image.
#
# The supply chain is conda-forge through pixi and nothing else (Consistency
# Conventions, FR-49): no pip, no apt-get, no system package.
RUN SETUPTOOLS_SCM_PRETEND_VERSION="${COMPONENT_VERSION}" pixi install --locked -e default \
    && rm -rf /root/.cache

# Static files are collected at **build** time, which is the first of AC #3's
# four zero-writable-path legs. `staticfiles/` is gitignored and exists only as a
# build product; `whitenoise.middleware.WhiteNoiseMiddleware` is in MIDDLEWARE
# and production.py's STORAGES names CompressedManifestStaticFilesStorage, so the
# application itself serves what is collected here. No sidecar, no shared volume,
# nothing written at run time.
#
# Under `config.settings.production`, deliberately: it is the only settings module
# that declares the manifest storage, and the manifest is the artefact being
# baked. That settings module runs stage 1 of the refusal contract on import, so
# the roster's variables have to be satisfiable -- they are supplied inline on
# this one RUN so that they do not persist as ENV into the image. They are build
# scaffolding and not configuration: `tests/unit/test_payload_properties.py`
# asserts that no ENV instruction in this file sets any of them, which is what
# keeps that distinction real rather than intended.
RUN DJANGO_SETTINGS_MODULE=config.settings.production \
    DJANGO_SECRET_KEY=build-stage-only-never-a-runtime-secret \
    DJANGO_ADMIN_URL=build-stage-only/ \
    DATABASE_URL=postgres://build:build@127.0.0.1:5432/build \
    COMPONENT_OIDC_ISSUER=https://build.invalid/realms/build \
    COMPONENT_IDENTITY_CLAIM=sub \
    COMPONENT_GROUP_CLAIM=groups \
    COMPONENT_STAFF_GROUP=build-stage-staff \
    COMPONENT_SUPERUSER_GROUP=build-stage-superuser \
    pixi run --frozen collectstatic \
    && rm -rf /root/.cache

# How an *arbitrary* UID gets access to a tree it has never been named in.
#
# The platform assigns a UID the image has never seen and puts it in group 0.
# There is no `/etc/passwd` entry for it and no way to chown for it in advance,
# so the only thing that can grant access ahead of time is the group: group 0
# gets the owner's permissions on everything under /app, and the assigned UID
# reads through its group membership. This is what makes `--user 12345:0` work,
# and it is why the numeric USER below is not the whole answer.
#
# Read access, not write, and the mode says so rather than the comment saying it.
# `g=rX` grants the group read everywhere and execute only where the owner
# already has it, which is exactly what the conda environment's binaries and its
# directories need to be traversed. `g=u` would have been shorter and would have
# copied the owner's bits -- and for a root-owned tree that means group *write*,
# so an arbitrary UID in group 0 could rewrite the application it is running.
# Nothing at run time writes under /app, and this is the instruction that makes
# that a property of the image rather than a habit of the code.
RUN chgrp -R 0 /app && chmod -R g=rX /app

# The one thing `pixi run` writes that is not the task's own doing, redirected to
# the tmpfs where AC #2 permits writes.
#
# After every `pixi run <task>` completes, pixi records a cache entry at
# `.pixi/task-cache-v0/<env>-<task>-<hash>.json`. It is written *after* the task's
# own exit status is known, so a failure to write it fails the whole invocation
# with the task's output already printed -- which is the confusing shape it
# arrives in: `manage migrate` applies every migration, reports success, and then
# `pixi` exits non-zero with `Permission denied (os error 13)` under a `g=rX`
# tree, or `Read-only file system (os error 30)` under `--read-only`.
#
# There is no flag and no environment variable to relocate or disable it --
# `PIXI_CACHE_DIR` and `RATTLER_CACHE_DIR` govern the package caches and not this
# one, and `--frozen`/`--no-install` govern solving and not caching. A symlink is
# what is left.
#
# It points at `/tmp` itself rather than a subdirectory of it. The target has to
# *exist* when pixi runs: the platform mounts `/tmp` as a fresh tmpfs, so a link
# to `/tmp/<anything>` dangles, and `mkdir` on a name already occupied by a
# dangling symlink fails with `File exists (os error 17)` rather than following
# it. `/tmp` is the one directory guaranteed to be there.
#
# This is not a hole in the read-only tree. The application still writes nothing
# under /app; what changes is where a pixi bookkeeping file lands, and it lands in
# the temporary directory AC #2 already sanctions.
RUN rm -rf /app/.pixi/task-cache-v0 && ln -s /tmp /app/.pixi/task-cache-v0

# HOME is a temporary directory because an arbitrary UID has no home. It has no
# /etc/passwd entry, so `getpwuid` fails and every tool that resolves `$HOME`
# falls back to `/` -- which is read-only. Pointing it at /tmp is what keeps that
# from being a start-up failure with an error message about neither UIDs nor
# filesystems.
#
# The pixi and rattler caches follow HOME for the same reason: their defaults sit
# under the home directory, and a cache path that cannot be created is a start-up
# failure rather than a slow start.
#
# PIXI_FROZEN and PIXI_NO_INSTALL together are `--as-is`: at run time `pixi run`
# performs no solve, checks no lock file against the manifest and modifies no
# environment, so it reads /app and writes nothing there. The environment was
# built above, from the lock file, and run time is not where that is
# reconsidered.
#
# PYTHONDONTWRITEBYTECODE is load-bearing rather than tidiness. The editable
# install resolves `config` and `django_service` from /app/src, and CPython
# writes `__pycache__` next to the source it imports -- which would be a write
# under /app on the first request of every container, and the exact thing AC #2
# says does not happen.
#
# None of these is application configuration. Every one is a property of the
# filesystem the payload runs on.
ENV HOME=/tmp \
    PIXI_CACHE_DIR=/tmp/.cache/pixi \
    RATTLER_CACHE_DIR=/tmp/.cache/rattler \
    PIXI_FROZEN=true \
    PIXI_NO_INSTALL=true \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Numeric, and non-root. A name would need an /etc/passwd entry, which is the one
# thing an arbitrary-UID platform will not honour; the number is what the runtime
# actually applies. The platform overrides this with a UID of its own, and the
# group-0 permissions above are what make that override work -- so this value is
# the floor rather than the expectation.
USER 1001

# Documentation of the port the `web` task binds, and nothing more: EXPOSE
# publishes nothing on its own. The bind address lives in the pixi task, which is
# the one place the process model is declared (AD-14).
EXPOSE 8000

# No VOLUME, for anything. Not for media, not for logs, not for static files.
# A declared volume would be a writable path the component depends on, which is
# the claim AC #2 denies: static is collected above and served by the
# application, user media is a non-goal (FR-25), logs go to the event stream as
# structured JSON on stdout with no files and no rotation, and sessions are
# database-backed (NFR-3). /tmp is mounted by the platform as a tmpfs and needs
# no declaration here.

# `pixi run web`, because AD-14 says the deployment repository invokes
# `pixi run <process>` and this image must not declare a second invocation
# mechanism beside it.
#
# The exec form rather than the shell form, so that pixi is PID 1 rather than a
# `/bin/sh -c` that would sit between the runtime and it. pixi forwards the
# platform's SIGTERM to the task it started, which is what the ordered drain in
# `config/workers.py` (Story 5.4) is built on; a shell wrapper is the classic way
# to lose that signal and turn every rolling deploy into a hard kill.
CMD ["pixi", "run", "web"]
