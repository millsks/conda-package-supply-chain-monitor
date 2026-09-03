"""R-1: is `django-storages` fit for the Django and Python this project locks?

FR-50 says channel availability *and* fitness against the pinned runtime are
checked before a feature is committed to. `django-storages` passes the first
half -- it is on conda-forge -- and its 1.14.6 release (2025-04-02) declares
support for neither Django 6.0 nor Python 3.14. Availability passed; fitness was
unknown. This module is what closes that gap, by exercising the package against
the locked runtime through the call sites FR-25's object-storage feature will
use.

**Not a unit test and not part of the gate.** It runs only in the
`spike-storage` pixi environment, which is the `dev` environment plus
`django-storages`, and only through `pixi run spike-storage`. The module is
named `spike_*.py` so `pytest tests/` -- what `test-cov` runs -- never collects
it. The recorded verdict lives beside the dependency declaration in `pixi.toml`
and in `docs/development.md`, "Object storage fitness (R-1)".

**What is proven and what is not.** The legs below marked mandatory run without
any S3-compatible server and must all pass for the verdict to be anything but
*failed*. The round-trip leg needs a live endpoint and a deliberate opt-in --
`SPIKE_STORAGE_ROUND_TRIP` -- and is skipped, loudly and naming the bound, when
that opt-in is absent. CG-2 applies: a silently narrowed claim reads as full
coverage and is worse than a bounded one, so the skip message and the recorded
verdict both say what went unproven.

**Why the opt-in exists, and why ambient credentials are ignored without it.**
The five configuration variables this module reads are the ordinary AWS ones.
A developer with an AWS profile exported, or a corporate S3 proxy in their
shell, would otherwise have had the round-trip leg write to, overwrite in and
delete from whatever bucket their environment happened to name -- on the
strength of running the command the documentation tells them to run. So the
fixture uses the unreachable `.invalid` fallbacks *unless* the opt-in is set,
and the leg refuses to run against the fallback endpoint. Nothing here reaches a
real bucket by accident.
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
import uuid
import warnings
from pathlib import Path
from typing import Any

import boto3
import django
import pytest
import storages
from botocore.config import Config
from django.core.checks import run_checks
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.core.files.storage import default_storage
from django.core.files.storage import storages as storage_handler

# Every test here is a spike. The round-trip leg adds `integration` on top,
# because it touches a real resource.
pytestmark = pytest.mark.spike

# The versions the verdict in `pixi.toml` is recorded against, from the spine's
# Stack table. Asserted rather than assumed: a verdict is only a statement about
# the versions it was produced on, so a bump to any of them has to re-run this
# spike and re-record the outcome rather than inherit it.
#
# This module runs outside the gate, so this assertion alone would not notice a
# bump made in `pixi.toml` and re-solved into `pixi.lock`. The gate-side half is
# `tests/unit/test_dependency_policy.py::test_the_recorded_verdict_names_the_versions_the_lock_resolves`,
# which reconciles the same four versions against the lock on every `pixi run
# ci`. Neither is redundant: this one checks what is *installed*, that one
# checks what is *locked*, and the verdict is a claim about both.
VERDICT_VERSIONS = {
    "django-storages": "1.14.6",
    "boto3": "1.43.65",
    "django": "5.2",
    "python": "3.14",
}

# 1.14.x ships two S3 backends. `storages.backends.s3.S3Storage` is the current
# one; `storages.backends.s3boto3.S3Boto3Storage` is the legacy name, kept as a
# subclass of it. Epic 7 Story 7.5 names the former. Both are asserted to exist
# and to stand in that relationship, so a future release that inverts or removes
# either is a failure here rather than a surprise there.
BACKEND_PATH = "storages.backends.s3.S3Storage"
LEGACY_BACKEND_PATH = "storages.backends.s3boto3.S3Boto3Storage"

# The `django.core.files.storage.Storage` methods FR-25's feature calls. This is
# the contract the spike checks, not the whole of the base class.
STORAGE_METHODS = (
    "save",
    "open",
    "exists",
    "delete",
    "url",
    "size",
    "listdir",
    "get_available_name",
)

# Of the eight above, these two are *not* overridden by django-storages: on
# 1.14.6 `S3Storage.save` and `S3Storage.open` are the identical function
# objects as `django.core.files.storage.Storage.save` / `.open`. Recorded rather
# than left implicit, because it changes what a signature check of those two
# means: binding Django 6.0's signature against Django 6.0's own cannot fail and
# says nothing about the package. The behaviour they delegate to lives in the
# private hooks below, which *are* overridden, and which the spike checks
# separately. Frozen as a set, so a release that starts overriding either -- or
# stops overriding one of the other six -- fails here rather than quietly
# changing what the verdict covers.
INHERITED_FROM_DJANGO = frozenset({"save", "open"})

# Where the real behaviour behind those two lives, and the call Django's own
# base class makes to it. `Storage.open` is `return self._open(name, mode)`
# and `Storage.save` ends in `name = self._save(name, content)` (Django 6.0,
# `django/core/files/storage/base.py:22` and `:49`), so each hook must accept
# exactly two positional arguments. The base class declares neither method --
# they are abstract by convention, not by signature -- so there is nothing to
# compare a signature *against*; the call the base makes is the contract, and
# binding it is the check.
INTERNAL_HOOK_ARITY = {"_save": 2, "_open": 2}

# The environment variables the backend is configured from, and the `OPTIONS`
# key each one feeds. FR-38: configuration is exclusively environmental, so this
# mapping -- not a settings file, not a boto3 profile -- is the whole
# configuration surface *of this module*.
#
# It is not the package's own surface, and the difference is the finding Epic 7
# Story 7.5 has to act on. django-storages 1.14.6 defaults `access_key` and
# `secret_key` from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in the process
# environment (via its internal `lookup_env`), but reads `endpoint_url`,
# `region_name` and `bucket_name` from **Django settings alone**. FR-38 is
# therefore the application's job, not something the package delivers: it is the
# settings module that has to route those three from the environment into
# `STORAGES["default"]["OPTIONS"]`, which is exactly what this module does.
OPTION_FOR_VARIABLE = {
    "AWS_S3_ENDPOINT_URL": "endpoint_url",
    "AWS_S3_REGION_NAME": "region_name",
    "AWS_STORAGE_BUCKET_NAME": "bucket_name",
    "AWS_ACCESS_KEY_ID": "access_key",
    "AWS_SECRET_ACCESS_KEY": "secret_key",
}

# The two of the five django-storages 1.14.6 reads from the process environment
# on its own. The other three reach the backend only because this module passes
# them, which is the asymmetry `test_configuration_reaches_the_backend_from_the_environment_and_from_django_settings`
# proves by withholding each option in turn.
ENVIRONMENT_SOURCED_OPTIONS = frozenset({"access_key", "secret_key"})

# Values used unless the round-trip opt-in is set. `.invalid` is reserved by
# RFC 2606 and resolves nowhere, so a leg that accidentally opened a connection
# would fail rather than reach something real. Nothing in the mandatory legs
# performs I/O.
FALLBACK_ENVIRONMENT = {
    "AWS_S3_ENDPOINT_URL": "https://s3.spike.invalid",
    "AWS_S3_REGION_NAME": "us-east-1",
    "AWS_STORAGE_BUCKET_NAME": "spike-bucket",
    "AWS_ACCESS_KEY_ID": "spike-access-key",
    "AWS_SECRET_ACCESS_KEY": "spike-secret-value",
}

# The endpoint variable, named separately because the round-trip leg reports it.
ENDPOINT_VARIABLE = "AWS_S3_ENDPOINT_URL"

# The deliberate opt-in that arms the round-trip leg. Two things hang off it and
# both matter: without it the fixture ignores ambient values entirely (so a
# developer's real credentials cannot be picked up by running the documented
# command), and the round-trip leg skips. Gating on the *opt-in* rather than on
# "the endpoint looks unreachable" is deliberate -- an earlier form of this leg
# tested `endpoint.endswith(".invalid")`, which coupled the gate to the spelling
# of a fallback constant: adding a port to that constant would have armed the
# leg, and a real endpoint at an internal `.invalid` name would have been
# skipped while the bound was reported unclosed.
ROUND_TRIP_OPT_IN = "SPIKE_STORAGE_ROUND_TRIP"
ROUND_TRIP_TRUTHY = frozenset({"1", "true", "yes", "on"})

# boto3's two file-based configuration sources. FR-38 forbids a configuration
# file in the image, so both are pointed at paths that do not exist for the
# duration of a spike: anything the backend then knows, it learned from the
# environment or from Django settings.
BOTO_CONFIG_FILE_VARIABLES = ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE")

# Modules whose import-time warnings the deprecation leg has to be able to see.
# `storages` alone was not enough: boto3 and botocore are imported at the top of
# this module, so their import-time warnings had already fired -- once, before
# any recorder existed -- and the leg was checking them against silence it got
# for free while the verdict named boto3 as one of the versions it is a
# statement about.
WARNING_SENSITIVE_PACKAGES = ("storages", "boto3", "botocore")

# Warning categories that would mean the package is calling a Django API on its
# way out. `RemovedInDjango*Warning` is matched by name because the class is
# version-specific -- `RemovedInDjango70Warning` today, a different name in the
# next cycle -- and pinning the current one would make this check lapse silently.
REMOVAL_WARNING_PREFIX = "RemovedInDjango"
DEPRECATION_CATEGORIES = (DeprecationWarning, PendingDeprecationWarning)

# The one place `S3Storage` renames a parameter Django's base class declares:
# `listdir(self, path)` in Django 6.0, `listdir(self, name)` in
# django-storages 1.14.6. Recorded rather than either failed on or hidden.
#
# Why it is harmless is worth stating precisely, because the reason is the part
# a future reader will reuse for the next rename. It is *not* that Django calls
# these methods positionally only -- Django makes at least two keyword calls
# into this contract: `django/db/models/fields/files.py:98` calls
# `self.storage.save(name, content, max_length=self.field.max_length)` and
# `django/core/files/storage/base.py:43` calls
# `self.get_available_name(name, max_length=max_length)`. It is that `listdir`
# is not one of those call sites, and that the renamed parameter is not
# `max_length`. A rename touching `save`, `get_available_name` or the
# `max_length` parameter of either would break Django itself.
#
# Frozen as a set so a *second* such divergence, or this one disappearing, fails
# the spike instead of passing unremarked.
#
# Each entry is (method, parameter position, name Django declares, name the
# backend declares).
RECORDED_KEYWORD_DIVERGENCES = {("listdir", 1, "path", "name")}

# The keyword call sites Django 6.0 makes into this contract, as (method,
# parameter). Asserted rather than described, so the claim above cannot rot into
# a comment nobody re-checks.
DJANGO_KEYWORD_CALL_SITES = {("save", "max_length"), ("get_available_name", "max_length")}


def _import_backend_class(path: str) -> type[Storage]:
    """Import a storage backend by its dotted path.

    Args:
        path: A dotted path such as ``storages.backends.s3.S3Storage``.

    Returns:
        The imported class.
    """
    module_path, _, class_name = path.rpartition(".")
    module = importlib.import_module(module_path)
    imported: type[Storage] = getattr(module, class_name)
    return imported


def _round_trip_is_armed() -> bool:
    """Report whether the deliberate opt-in for the live round-trip leg is set."""
    return os.environ.get(ROUND_TRIP_OPT_IN, "").strip().lower() in ROUND_TRIP_TRUTHY


def _options_from_environment() -> dict[str, str]:
    """Build the ``STORAGES["default"]["OPTIONS"]`` dict from the environment.

    Reads `os.environ` and nothing else -- no settings module, no file, no
    boto3 profile. This is FR-38's rule expressed as code, and it is the shape
    Epic 7 Story 7.5 has to reproduce in `config/settings/`.

    **One thing Story 7.5 must not reproduce verbatim.** The subscript below
    raises a bare `KeyError` when a variable is missing, and that is acceptable
    only here, in a spike whose fixture always sets all five. A settings module
    that copied it would abort at import with `KeyError:
    'AWS_STORAGE_BUCKET_NAME'` on a deployment that forgot one -- an opaque
    traceback where Django's own contract is
    `django.core.exceptions.ImproperlyConfigured` naming the variable. Story 7.5
    raises that instead. `test_a_missing_variable_is_a_named_failure_rather_than_a_silent_default`
    pins the observed behaviour so the requirement rests on a fact rather than a
    reading.

    Returns:
        The backend's keyword configuration, one entry per declared variable.

    Raises:
        KeyError: If any of the five variables is unset.
    """
    return {option: os.environ[variable] for variable, option in OPTION_FOR_VARIABLE.items()}


def _safety_options() -> dict[str, Any]:
    """Return the options that keep a live round trip from damaging a real bucket.

    Two of them, and each closes a failure this spike could otherwise cause
    rather than observe:

    * ``file_overwrite`` defaults to **True** in django-storages, so `save()`
      would silently replace a pre-existing object at the key it is given and
      teardown would then delete it. With it False, `get_available_name` picks a
      free name instead, and the round-trip leg additionally refuses to start if
      its key is already taken.
    * ``client_config`` carries a short connect and read timeout and a single
      attempt. Without it, botocore's defaults (60 s connect, 60 s read, plus a
      retry budget) make the documented "point it at MinIO and re-run" remedy
      hang for minutes against a host that is simply not there.

    The other three `Config` fields restate what the backend would have computed
    for itself -- `S3Storage` builds its default client config from
    `addressing_style`, `signature_version` and `proxies`, all of which are None
    here -- so supplying a config of our own gives nothing else up.

    Returns:
        Extra `OPTIONS` entries to merge over the environment-sourced ones.
    """
    return {
        "file_overwrite": False,
        "client_config": Config(
            s3={"addressing_style": None},
            signature_version=None,
            proxies=None,
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 1},
        ),
    }


def _positional_parameters(signature: inspect.Signature) -> list[inspect.Parameter]:
    """Return the parameters of a signature that a positional call can fill."""
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    return [parameter for parameter in signature.parameters.values() if parameter.kind in positional]


def _keyword_divergences(method: str) -> list[tuple[str, int, str, str]]:
    """Return the parameters the backend renames relative to Django's base class.

    A rename is invisible to a positional caller and fatal to a keyword one, so
    it is neither a plain pass nor a plain failure. It is reported.

    Args:
        method: The `Storage` method to compare.

    Returns:
        One (method, position, base name, backend name) tuple per renamed
        parameter, empty when the names agree.
    """
    base = _positional_parameters(inspect.signature(getattr(Storage, method)))
    backend = _positional_parameters(inspect.signature(getattr(_import_backend_class(BACKEND_PATH), method)))
    return [
        (method, index, declared.name, implemented.name)
        for index, (declared, implemented) in enumerate(zip(base, backend, strict=False))
        if declared.name != implemented.name
    ]


@pytest.fixture
def spike_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """Put the five configuration variables in the environment, and no file beside them.

    Ambient values are used **only** when `SPIKE_STORAGE_ROUND_TRIP` arms the
    live leg. Without that opt-in the fallbacks win outright, whatever the shell
    already exports: the mandatory legs perform no I/O, so they gain nothing from
    real values, and preferring ambient ones is how `pixi run spike-storage`
    came to be able to reach a developer's production bucket.

    Args:
        monkeypatch: pytest's environment patcher; it restores on teardown.
        tmp_path: A directory whose non-existent children stand in for the boto3
            configuration files FR-38 forbids.

    Returns:
        The variable-to-value mapping now in force.
    """
    armed = _round_trip_is_armed()
    values = {
        variable: (os.environ.get(variable) if armed else None) or FALLBACK_ENVIRONMENT[variable]
        for variable in OPTION_FOR_VARIABLE
    }
    for variable, value in values.items():
        monkeypatch.setenv(variable, value)
    for variable in BOTO_CONFIG_FILE_VARIABLES:
        monkeypatch.setenv(variable, str(tmp_path / "this-file-does-not-exist"))
    return values


@pytest.fixture
def configured_storage(settings: Any, spike_environment: dict[str, str]) -> Storage:
    """Configure `STORAGES["default"]` from the environment and return what Django resolves.

    Args:
        settings: pytest-django's settings fixture. Assigning through it emits
            `setting_changed`, which is what resets Django's storage handler and
            `default_storage`; rebinding `settings.STORAGES` any other way would
            leave both caching the previous backend.
        spike_environment: The environment this configuration is built from.

    Returns:
        The backend instance `django.core.files.storage.storages["default"]`
        hands back.
    """
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": BACKEND_PATH, "OPTIONS": {**_options_from_environment(), **_safety_options()}},
    }
    resolved: Storage = storage_handler["default"]
    return resolved


def test_the_runtime_under_test_is_the_runtime_the_verdict_names() -> None:
    """The verdict is a statement about specific versions, so the versions are asserted.

    Read back from the installed distributions rather than taken from the spine
    on trust. A bump to any of the four invalidates the recorded verdict and has
    to re-run this spike, which is what failing here forces.

    This module runs outside the gate, so this check fires only when someone runs
    the spike. The gate-side counterpart reads the same four versions out of the
    verdict comment and reconciles them against `pixi.lock`
    (`tests/unit/test_dependency_policy.py`), which is what catches a bump that
    was solved but never re-spiked.
    """
    running = {
        "django-storages": storages.__version__,
        "boto3": boto3.__version__,
        "django": ".".join(str(part) for part in django.VERSION[:2]),
        "python": ".".join(str(part) for part in sys.version_info[:2]),
    }
    assert running == VERDICT_VERSIONS, (
        f"the spike is running against {running}, not the versions the recorded verdict names "
        f"({VERDICT_VERSIONS}). Re-run the spike and re-record the verdict in pixi.toml and "
        "docs/development.md rather than carrying the old one forward."
    )


def test_the_backend_module_imports_and_the_storage_class_instantiates(spike_environment: dict[str, str]) -> None:
    """AC #1: the package loads and constructs under Django 6.0 on Python 3.14.

    Both class paths 1.14.x ships are checked, and the relationship between them
    is asserted rather than described: the legacy `S3Boto3Storage` is a subclass
    of the current `S3Storage`, so naming the current one -- which Story 7.5
    does -- gives up nothing.
    """
    backend = _import_backend_class(BACKEND_PATH)
    legacy = _import_backend_class(LEGACY_BACKEND_PATH)

    assert issubclass(backend, Storage), f"{BACKEND_PATH} is not a django.core.files.storage.Storage"
    assert issubclass(legacy, backend), (
        f"{LEGACY_BACKEND_PATH} is no longer a subclass of {BACKEND_PATH}; the two backends have diverged "
        "and Story 7.5's choice of class path has to be re-taken."
    )

    instance = backend(**_options_from_environment())
    assert isinstance(instance, Storage)
    assert instance.bucket_name == spike_environment["AWS_STORAGE_BUCKET_NAME"]
    assert instance.endpoint_url == spike_environment["AWS_S3_ENDPOINT_URL"]


def test_django_resolves_the_configured_backend_as_the_default_storage(
    configured_storage: Storage,
    spike_environment: dict[str, str],
) -> None:
    """AC #1: `storages["default"]` and `default_storage` both resolve to the backend.

    Two handles, asserted separately, because they are two mechanisms: the
    handler is a mapping built from `STORAGES`, and `default_storage` is a lazy
    proxy that resolves through it. A backend reachable by one and not the other
    would break half the call sites in Django's own file field machinery.
    """
    backend = _import_backend_class(BACKEND_PATH)

    assert isinstance(configured_storage, backend)
    assert isinstance(default_storage, backend), (
        "default_storage did not resolve to the configured backend; STORAGES['default'] is set but the "
        "lazy proxy is still holding the previous storage."
    )
    assert default_storage.bucket_name == spike_environment["AWS_STORAGE_BUCKET_NAME"]
    assert configured_storage.bucket_name == spike_environment["AWS_STORAGE_BUCKET_NAME"]


@pytest.mark.parametrize("method", STORAGE_METHODS)
def test_every_storage_method_the_feature_calls_is_present(method: str, configured_storage: Storage) -> None:
    """AC #1: each named method exists on the resolved backend and is callable."""
    attribute = getattr(configured_storage, method, None)
    assert attribute is not None, f"{BACKEND_PATH} has no {method}(); FR-25's feature calls it"
    assert callable(attribute), f"{BACKEND_PATH}.{method} is not callable"


@pytest.mark.parametrize("method", STORAGE_METHODS)
def test_every_storage_method_accepts_the_call_django_6_makes(method: str) -> None:
    """AC #1: the backend's signature accepts what Django 6.0's `Storage` declares.

    This is the class of breakage a package predating Django 6.0 is most likely
    to exhibit, and it is checked by binding rather than by eyeballing: the
    minimal positional call Django's base class permits, and the maximal one,
    are both bound against the backend's own signature. Either raising
    `TypeError` means a call site Django makes would fail at runtime.

    Extra *optional* parameters are fine and expected -- `S3Storage.url` adds
    `parameters`, `expire` and `http_method`. An extra *required* one is not,
    and fails the maximal bind.

    Two of the eight -- `save` and `open` -- are inherited unchanged from
    Django, so for those this binds Django's signature against itself and cannot
    fail. That is not a hole left open: it is recorded in
    `INHERITED_FROM_DJANGO`, frozen by
    `test_the_methods_the_backend_inherits_unchanged_are_the_recorded_ones`, and
    the overrides those two actually delegate to are checked by
    `test_the_internal_hooks_accept_the_call_djangos_base_class_makes`.
    """
    base = _positional_parameters(inspect.signature(getattr(Storage, method)))
    backend_signature = inspect.signature(getattr(_import_backend_class(BACKEND_PATH), method))

    required = [parameter for parameter in base if parameter.default is inspect.Parameter.empty]
    for arity, label in ((len(required), "required"), (len(base), "full")):
        try:
            backend_signature.bind(*[object()] * arity)
        except TypeError as error:
            message = (
                f"{BACKEND_PATH}.{method}{backend_signature} rejects the {label} positional call "
                f"Django 6.0's Storage.{method}{inspect.signature(getattr(Storage, method))} declares: {error}"
            )
            pytest.fail(message)


def test_the_methods_the_backend_inherits_unchanged_are_the_recorded_ones() -> None:
    """AC #1: which of the eight say something about django-storages, and which do not.

    `S3Storage.save` and `S3Storage.open` are the *identical function objects* as
    Django 6.0's `Storage.save` / `Storage.open` -- django-storages overrides the
    private `_save` / `_open` hooks, not the public methods. Any signature check
    of those two therefore compares Django with Django and cannot fail, so the
    verdict must not list them as evidence about the package in the same breath
    as the six that are genuinely overridden.

    Frozen from both directions. A release that begins overriding `save` makes
    the recorded set too large; one that stops overriding `listdir` makes it too
    small. Either changes what the other checks in this module cover, so either
    has to be re-recorded rather than absorbed.
    """
    backend = _import_backend_class(BACKEND_PATH)
    inherited = frozenset(method for method in STORAGE_METHODS if getattr(backend, method) is getattr(Storage, method))
    assert inherited == INHERITED_FROM_DJANGO, (
        f"{BACKEND_PATH} inherits {sorted(inherited)} unchanged from Django 6.0's Storage, while the "
        f"recorded methods are {sorted(INHERITED_FROM_DJANGO)}. Re-record here and in pixi.toml's verdict "
        "together: an inherited method is one whose signature check proves nothing about django-storages."
    )


@pytest.mark.parametrize("hook", sorted(INTERNAL_HOOK_ARITY))
def test_the_internal_hooks_accept_the_call_djangos_base_class_makes(hook: str) -> None:
    """AC #1: the overrides behind the two inherited methods take Django's internal call.

    `Storage.save` and `Storage.open` are inherited unchanged, so the behaviour
    django-storages supplies for them sits in `_save` and `_open`. Django's base
    class calls each with exactly two positional arguments; a hook that rejected
    that call would fail on the first `save()` or `open()` at runtime while every
    public-signature check in this module still passed.

    The base class declares neither hook -- they raise `NotImplementedError` only
    by not existing -- so this binds the call rather than comparing signatures.
    That the base declares neither is asserted too, because if a future Django
    started declaring them, the comparison this module *should* be making would
    change.
    """
    backend = _import_backend_class(BACKEND_PATH)
    assert not hasattr(Storage, hook), (
        f"Django 6.0's Storage now declares {hook}. This test binds the call the base class makes because "
        "there was no declared signature to compare against; with one, compare signatures instead."
    )
    implemented = getattr(backend, hook, None)
    assert implemented is not None, (
        f"{BACKEND_PATH} does not override {hook}. Django's Storage.save/.open delegate to it, and "
        f"{BACKEND_PATH} inherits both unchanged, so without {hook} neither method has an implementation."
    )

    # `implemented` is the unbound function off the class, so the receiver is
    # one of the positional arguments here where it is implicit in the source.
    signature = inspect.signature(implemented)
    try:
        signature.bind(*[object()] * (1 + INTERNAL_HOOK_ARITY[hook]))
    except TypeError as error:
        pytest.fail(
            f"{BACKEND_PATH}.{hook}{signature} rejects the {INTERNAL_HOOK_ARITY[hook]}-argument positional "
            f"call Django 6.0's Storage makes to it: {error}"
        )


def test_the_only_parameter_rename_is_the_recorded_one() -> None:
    """AC #1: parameter *names* are compared too, and divergence is recorded, not hidden.

    The positional check above passes through a renamed parameter without
    noticing, because a positional call does not use the name. The rename that
    exists is on `listdir`, which is not one of the methods Django calls by
    keyword, so it is not a failure -- but leaving it unmentioned would be the
    silently narrowed claim CG-2 forbids. It is frozen instead: this fails if a
    new rename appears or if the recorded one goes away.
    """
    found = {divergence for method in STORAGE_METHODS for divergence in _keyword_divergences(method)}
    assert found == RECORDED_KEYWORD_DIVERGENCES, (
        f"the backend's parameter names diverge from Django 6.0's Storage in {sorted(found)}, and the "
        f"recorded set is {sorted(RECORDED_KEYWORD_DIVERGENCES)}. Update the record in this module and "
        "the verdict in pixi.toml together -- each entry is a keyword call site that would raise TypeError."
    )


def test_the_renamed_parameter_is_not_one_django_passes_by_keyword() -> None:
    """AC #1: *why* the recorded rename is harmless, asserted rather than asserted about.

    Django 6.0 does make keyword calls into this contract --
    `django/db/models/fields/files.py:98` passes `max_length=` to `save`, and
    `django/core/files/storage/base.py:43` passes `max_length=` to
    `get_available_name`. "Positional calls are the only kind Django makes" was
    the reason originally recorded for tolerating the `listdir(path -> name)`
    rename, and it was simply false; the conclusion survived only by luck. The
    true reason is narrower and is what this checks: each parameter Django names
    in a keyword call is spelled the same way by the backend, and `listdir` is
    not among the methods it names at all.
    """
    backend = _import_backend_class(BACKEND_PATH)
    renamed = {(method, declared) for method, _index, declared, _implemented in RECORDED_KEYWORD_DIVERGENCES}

    collisions = sorted(renamed & DJANGO_KEYWORD_CALL_SITES)
    assert collisions == [], (
        f"a recorded parameter rename lands on a keyword call site Django itself makes: {collisions}. "
        "Django would raise TypeError on that call, so the divergence is a failure and not a record."
    )

    missing = sorted(
        f"{method}({parameter}=...)"
        for method, parameter in DJANGO_KEYWORD_CALL_SITES
        if parameter not in inspect.signature(getattr(backend, method)).parameters
    )
    assert missing == [], (
        f"{BACKEND_PATH} does not accept the keyword arguments Django 6.0 passes: {missing}. "
        "These are real call sites in Django's own file-field machinery, not hypothetical ones."
    )


def test_import_and_instantiation_raise_no_deprecation_or_removal_warning(
    monkeypatch: pytest.MonkeyPatch,
    spike_environment: dict[str, str],
) -> None:
    """AC #1: a removed-API warning here is the early signal of a Django 6.1 break.

    Every package the verdict names a version for is evicted from `sys.modules`
    and re-imported inside the recorder -- `storages`, and also `boto3` and
    `botocore`, which this module imports at the top and whose import-time
    warnings would otherwise have fired once, before any recorder existed, and
    been checked against silence they got for free. `monkeypatch.delitem` is what
    does the eviction, so the original modules are put back on teardown and no
    later test ends up holding a class object from a second import.
    """
    assert spike_environment
    evicted = [
        name
        for name in list(sys.modules)
        if any(name == package or name.startswith(f"{package}.") for package in WARNING_SENSITIVE_PACKAGES)
    ]
    assert evicted, f"none of {WARNING_SENSITIVE_PACKAGES} is imported; this check would pass vacuously"
    for name in evicted:
        monkeypatch.delitem(sys.modules, name)

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        importlib.import_module("boto3")
        backend = _import_backend_class(BACKEND_PATH)
        backend(**_options_from_environment())

    offenders = [
        f"{warning.category.__name__}: {warning.message}"
        for warning in recorded
        if issubclass(warning.category, DEPRECATION_CATEGORIES)
        or warning.category.__name__.startswith(REMOVAL_WARNING_PREFIX)
    ]
    assert offenders == [], (
        f"{BACKEND_PATH} or one of boto3/botocore warns on import or instantiation: {offenders}. A "
        "RemovedInDjango* warning means the package is calling an API Django has already scheduled for "
        "removal, which dates the verdict."
    )


def test_django_system_checks_report_no_error_with_the_backend_configured(configured_storage: Storage) -> None:
    """AC #1: the check framework is run with the backend configured -- and it is a weak signal.

    Recorded honestly, because the spec mandates the assertion and CG-2 forbids
    letting it be read as more than it is. **Django does not instantiate a
    storage backend during system checks.** Nothing in `run_checks()` resolves
    `STORAGES["default"]`: the only check that reads `STORAGES` at all is
    `django.contrib.staticfiles.checks.check_storages`, and it inspects the
    `staticfiles` alias. Setting `STORAGES["default"]["BACKEND"]` to
    `"nonexistent.module.NoSuchStorage"` and calling `run_checks()` returns an
    empty list -- verified, not reasoned about.

    So this leg proves that configuring the backend introduces no *other*
    error into the check framework. It does not prove the backend is
    check-clean, and the verdict says so in the same words.
    """
    assert configured_storage is not None
    serious = [str(message) for message in run_checks() if message.is_serious()]
    assert serious == [], f"django.core.checks.run_checks() reports errors with {BACKEND_PATH} configured: {serious}"


def test_moving_every_environment_variable_moves_the_whole_configuration(
    monkeypatch: pytest.MonkeyPatch,
    spike_environment: dict[str, str],
    tmp_path: Path,
) -> None:
    """AC #1 and FR-38: every value this module routes does move with the environment.

    Half of the FR-38 claim, and the weaker half. Giving every variable a second
    value and rebuilding shows the configuration follows the environment -- but
    it can only show that for the values the rebuild itself injects, because
    `BaseStorage.__init__` applies explicit keyword arguments last and they win
    over `get_default_settings()`. The other half -- that nothing reaches the
    backend from a source that is *not* the environment -- is the sibling test
    below, and it is the one that made FR-38's real shape visible.

    boto3's two configuration files are pointed at paths that do not exist for
    the duration, and that absence is asserted rather than assumed.
    """
    for variable in BOTO_CONFIG_FILE_VARIABLES:
        declared = Path(os.environ[variable])
        assert not declared.exists(), (
            f"{variable} points at {declared}, which exists; the spike would be reading a configuration file"
        )

    moved = {variable: f"moved-{value}" for variable, value in spike_environment.items()}
    moved[ENDPOINT_VARIABLE] = "https://moved.spike.invalid"
    for variable, value in moved.items():
        monkeypatch.setenv(variable, value)

    backend = _import_backend_class(BACKEND_PATH)
    rebuilt = backend(**_options_from_environment())

    assert rebuilt.endpoint_url == moved[ENDPOINT_VARIABLE]
    assert rebuilt.region_name == moved["AWS_S3_REGION_NAME"]
    assert rebuilt.bucket_name == moved["AWS_STORAGE_BUCKET_NAME"]
    assert rebuilt.access_key == moved["AWS_ACCESS_KEY_ID"]
    assert rebuilt.secret_key == moved["AWS_SECRET_ACCESS_KEY"]
    assert str(tmp_path) in os.environ["AWS_CONFIG_FILE"]


def test_configuration_reaches_the_backend_from_the_environment_and_from_django_settings(
    settings: Any,
    spike_environment: dict[str, str],
) -> None:
    """FR-38, stated accurately: only two of the five come from the environment on their own.

    Proved by *withholding* rather than by moving. Each option is omitted from
    the constructor in turn and the resulting attribute is read:

    * `access_key` and `secret_key` survive the omission, because
      django-storages' `get_default_settings()` falls back to `lookup_env` on
      `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
    * `endpoint_url`, `region_name` and `bucket_name` come back **None**. The
      package does not read the environment for them at all -- it reads
      `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME` and `AWS_STORAGE_BUCKET_NAME`
      from *Django settings*, which the last section of this test demonstrates
      by putting a value there and watching it arrive.

    That is the finding Epic 7 Story 7.5 has to act on, and it is why the
    recorded verdict does not say "configuration comes from environment variables
    alone" without qualification: FR-38 is satisfied by the *application* routing
    those three from the environment into `STORAGES["default"]["OPTIONS"]`, which
    is what `_options_from_environment` does. Nothing about the package delivers
    it for free.
    """
    backend = _import_backend_class(BACKEND_PATH)
    options = _options_from_environment()

    for option in OPTION_FOR_VARIABLE.values():
        withheld = {name: value for name, value in options.items() if name != option}
        observed = getattr(backend(**withheld), option)
        if option in ENVIRONMENT_SOURCED_OPTIONS:
            assert observed == options[option], (
                f"{option} was withheld from the constructor and did not fall back to the process "
                f"environment; django-storages 1.14.6 reads {sorted(ENVIRONMENT_SOURCED_OPTIONS)} from it. "
                "Re-record which values the package sources itself -- the verdict names them."
            )
        else:
            assert observed is None, (
                f"{option} was withheld from the constructor and came back as {observed!r} rather than None. "
                "Something other than this module's environment routing is configuring the backend -- a "
                "Django setting, a boto3 profile or a package default -- and the verdict has to say so."
            )

    settings.AWS_STORAGE_BUCKET_NAME = "bucket-from-django-settings"
    from_settings = backend(**{name: value for name, value in options.items() if name != "bucket_name"})
    assert from_settings.bucket_name == "bucket-from-django-settings", (
        "django-storages did not read AWS_STORAGE_BUCKET_NAME from Django settings. The verdict records "
        "that it reads endpoint_url, region_name and bucket_name from settings alone, which is why FR-38 "
        "is the application's job; if that has changed, the verdict has to change with it."
    )


def test_a_missing_variable_is_a_named_failure_rather_than_a_silent_default(
    monkeypatch: pytest.MonkeyPatch,
    spike_environment: dict[str, str],
) -> None:
    """L6 / FR-38: an unset variable must not become an empty string or a default.

    `_options_from_environment` subscripts `os.environ`, so a missing variable
    raises `KeyError` naming it. That is the right *shape* -- loud, and naming
    the variable -- and the wrong *exception* for a settings module: Django's own
    contract for a misconfigured deployment is `ImproperlyConfigured`. Pinned
    here so Story 7.5's obligation rests on an observed behaviour rather than on
    a reading of the helper, and so a future edit that turned the subscript into
    a `.get(variable, "")` fails rather than shipping a backend configured with
    empty credentials.
    """
    assert spike_environment
    monkeypatch.delenv("AWS_STORAGE_BUCKET_NAME")
    with pytest.raises(KeyError, match="AWS_STORAGE_BUCKET_NAME"):
        _options_from_environment()


def test_the_backend_builds_a_boto3_client_without_touching_the_network(configured_storage: Storage) -> None:
    """AC #1: botocore's session, endpoint resolution and signer run on Python 3.14.

    `S3Storage.connection` is lazy, so every other mandatory leg completes
    without botocore ever constructing anything -- which left the whole
    session/credential/signer surface unexercised while `boto3 1.43.65` sat in
    the verdict's "Tested against" line, reading as coverage it did not have.
    This touches it. Building the resource resolves the endpoint, selects a
    signature version and assembles the credential chain, all offline: no
    request is made until a method is called on it, and none is here.

    The `.invalid` endpoint is what keeps that honest -- if construction did
    reach the network, this would fail rather than pass quietly.
    """
    connection = configured_storage.connection
    assert connection is not None, "S3Storage.connection returned nothing; botocore built no resource"
    assert connection.meta.client.meta.endpoint_url == configured_storage.endpoint_url, (
        "the boto3 client resolved an endpoint other than the configured one; endpoint resolution on "
        "botocore 1.43.65 / Python 3.14 does not honour endpoint_url as the backend passes it."
    )


@pytest.mark.integration
def test_the_object_round_trip_holds_against_a_live_endpoint(
    configured_storage: Storage,
    spike_environment: dict[str, str],
) -> None:
    """The optional leg: save, exists, open, size, url and delete against a real bucket.

    Armed only by `SPIKE_STORAGE_ROUND_TRIP`, never by credentials that merely
    happen to be exported. It is not armed in the ordinary case -- no
    S3-compatible server is stood up for this spike -- and the skip below is how
    that bound is *reported* rather than passed over in silence. The recorded
    verdict in `pixi.toml` says the same thing in the same words: what the
    mandatory legs prove is that the package loads, configures and conforms; the
    wire protocol against a real bucket is unproven until this leg runs.

    This is the deliberate `pytest.skip` Task 6 requires, and it is not the
    evasion `tests/unit/test_suite_policy.py` bans: it guards a resource that
    was never provisioned, not an assertion that turned out to be inconvenient.
    The whole module is outside the gate, so nothing here can dodge it.

    **What "leaves the bucket as it found it" means here, precisely.** The leg
    writes one object under a key containing a fresh UUID, having first asserted
    that key does not exist; `file_overwrite` is False, so a collision would be
    renamed rather than silently overwritten. Teardown deletes the key it
    intended to write *and* whatever name `save()` returned, so an object created
    by a `save()` that then raised is still removed. It does not touch anything
    it did not create, and it creates nothing that outlives the test.
    """
    if not _round_trip_is_armed():
        pytest.skip(
            f"{ROUND_TRIP_OPT_IN} is not set, so the live round trip is not armed. "
            "BOUND ON THE VERDICT: the save -> exists -> open -> size -> url -> delete round trip did not "
            "run. django-storages 1.14.6 is proven to import, configure and satisfy Django 5.2's Storage "
            "contract on Python 3.14; it is NOT proven against a live bucket. Set "
            f"{ROUND_TRIP_OPT_IN}=1 with {ENDPOINT_VARIABLE} and the four other AWS_* variables pointing at "
            "a MinIO or S3 endpoint you are willing to have written to, then re-run "
            "`pixi run spike-storage` to close it."
        )

    endpoint = spike_environment[ENDPOINT_VARIABLE]
    assert endpoint != FALLBACK_ENVIRONMENT[ENDPOINT_VARIABLE], (
        f"{ROUND_TRIP_OPT_IN} arms the live leg but {ENDPOINT_VARIABLE} is still the unreachable fallback "
        f"{endpoint!r}. Point it at a real S3-compatible endpoint, or unset {ROUND_TRIP_OPT_IN}."
    )

    key = f"spike/r1-round-trip-{uuid.uuid4().hex}.txt"
    payload = b"R-1 round trip"
    assert not configured_storage.exists(key), (
        f"{key} already exists in the bucket. The leg refuses to write over an object it did not create."
    )

    written = {key}
    try:
        stored = configured_storage.save(key, ContentFile(payload))
        written.add(stored)
        assert stored == key, (
            f"save() stored {stored!r} rather than the free key {key!r} it was given; get_available_name "
            "renamed it, which means the key was taken between the check above and the write."
        )
        assert configured_storage.exists(stored)
        with configured_storage.open(stored) as handle:
            assert handle.read() == payload
        assert configured_storage.size(stored) == len(payload)
        assert configured_storage.url(stored)
    finally:
        for candidate in sorted(written):
            if configured_storage.exists(candidate):
                configured_storage.delete(candidate)

    leftover = sorted(candidate for candidate in written if configured_storage.exists(candidate))
    assert leftover == [], f"the round-trip leg left objects behind in the bucket: {leftover}"
