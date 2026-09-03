"""The two feature-scoped forbidden states, and the regions that own them (AC #1-#4).

Conditions 8 and 9 of the refusal table -- an in-process cache backend where the
Redis feature is selected, and eager task execution where background task
processing is selected. They are the only two of the fourteen forbidden states
that are conditional, and they are conditional because
`config/settings/production.py` hardcodes `django_redis.cache.RedisCache` with no
feature branch: a component that did not select Redis legitimately falls back to
Django's in-process cache in a deployment, so an unconditional refusal would
reject valid combinations for having exactly the cache they were built with.

**Which content belongs to which feature is carried by markers, not by prose.**
The spine's Test-location convention says a feature's tests carry that feature's
disposition and are pruned with it, so this file is delimited the same way
`stage_one.py` is. `feature:redis` encloses the cache dotted paths, the
`LocMemCache` subclass, the `CACHES` builder, the `redis` entry in
`FEATURE_CONDITIONS` and the whole of
`TestAnInProcessCacheBackendWhereRedisIsSelected`; `feature:celery` encloses the
`celery` entry and the whole of
`TestEagerTaskExecutionWhereBackgroundTasksAreSelected`. A paragraph naming those
functions was what stood here before, and a paragraph is not a removal mechanism:
a materializer reads markers, and seven cases in this file would have failed in a
combination that selected neither feature. Both regions are declared alongside
`stage_one.py`'s own in that module's docstring, which is the single declaration
site until Epic 7 authors `accelerator.toml`.

The imports those regions use are unmarked, for the reason `stage_one.py` records
about its own three: a marker pair inside the sorted import block does not survive
`ruff`'s isort, every one of them resolves in any combination because they are
Django's and this suite's, and what removing a region leaves behind is an unused
import rather than an `ImportError`. Pruning it is the materializer's general
orphan problem (Epic 8).

`TestTheFeatureRegionMarkers` and every helper above it carry no marker, and are
correct to keep in all six combinations -- including one that selected neither
feature, where they scan files that legitimately hold no region at all. That is
also why the naming assertion is a **subset** relation and not an equality: a
combination materialized for Redis alone carries one feature's markers, and
`FEATURE_CONDITIONS` shrinks in step with them, so equality would fail on a tree
that is correct. The subset still fails a marker naming a feature nothing here
declares, which is the thing worth catching.

**The runtime half of AC #3 is not asserted here, and cannot be.** AC #3 says
that in a combination whose feature is absent, neither condition is evaluated and
startup proceeds. AD-3 makes materialization subtractive, so that is satisfied
*by absence*: the condition and its roster entry are not in the file at all. That
is provable only against a materialized combination, and no materialized
combination exists yet -- the six pre-locked environments and `tools/materializer/`
are Epic 8's, and `pixi.toml` today declares `default`, `dev` and `spike-storage`.
So AC #3's runtime half is a **traceability marker in this module, not an
acceptance condition for this story**; what `TestTheFeatureRegionMarkers` asserts
is the mechanism that makes it true by construction, which is the half this story
delivers.

Every case drives the public `run_stage_one`, never a condition function
directly -- the rule `test_stage_one_conditions.py` states and the reason it
gives: a condition called by hand passes whether or not it was ever wired into
the roster, and the wiring is half of what this story adds.

Every case is deployed. `COMPONENT_RUNTIME` is deleted rather than set, because
locality fails closed (AD-13) and absent is the spelling a real deployment that
lost the variable would have; `OTEL_SDK_DISABLED` is deleted alongside it,
because condition 3 reads it from the environment and a developer's shell holding
it would refuse every case here for the wrong reason.
"""

from __future__ import annotations

import ast
import inspect
import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final
from typing import NoReturn

import pytest
from django.core.cache.backends.locmem import LocMemCache
from django.core.exceptions import AppRegistryNotReady
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_one
from config.startup import stage_one
from tests.conftest import valid_deployed_settings_namespace

# The AD-24 marker parser, promoted to `tests/feature_regions.py` when Story 5.7
# needed the same question answered about `src/config/settings/base.py` -- see
# that module's docstring for why a second private copy was not written. Bound
# back to the private names the cases below already use, deliberately: four of
# them assign a local `regions`, and importing the function under its own name
# would shadow it into an `UnboundLocalError`. Nothing about the parse changed in
# the move, and no assertion here changed with it.
from tests.feature_regions import marker_events as _marker_events
from tests.feature_regions import regions as _regions

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

#: The repository root, for turning an absolute source path into the repository-
#: relative spelling the region declarations use and back again.
REPO_ROOT: Final = Path(__file__).resolve().parents[3]


# feature:redis
LOCMEM_CACHE = "django.core.cache.backends.locmem.LocMemCache"
DUMMY_CACHE = "django.core.cache.backends.dummy.DummyCache"

# The backend `config/settings/production.py` hardcodes, and therefore the one a
# component that selected Redis is expected to be on. `django-redis` is an
# unscoped `[dependencies]` entry in pixi.toml, so this resolves in the `dev`
# environment and the negative case needs no import guard -- which
# `tests/unit/test_suite_policy.py` bans outright anyway.
REDIS_CACHE = "django_redis.cache.RedisCache"

# A cache alias name that is not `default`, so a refusal naming the wrong alias
# is a failing assertion rather than a coincidence.
SECOND_ALIAS = "sessions"


class ReExportedLocMemCache(LocMemCache):
    """A `LocMemCache` subclass under a dotted path of its own.

    The evasion condition 8 closes, and the reason it resolves the `BACKEND` with
    `import_string` and tests with `issubclass` rather than comparing strings: a
    component that wanted the in-process cache in a deployment needs only to
    subclass it and point `BACKEND` at the subclass. Declared at module scope
    rather than inside a test, because the whole point is that it has a real
    importable dotted path for the condition to resolve.
    """


#: This subclass's own dotted path, derived from the module rather than written
#: out -- a hand-spelled path would go stale the moment the file moved, and would
#: then make the case pass by being skipped as unimportable.
RE_EXPORTED_CACHE: Final = f"{__name__}.{ReExportedLocMemCache.__name__}"

#: A dotted path that resolves to nothing. `import_string` raises `ImportError`
#: for it, which condition 8 skips rather than converts into a refusal.
UNIMPORTABLE_CACHE = "not_a_distribution.cache.NoSuchBackend"

#: A dotted path that resolves to something that is not a class at all. Handing
#: it to `issubclass` raises `TypeError`, which is not `ImproperlyConfigured`.
NON_CLASS_CACHE = "django.utils.module_loading.import_string"

#: A dotted path whose resolution raises something that is *not* an `ImportError`.
#: The attribute does not exist; `__getattr__` below is what decides what reading
#: it does, which is how an arbitrary exception out of `import_string` is driven
#: without adding a module to the tree whose only purpose is to fail.
EXPLODING_BACKEND_ATTRIBUTE: Final = "ExplodingCacheBackend"
EXPLODING_CACHE: Final = f"{__name__}.{EXPLODING_BACKEND_ATTRIBUTE}"


def __getattr__(name: str) -> NoReturn:
    """Make one attribute of this module raise something other than `ImportError`.

    `import_string` runs third-party code twice over: it imports the module named
    by the dotted path, whose top level can raise anything at all, and then reads
    an attribute off it -- and a module that defines `__getattr__`, as this one
    does, decides for itself what reading an attribute does. Condition 8 has to
    survive both, which is why its guard is `Exception` rather than `ImportError`.

    `AppRegistryNotReady` is the realistic instance rather than an arbitrary one.
    Stage 1 runs while `apps.populate` is still going, so a `BACKEND` in a package
    that touches a model at import time raises exactly this -- the same obstacle
    `_MODEL_BACKEND` in `stage_one.py` is written around.

    Args:
        name: The attribute being read.

    Raises:
        AppRegistryNotReady: For `EXPLODING_BACKEND_ATTRIBUTE`.
        AttributeError: For every other name. An absent attribute has to keep
            looking absent: pytest reads `pytestmark` and other optional module
            attributes off this module during collection, and a `__getattr__` that
            raised something else for them would break collection rather than one
            test.

    """
    if name == EXPLODING_BACKEND_ATTRIBUTE:
        message = f"{EXPLODING_BACKEND_ATTRIBUTE} cannot be resolved: the app registry is not ready"
        raise AppRegistryNotReady(message)
    raise AttributeError(name)


# /feature:redis
@pytest.fixture(autouse=True)
def _deployed_and_traced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put every case in this module in a deployed component with tracing on."""
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)


@pytest.fixture
def namespace() -> ModuleType:
    """A deployed settings namespace no condition objects to, ready to be broken.

    It declares neither `CACHES` nor either eager flag, which is not an omission:
    `config/settings/base.py` declares neither either, so absence is a real
    deployed state both conditions have to accept rather than a hypothetical one.
    The shared factory is deliberately not extended with feature-scoped keys --
    that would put a `feature:` region in the fixture every core test depends on.
    """
    return valid_deployed_settings_namespace()


def _refusal(settings_module: ModuleType) -> str:
    """Run stage 1, insist that it refused, and return the message it refused with.

    Args:
        settings_module: The namespace to evaluate.

    Returns:
        The refusal message, for the caller to assert its distinguishing
        substring on. Substring assertions rather than `pytest.raises(match=...)`
        because the messages carry regex metacharacters -- `CACHES['default']`
        above all -- and escaping them at every call site reads as noise rather
        than as the claim being made.

    """
    with pytest.raises(ImproperlyConfigured) as refused:
        run_stage_one(settings_module)
    return str(refused.value)


# feature:redis
def _cached_by(dotted_path: str, alias: str = "default") -> dict[str, dict[str, str]]:
    """Build a `CACHES` mapping with one alias on one backend.

    Args:
        dotted_path: What to put in `BACKEND`.
        alias: The alias to put it under.

    Returns:
        A mapping shaped the way Django's `CACHES` is shaped.

    """
    return {alias: {"BACKEND": dotted_path}}


# /feature:redis
def _stage_one_path() -> Path:
    """Locate `stage_one.py` on disk by way of the module object rather than a path.

    Derived from the module under test so that moving the file moves this with
    it. A repository-relative literal would keep resolving from whatever the
    working directory happened to be and would fail for the wrong reason.

    Returns:
        The absolute path of the module's source file.

    Raises:
        RuntimeError: The module has no source file -- which would mean it had
            been imported from something other than the tree, and every marker
            assertion below would be reading the wrong thing.

    """
    source_path = inspect.getsourcefile(stage_one)
    if source_path is None:
        message = "config.startup.stage_one has no source file to scan for AD-24 markers"
        raise RuntimeError(message)
    return Path(source_path).resolve()


STAGE_ONE_PATH: Final = _stage_one_path()
STAGE_ONE_SOURCE: Final = STAGE_ONE_PATH.read_text(encoding="utf-8")
STAGE_ONE_LINES: Final = STAGE_ONE_SOURCE.splitlines()

#: The paths whose markers this module reconciles. Every one of them is a file
#: this story wrote markers into, and each is located through something that
#: moves with it rather than through a repository-relative literal.
#:
#: This is not a claim about the tree. The set of region-bearing paths is open --
#: `accelerator.toml` will declare it as an open array, and an earlier revision of
#: AD-24 named three paths and was wrong -- so nothing here asserts how large it
#: is. What it is, is the set these three modules can see and are therefore able
#: to keep honest; Epic 7's reconciler is what covers the rest.
MARKER_BEARING_PATHS: Final = (
    STAGE_ONE_PATH,
    Path(__file__).resolve(),
    Path(__file__).resolve().with_name("test_stage_one_conditions.py"),
    # Story 4.5's three. `forbidden_states.py` carries the `ForbiddenState`
    # record for each conditional state, `test_refusal_coverage_audit.py` carries
    # the expectations that read them, and `test_no_softening.py` carries each
    # conditional state's CG-3 builder and the broad-handler allowance recording
    # a guard that is itself inside a `feature:redis` region. All three shrink
    # with their features rather than demanding a test, a count or an allowance
    # for a condition a combination does not contain.
    Path(__file__).resolve().with_name("forbidden_states.py"),
    Path(__file__).resolve().with_name("test_refusal_coverage_audit.py"),
    Path(__file__).resolve().with_name("test_no_softening.py"),
)

#: Each of those files read once, at import, so that a case that scans one is a
#: comparison rather than a second read of the same bytes.
MARKER_BEARING_SOURCES: Final = {path: path.read_text(encoding="utf-8") for path in MARKER_BEARING_PATHS}

#: One region declaration in `stage_one.py`'s module docstring. Only the
#: structured opening of each bullet is matched -- the path and the feature, in
#: that order, each in backticks -- because everything after it is prose that
#: describes what the region contains and is expected to be rewritten. The
#: docstring's whitespace is collapsed before this runs, so a bullet rewrapped
#: across two lines still reconciles.
DECLARATION: Final = re.compile(r"path `(?P<path>[^`]+)`, feature `(?P<feature>[^`]+)`")

#: The condition each feature owns in `stage_one.py`, and the roster entry that
#: calls it. Both have to fall inside the feature's own region: the materializer
#: removes a region's lines, so a call site left outside the pair survives into a
#: combination whose definition has gone, which is a `NameError` at settings
#: import rather than a missing check.
#:
#: Each entry is itself marker-delimited, which is what makes the assertions
#: written over this mapping shrink in step with the tree they are asserted
#: against.
FEATURE_CONDITIONS: Final = {
    # One entry per feature this file knows about. The comment is load-bearing as
    # well as descriptive: a comment inside the braces holds the literal in its
    # expanded form, so a combination that selected neither feature is left with a
    # mapping `ruff format` accepts rather than one it wants rewritten as `{}`.
    # feature:redis
    "redis": "_refuse_in_process_cache",
    # /feature:redis
    # feature:celery
    "celery": "_refuse_eager_tasks",
    # /feature:celery
}


def _features_marked_in(source: str) -> set[str]:
    """Return every feature name any marker in one file mentions.

    Args:
        source: The file's text.

    Returns:
        The feature names, opening and closing markers alike -- a closing marker
        that names a feature nothing else does is exactly the misspelling worth
        finding.

    """
    return {feature for _, _, feature in _marker_events(source)}


def _declared_regions() -> set[tuple[str, str]]:
    """Read the region declarations out of `stage_one.py`'s module docstring.

    That docstring is the single declaration site until Epic 7 moves the
    declarations into `accelerator.toml` (AD-1). Read from `__doc__` rather than
    from the file's text so that what is reconciled is the declaration as the
    module actually carries it.

    Returns:
        One `(repository-relative path, feature)` pair per declaration bullet.

    Raises:
        RuntimeError: The module carries no docstring at all, which would make
            every declaration assertion below vacuously true.

    """
    docstring = stage_one.__doc__
    if not docstring:
        message = "config.startup.stage_one carries no docstring, so its AD-24 region declarations are gone"
        raise RuntimeError(message)
    collapsed = re.sub(r"\s+", " ", docstring)
    return {(match["path"], match["feature"]) for match in DECLARATION.finditer(collapsed)}


def _marked_regions() -> set[tuple[str, str]]:
    """Return every `(path, feature)` the markers on disk actually spell.

    Returns:
        One pair per feature named by a marker in each marker-bearing path, with
        the path spelled the way a declaration spells it.

    """
    return {
        (path.relative_to(REPO_ROOT).as_posix(), feature)
        for path, source in MARKER_BEARING_SOURCES.items()
        for feature in _features_marked_in(source)
    }


def _sole_line_matching(pattern: str) -> int:
    """Find the one line of `stage_one.py` matching a whole-line pattern.

    Args:
        pattern: A regular expression matched against each right-stripped line.

    Returns:
        The 1-indexed line number.

    Raises:
        AssertionError: No line matched, or more than one did. Either makes the
            enclosure assertion meaningless rather than merely wrong.

    """
    matched = [
        line_number for line_number, line in enumerate(STAGE_ONE_LINES, start=1) if re.fullmatch(pattern, line.rstrip())
    ]
    assert len(matched) == 1, f"expected exactly one line matching {pattern!r}, found {matched}"
    return matched[0]


def _outside_every_function(node: ast.AST) -> Iterator[ast.AST]:
    """Walk a tree without ever entering a function, class or lambda body.

    `ast.walk` reaches every node, and a condition's own `if not isinstance(...)`
    guards are `if` statements too, so a walk that entered function bodies would
    report them as feature gates. What AC #4 forbids is a branch at *module*
    scope, which decides whether the condition exists -- and module scope is not
    only `Module.body`: an `if` nested in a module-level `try`, `with`, `for` or
    `match` executes at import just the same and `tree.body` cannot see it.

    Args:
        node: The node to walk from.

    Yields:
        Every descendant reachable without crossing into a new scope.

    """
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            yield from _outside_every_function(child)


def _path_id(path: Path) -> str:
    """Name a parametrized case after the file it scans.

    Args:
        path: The file being scanned.

    Returns:
        The file's own name, which is what a failure needs to point at.

    """
    return path.name


# feature:redis
class TestAnInProcessCacheBackendWhereRedisIsSelected:
    """Condition 8, **feature `redis`** (AC #1).

    Pruned with the `feature:redis` regions in `src/config/startup/stage_one.py`
    and with the ones in this file.
    """

    def test_the_condition_and_its_roster_entry_are_both_inside_the_redis_region(self) -> None:
        """AC #4 for this half of the pair, on the two lines that have to move together.

        The definition and the call site are not adjacent, so the feature owns two
        marker pairs in `stage_one.py` rather than one. Asserting both is the
        point: a roster entry left outside its pair survives into a combination
        whose definition the materializer removed, which is a `NameError` at
        settings import -- a failure that path-level reconciliation cannot see.
        """
        name = FEATURE_CONDITIONS["redis"]
        regions = [region for region in _regions(STAGE_ONE_SOURCE) if region.feature == "redis"]
        definition = _sole_line_matching(rf"def {re.escape(name)}\(.*")
        call_site = _sole_line_matching(rf"\s+{re.escape(name)},")

        assert any(region.encloses(definition) for region in regions), f"{name}'s definition is outside the region"
        assert any(region.encloses(call_site) for region in regions), f"{name}'s roster entry is outside the region"

    @pytest.mark.forbidden_state("in-process-cache-backend")
    def test_the_in_process_cache_backend_refuses(self, namespace: ModuleType) -> None:
        """The state itself: `local.py:38-43`'s cache, reached in a deployment."""
        namespace.CACHES = _cached_by(LOCMEM_CACHE)

        message = _refusal(namespace)

        assert "CACHES['default']" in message
        assert LOCMEM_CACHE in message

    def test_the_dummy_cache_backend_refuses_too(self, namespace: ModuleType) -> None:
        """The same forbidden state in the spelling that does not look like it.

        A component that selected Redis and then configured the cache away
        entirely has a cache that stores nothing at all, which is worse than a
        per-worker one and reads as deliberate rather than as a fallback.
        """
        namespace.CACHES = _cached_by(DUMMY_CACHE)

        message = _refusal(namespace)

        assert DUMMY_CACHE in message

    def test_a_subclass_under_its_own_dotted_path_refuses(self, namespace: ModuleType) -> None:
        """The evasion the object resolution closes.

        Subclassing `LocMemCache` and pointing `BACKEND` at the subclass is the
        cheapest way to keep the in-process cache in a deployment, and a condition
        comparing dotted paths would report it as clean. `import_string` plus
        `issubclass` is what AD-26 calls for wherever objects can be resolved --
        and here they can, because a cache backend imports no model and stage 1
        runs before the app registry is ready.
        """
        namespace.CACHES = _cached_by(RE_EXPORTED_CACHE)

        message = _refusal(namespace)

        assert RE_EXPORTED_CACHE in message
        # The message names the forbidden ancestor as well as the configured path,
        # because the path alone does not tell a reader why it was refused.
        assert LocMemCache.__name__ in message

    def test_the_refusal_names_the_alias_and_says_which_feature_is_selected(
        self,
        namespace: ModuleType,
    ) -> None:
        """A refusal on a conditional condition has to say which half of the pair is wrong.

        The alias is what sends the reader to the line; naming the Redis feature
        is what tells them the alternative is to change the selection rather than
        the setting. Put on a second alias here because that is where this hides
        -- a `sessions` alias left on the in-process backend beside a Redis
        `default` passes any check that reads only `CACHES["default"]`.
        """
        namespace.CACHES = {
            "default": {"BACKEND": REDIS_CACHE, "LOCATION": "redis://redis:6379/0"},
            SECOND_ALIAS: {"BACKEND": LOCMEM_CACHE},
        }

        message = _refusal(namespace)

        assert f"CACHES[{SECOND_ALIAS!r}]" in message
        assert "Redis" in message
        assert "'default'" not in message, "the refusal named the wrong alias"

    def test_the_redis_cache_backend_is_accepted(self, namespace: ModuleType) -> None:
        """The backend `production.py:35-46` hardcodes, which is the whole point of the pair.

        The resolution is asserted before the acceptance, and that is what makes
        this a control rather than a coincidence. Condition 8 skips a `BACKEND` it
        cannot load, so were `django-redis` ever dropped from `[dependencies]`
        this case would go green for the exact reason that would make the
        condition blind -- passing while inspecting nothing. Asserting that the
        path resolves to a class first turns that into a failure naming the
        missing dependency.
        """
        assert isinstance(import_string(REDIS_CACHE), type), f"{REDIS_CACHE} no longer resolves to a class"

        namespace.CACHES = _cached_by(REDIS_CACHE)

        run_stage_one(namespace)

    def test_no_caches_at_all_is_accepted(self, namespace: ModuleType) -> None:
        """`config/settings/base.py` declares no `CACHES`, so absence is a real deployed state.

        It is also the state the shared `valid_deployed_settings_namespace` is in,
        and every module that builds a stage-1 case builds it on that factory: a
        condition that refused on absence would break all of them at once.
        """
        run_stage_one(namespace)

    @pytest.mark.parametrize(
        "configuration",
        [
            pytest.param("django_redis.cache.RedisCache", id="alias-is-not-a-mapping"),
            pytest.param({"LOCATION": "redis://redis:6379/0"}, id="mapping-with-no-backend"),
            pytest.param({"BACKEND": None}, id="backend-is-not-a-string"),
        ],
    )
    def test_an_alias_this_condition_cannot_read_is_skipped(
        self,
        namespace: ModuleType,
        configuration: object,
    ) -> None:
        """Skipped rather than refused, unlike condition 2's rosters -- and deliberately.

        The asymmetry is the point. Condition 2 refuses an unreadable
        `AUTHENTICATION_BACKENDS` because absence there *is* the forbidden state,
        so a value it cannot read hides one. Nothing hides here: Django's own
        `CacheHandler` raises `ImproperlyConfigured` for a malformed alias at the
        first cache access, and refusing it under this condition's message --
        which describes an in-process backend where Redis is selected -- would
        send the reader to the wrong line for a defect Django already owns.
        """
        namespace.CACHES = {"default": configuration}

        run_stage_one(namespace)

    def test_caches_that_is_not_a_mapping_at_all_is_skipped(self, namespace: ModuleType) -> None:
        """The outermost of the five skips, and the one nothing else reaches.

        A `CACHES` that is a list of alias mappings -- the shape someone reaches
        for after writing `DATABASES` from a template -- returns at the condition's
        first `isinstance` check. Django's `CacheHandler` refuses it at the first
        cache access with a message about the settings structure, which is the
        defect; this condition's message describes an in-process backend where
        Redis is selected, which it is not.
        """
        namespace.CACHES = [_cached_by(LOCMEM_CACHE)]

        run_stage_one(namespace)

    def test_a_backend_that_does_not_import_is_skipped_rather_than_refused(
        self,
        namespace: ModuleType,
    ) -> None:
        """The decision recorded as a test rather than left implicit.

        `import_string` raises `ImportError` for a dotted path that resolves to
        nothing. Converting that into a refusal would add a fifteenth forbidden
        state to a count the architecture settled at fourteen, under a message
        describing something the input is not. Django raises
        `InvalidCacheBackendError` -- itself an `ImproperlyConfigured` -- at the
        first cache access, so the defect is neither lost nor duplicated.
        """
        namespace.CACHES = _cached_by(UNIMPORTABLE_CACHE)

        run_stage_one(namespace)

    def test_a_backend_whose_resolution_raises_something_else_does_not_escape(
        self,
        namespace: ModuleType,
    ) -> None:
        """CG-3 over the one line in stage 1 that runs code this component did not write.

        `import_string` imports the module a settings value named. That module's
        top level can raise anything, and `AppRegistryNotReady` is the instance a
        Django package plausibly raises during stage 1, which runs inside
        `apps.populate`. A guard narrowed to `ImportError` lets it straight out of
        the settings import -- verified, not assumed -- and the module docstring
        and this condition's `Raises:` section both promise `ImproperlyConfigured`
        and nothing else comes out. So the alias is skipped, exactly as an
        unimportable one is: a backend that will not load is Django's defect, and
        it raises `InvalidCacheBackendError` for it at the first cache access.
        """
        namespace.CACHES = _cached_by(EXPLODING_CACHE)

        run_stage_one(namespace)

    def test_a_backend_that_resolves_to_something_that_is_not_a_class_is_skipped(
        self,
        namespace: ModuleType,
    ) -> None:
        """CG-3: the only exception out of a condition is `ImproperlyConfigured`.

        `issubclass` raises `TypeError` when its first argument is not a class,
        and a `BACKEND` naming a function is an ordinary typo. Without the guard
        that is a `TypeError` out of a settings import -- a boot failure reading
        as a defect in the refusal contract rather than as the misconfiguration
        it is.
        """
        namespace.CACHES = _cached_by(NON_CLASS_CACHE)

        run_stage_one(namespace)


# /feature:redis
# feature:celery
class TestEagerTaskExecutionWhereBackgroundTasksAreSelected:
    """Condition 9, **feature `celery`** (AC #2).

    Pruned with the `feature:celery` regions in `src/config/startup/stage_one.py`
    and with the one in this file.
    """

    def test_the_condition_and_its_roster_entry_are_both_inside_the_celery_region(self) -> None:
        """AC #4 for the other half of the pair, on the same two-lines-together rule."""
        name = FEATURE_CONDITIONS["celery"]
        regions = [region for region in _regions(STAGE_ONE_SOURCE) if region.feature == "celery"]
        definition = _sole_line_matching(rf"def {re.escape(name)}\(.*")
        call_site = _sole_line_matching(rf"\s+{re.escape(name)},")

        assert any(region.encloses(definition) for region in regions), f"{name}'s definition is outside the region"
        assert any(region.encloses(call_site) for region in regions), f"{name}'s roster entry is outside the region"

    @pytest.mark.forbidden_state("eager-task-execution")
    def test_eager_task_execution_refuses(self, namespace: ModuleType) -> None:
        """`local.py:103`'s flag, reached in a deployment.

        Eager execution runs the task in the web request that queued it, on that
        request's thread and inside its transaction -- so the component has the
        latency of doing the work synchronously and the operational cost of
        running workers that receive nothing.
        """
        namespace.CELERY_TASK_ALWAYS_EAGER = True

        message = _refusal(namespace)

        assert "CELERY_TASK_ALWAYS_EAGER" in message
        assert "background task processing" in message

    def test_a_truthy_value_that_is_not_true_refuses_too(self, namespace: ModuleType) -> None:
        """The truthiness rule, locked rather than only explained.

        The condition refuses on truthiness rather than on `is True`, and its
        `Raises:` section says why at length -- but until this case existed a
        later edit to `is True` passed the whole suite while admitting the
        forbidden state. The string `"false"` is the trap in its exact shape: it
        is what an environment-driven settings module produces from a variable
        nobody parsed, Celery reads it as on because Celery reads truthiness, and
        an identity test reads it as off. `DJANGO_ADMIN_FORCE_ALLAUTH` is the
        deliberate opposite, and `test_stage_one_conditions.py` locks that one.
        """
        namespace.CELERY_TASK_ALWAYS_EAGER = "false"

        message = _refusal(namespace)

        assert "CELERY_TASK_ALWAYS_EAGER" in message

    def test_no_eager_setting_at_all_is_accepted(self, namespace: ModuleType) -> None:
        """`config/settings/base.py` declares neither flag, so absence is the ordinary case."""
        run_stage_one(namespace)

    def test_eager_execution_switched_off_is_accepted(self, namespace: ModuleType) -> None:
        """Declared and false is not the forbidden state, and reads as deliberate.

        The refusal message has to agree with this case, which is the whole of why
        it does not tell a reader to leave the flag unset: `False` is accepted
        here, and guidance that contradicted an accepted state would send an
        operator to change a line that is already correct.
        """
        namespace.CELERY_TASK_ALWAYS_EAGER = False

        run_stage_one(namespace)

    def test_eager_propagation_on_its_own_is_accepted(self, namespace: ModuleType) -> None:
        """`CELERY_TASK_EAGER_PROPAGATES` is inert without the flag above it.

        `local.py:110` sets it beside `CELERY_TASK_ALWAYS_EAGER`, so it is the
        obvious second thing to refuse -- and refusing it would create a
        fifteenth forbidden state where the architecture settled on fourteen, and
        would reject a deployed component whose tasks are queued normally. It
        decides only whether an *eagerly executed* task re-raises; with nothing
        executing eagerly it decides nothing.
        """
        namespace.CELERY_TASK_EAGER_PROPAGATES = True

        run_stage_one(namespace)


# /feature:celery
class TestTheFeatureRegionMarkers:
    """AC #4: the regions are delimited, balanced, and are the only mechanism (AD-24).

    A local stand-in for the two-way reconciliation Epic 7 delivers against
    `accelerator.toml`. It cannot be the real thing -- there is no carrier to
    reconcile against yet, and this story is forbidden from writing one (AD-1) --
    but it is enough that a marker cannot be silently dropped in the interval.

    Every assertion here is written over whatever regions each file actually
    carries, so all of them hold in a combination with one feature, both, or
    neither. Nothing here asserts how many region-bearing paths the tree has: the
    set is open, the carrier declares it as an open array, and an earlier revision
    of AD-24 named three paths and was wrong.

    **It sits last in the file deliberately.** A file whose final construct is a
    feature region is left with two trailing blank lines once that region is
    removed, and `ruff format` deletes those -- so a materialized combination
    would fail its own format check on a file nobody had touched. A feature-neutral
    construct at the end is what absorbs the separation.
    """

    @pytest.mark.parametrize("path", MARKER_BEARING_PATHS, ids=_path_id)
    def test_every_marker_pair_is_balanced_and_never_nested(self, path: Path) -> None:
        """An unbalanced pair fails reconciliation (AD-24), so it fails here first.

        Nesting the same feature is checked as well as imbalance, because the two
        produce the same symptom from a line-based stripper: an opening marker
        with no closer of its own removes everything to the end of the file, and a
        closer with no opener removes nothing and leaves the marker behind.
        """
        depth: dict[str, int] = {}
        for line_number, closing, feature in _marker_events(MARKER_BEARING_SOURCES[path]):
            if closing:
                assert depth.get(feature, 0) == 1, (
                    f"{path.name} line {line_number} closes feature:{feature}, which is not open"
                )
                depth[feature] = 0
            else:
                assert depth.get(feature, 0) == 0, (
                    f"{path.name} line {line_number} opens feature:{feature} inside another feature:{feature} region"
                )
                depth[feature] = 1

        assert [feature for feature, count in depth.items() if count != 0] == []

    @pytest.mark.parametrize("path", MARKER_BEARING_PATHS, ids=_path_id)
    def test_no_two_regions_interleave(self, path: Path) -> None:
        """Two features' regions may nest or sit side by side, but must not cross.

        The balance assertion above keys its depth per feature, so
        `feature:redis` … `feature:celery` … `/feature:redis` … `/feature:celery`
        satisfies it -- and that arrangement is broken, not merely untidy. A
        line-based stripper removing the redis region deletes every line from
        `feature:redis` to `/feature:redis`, which takes celery's *opening* marker
        with it and leaves `/feature:celery` behind as an orphan. Whichever
        combination that is, it is not the one that was asked for.
        """
        open_features: list[str] = []
        for line_number, closing, feature in _marker_events(MARKER_BEARING_SOURCES[path]):
            if not closing:
                open_features.append(feature)
                continue
            assert open_features, f"{path.name} line {line_number} closes feature:{feature} with no region open"
            assert open_features[-1] == feature, (
                f"{path.name} line {line_number} closes feature:{feature} while "
                f"feature:{open_features[-1]} is the innermost open region"
            )
            open_features.pop()

        assert open_features == []

    @pytest.mark.parametrize("path", MARKER_BEARING_PATHS, ids=_path_id)
    def test_the_markers_name_only_features_this_module_knows(self, path: Path) -> None:
        """A marker naming an undeclared feature fails reconciliation (AD-24).

        A **subset** relation, not an equality, and the difference is the whole
        point of the assertion. `FEATURE_CONDITIONS` names both features because
        this tree carries both; a combination materialized for Redis alone carries
        one feature's markers and a `FEATURE_CONDITIONS` with one entry, and a
        combination with neither carries no markers at all. Equality would fail
        every one of those correct trees. The subset still fails the case worth
        catching: a marker spelling `feature:reids`, or naming a feature nothing
        here declares.
        """
        named = _features_marked_in(MARKER_BEARING_SOURCES[path])

        assert named <= set(FEATURE_CONDITIONS), f"{path.name} names a feature this module does not know: {named}"

    def test_the_declarations_and_the_markers_agree_in_both_directions(self) -> None:
        """AD-24's reconciliation rule, in the two directions it names.

        "A marker naming an undeclared feature fails; a declared region whose
        markers are absent from the named file fails." Until Epic 7 authors
        `accelerator.toml` the declaration is the bullet list in `stage_one.py`'s
        module docstring, and until this case existed nothing read it: the
        enclosure assertions compared against `FEATURE_CONDITIONS`, so the
        declaration block could lose a bullet, gain a path that carries no marker,
        or contradict the markers outright without anything failing.

        The second direction is asked only of features this module still knows
        about. The declaration bullets are prose in a docstring and no marker
        encloses them, so they survive materialization intact while the regions
        they describe do not -- and requiring markers for a feature the tree no
        longer has would fail every materialized combination. `FEATURE_CONDITIONS`
        is the linkage that makes that safe: its entries *are* marker-delimited, so
        it names exactly the features this tree still contains.
        """
        declared = _declared_regions()
        marked = _marked_regions()

        undeclared = marked - declared
        assert undeclared == set(), f"markers with no declaration in stage_one.py's docstring: {sorted(undeclared)}"

        unmarked = {(path, feature) for path, feature in declared if feature in FEATURE_CONDITIONS} - marked
        assert unmarked == set(), f"declared regions whose markers are absent from the named file: {sorted(unmarked)}"

    def test_no_region_contains_an_import(self) -> None:
        """AD-24 permits no conditional import and no `try`/`except ImportError` probe.

        An import inside a region is what both of those look like, so this is the
        mechanical form of the rule. It does not touch the exception guard
        condition 8 already has: that guards a dotted path the *settings module*
        supplied, resolves nothing about which features are present, and imports
        nothing itself.
        """
        regions = _regions(STAGE_ONE_SOURCE)
        imports = [
            node.lineno
            for node in ast.walk(ast.parse(STAGE_ONE_SOURCE))
            if isinstance(node, ast.Import | ast.ImportFrom) and any(region.encloses(node.lineno) for region in regions)
        ]

        assert imports == [], f"an import inside a feature region is a second removal mechanism: lines {imports}"

    def test_no_region_is_gated_by_a_module_level_branch(self) -> None:
        """AC #4 in its own words: "they are not unconditional code guarded by a runtime flag".

        A module-level `if` is the shape every forbidden alternative takes -- a
        settings flag, an environment variable, `if "django_redis" in
        INSTALLED_APPS`. The conditions' own internal `if`s are function-body
        statements and are not in scope here; what is forbidden is a branch that
        decides whether the condition exists. Every module-scope statement is
        walked, not only `Module.body`, because a gate inside a module-level
        `try`, `with`, `for` or `match` runs at import exactly the same.
        """
        regions = _regions(STAGE_ONE_SOURCE)
        gates = [
            node.lineno
            for node in _outside_every_function(ast.parse(STAGE_ONE_SOURCE))
            if isinstance(node, ast.If) and any(region.encloses(node.lineno) for region in regions)
        ]

        assert gates == [], f"a module-level branch inside a feature region gates it on a flag: lines {gates}"

    def test_the_roster_itself_carries_no_conditional_entry(self) -> None:
        """The other place a runtime flag would hide: a conditional expression in the tuple.

        `_STAGE_ONE` is the one call site every condition is reached through, so
        `_refuse_in_process_cache if REDIS else _noop` there would satisfy the
        function-definition half of AC #4 and defeat the whole of it.
        """
        roster = next(
            (
                node
                for node in ast.parse(STAGE_ONE_SOURCE).body
                if isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "_STAGE_ONE"
            ),
            None,
        )

        assert roster is not None, "stage_one.py declares no annotated _STAGE_ONE roster to inspect"
        assert [type(node).__name__ for node in ast.walk(roster) if isinstance(node, ast.IfExp)] == []

    def test_the_ruff_table_the_markers_depend_on_is_pinned(self) -> None:
        """The markers are lint-legal only because `[tool.ruff]` says so.

        `# feature:redis` is `ERA001 Found commented-out code` to ruff unless
        `feature` is a declared task tag -- the closing `# /feature:redis` escapes
        on its leading slash, the opening one does not. The tag is therefore not
        cosmetic: without it every opening marker in the tree is a lint failure and
        `pixi run ci` does not pass, which is why it is asserted here rather than
        left to whoever next tidies a configuration table.

        Both halves matter. `lint.task-tags` *replaces* ruff's default rather than
        extending it, so the three defaults are asserted alongside `feature`: a
        list that dropped them would switch TODO, FIXME and XXX handling off
        tree-wide with nothing to notice. And `ERA` is asserted still selected,
        because a select list that lost it would leave the tag declared and
        pointless while quietly licensing the commented-out code the group exists
        to find.
        """
        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            ruff = tomllib.load(handle)["tool"]["ruff"]

        assert set(ruff["lint"]["task-tags"]) >= {"TODO", "FIXME", "XXX", "feature"}
        assert "ERA" in ruff["lint"]["select"]
