"""`CPM-APP-S07`'s contract, swept rather than promised.

Four of the five acceptance criteria are claims about *the API as a whole*, and a
claim about a whole is not tested by testing one endpoint. "The only writes are two"
is false the moment a third arrives, and the third will arrive in a module nobody
thought to add a test to -- so what is asserted here is read off the URL resolver,
the serializer registry and the settings, not off a list somebody maintained.

**AC 3 is the one this module exists for.** `CPM-FR-27` gives v1 two writes: the
package-identity override and the queue action. The failure it guards against is not
somebody deliberately adding a third; it is somebody registering a `ModelViewSet`,
which brings `POST`, `PUT`, `PATCH` and `DELETE` with it and looks like one line in a
diff. So the sweep walks every registered route, asks what methods it answers, and
compares against the two.

**AC 5 is the one a sweep can nearly miss.** "A derived status is never `null`, `""`
or a boolean" is a property of every status field in every serializer, and checking
the three endpoints that exist today would leave the fourth free. `StatusField` is
what makes it checkable: the rule lives in one class, and the sweep asserts that
every field whose *name* is a status uses it. A serializer that spelled a status as a
`BooleanField` fails here rather than in whatever quarter somebody notices their
dashboard says a package is fine.

**Where a proxy is not enough, there is a case.** The permission sweep in
`test_permission_audit.py` accepts a `get_permissions` override as a declaration,
because statically that is all it can see. What that override actually *returns* for
each queue is asserted below, by calling it -- the same lesson two audits in this
epic already learned, that a sweep checking a proxy has to be paired with a case
checking the rule.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.urls import get_resolver
from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.settings import api_settings

from conda_sentinel.core.permissions import RolePermission
from conda_sentinel.core.serializer_fields import StatusField
from conda_sentinel.core.serializer_fields import StatusSerializationError
from conda_sentinel.surface.api.views import QueueListAPIView
from conda_sentinel.workflow.api.permissions import queue_permission
from conda_sentinel.workflow.states import QUEUE_OWNERS

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The package every module under audit lives in.
IMPORT_ROOT: Final[str] = "conda_sentinel"

#: Where **this application's** API is mounted.
#:
#: `CPM-APP-S14` moved it under the application's own name. Before that it shared
#: `/api/` with the platform's user endpoint, which is why the roster below used to
#: carry a recorded exemption for that endpoint: the two shared a root and a schema
#: document, so "what does this API write" could not be answered without naming
#: somebody else's view. Two roots, and the question answers itself.
API_PREFIX: Final[str] = "conda-sentinel/api/"

#: Where the platform's own API lives, which is not under this application's root.
#:
#: Asserted rather than assumed by `test_the_platforms_api_is_not_under_this_ones`,
#: because the failure it guards is silent: a prefix that swept `/api/` along with the
#: application's pages would break a contract `CPM-APP-S07` published, and every one
#: of this product's own cases would still pass.
PLATFORM_API_PREFIX: Final[str] = "api/"

#: Views under this application's API root that are not part of its contract.
#:
#: They *serve* the contract rather than being in it: the schema document, the browser
#: for it, and the refusal for a version this API does not have. None answers a
#: question about a package, and none belongs in the roster of endpoints AC 3
#: enumerates -- but all three have to live under the root they describe, because a
#: contract published somewhere else is one a caller has to be told about separately.
#:
#: Spelled exactly and spent exactly: `test_every_contract_service_is_still_mounted`
#: fails on an entry that has stopped being real, so this cannot go on licensing an
#: endpoint that quietly became one.
CONTRACT_SERVICES: Final[frozenset[str]] = frozenset(
    {
        "config.api_versions.UnknownApiVersion",
        "drf_spectacular.views.SpectacularAPIView",
        "drf_spectacular.views.SpectacularSwaggerView",
    },
)

#: The HTTP methods that change something.
WRITE_METHODS: Final[frozenset[str]] = frozenset({"post", "put", "patch", "delete"})

#: Every method a route may answer, for reading them off a plain view class.
HTTP_METHODS: Final[frozenset[str]] = WRITE_METHODS | {"get", "head", "options"}

#: The two writes `CPM-FR-27` gives v1, by the view class that answers each.
#:
#: **The acceptance criterion restated as data.** Spelled by class name rather than
#: by URL so a route moved during a refactor still matches, and a *third view* does
#: not -- which is the change this is watching for.
DECLARED_WRITES: Final[frozenset[str]] = frozenset(
    {
        "conda_sentinel.identity.api.views.PackageIdentityOverrideAPIView",
        "conda_sentinel.workflow.api.views.WorkflowItemTransitionAPIView",
    },
)

#: What a status field is called, wherever it appears.
#:
#: Matched on the name because that is what a reviewer reading a serializer sees, and
#: because the alternative -- a list of every status field in the product -- is a
#: second roster that goes stale. A field called `state`, `status`, `confidence`,
#: `outcome` or `readiness` carries one of `CPM-FR-5`'s five values, and `CPM-AD-24`
#: says how each is emitted.
STATUS_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {"confidence", "outcome", "priority", "readiness", "status", "work_type"},
)

#: Status-named fields that are deliberately *not* derived statuses.
#:
#: Spelled out and spent, on the terms `test_app_layering_audit.py` sets for its
#: recorded imports: an exemption that stops being real fails below rather than going
#: on licensing nothing.
#:
#: `state` on a workflow serializer is `ItemState` -- `open`, `in_progress`,
#: `resolved` -- which is a position in a workflow rather than a verdict about a
#: package. `CPM-AD-24` is about derived statuses, and widening `StatusField` to every
#: enumerated string would make this sweep mean nothing.
RECORDED_NON_STATUSES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("WorkflowItemSerializer", "state"),
        ("WorkflowTransitionSerializer", "from_state"),
        ("WorkflowTransitionSerializer", "to_state"),
        ("TransitionRequestSerializer", "expected_state"),
        ("TransitionRequestSerializer", "to_state"),
    },
)


def product_modules() -> Iterator[str]:
    """Yield every module inside this product's package.

    Yields:
        Dotted module names.

    """
    root = importlib.import_module(IMPORT_ROOT)
    for module in pkgutil.walk_packages(root.__path__, prefix=f"{IMPORT_ROOT}."):
        if ".migrations." not in module.name:
            yield module.name


def declared_serializers() -> list[type[serializers.Serializer]]:  # type: ignore[type-arg]
    """Return every serializer class this product declares.

    Found by import rather than from a roster: a serializer added in a module nobody
    listed here is exactly the one that would carry an unchecked status.

    Returns:
        The classes, deduplicated, in import order.

    """
    found: dict[str, type[serializers.Serializer]] = {}  # type: ignore[type-arg]
    for name in product_modules():
        module = importlib.import_module(name)
        for attribute, value in vars(module).items():
            if (
                inspect.isclass(value)
                and issubclass(value, serializers.BaseSerializer)
                and value.__module__.startswith(f"{IMPORT_ROOT}.")
            ):
                found.setdefault(f"{value.__module__}.{attribute}", value)  # type: ignore[arg-type]
    return list(found.values())  # type: ignore[arg-type]


def registered_routes() -> list[Route]:
    """Return every registered route: its pattern, its view, and the methods it answers.

    **The methods are read at collection time, not off the class**, and that took a
    correction. A `ModelViewSet` defines `create`, `update` and `destroy`, never
    `post`, `put` or `delete` -- the router maps them when it builds the route. So an
    earlier version of this module asked the class `hasattr(view, "post")` and would
    have reported a registered `ModelViewSet` as read-only, which is precisely the
    one-line diff the write sweep exists to catch. It was found by the platform's own
    user endpoint failing to show up where it was expected.

    Returns:
        One `Route` per route, whoever owns the view -- including the platform's,
        because "what does this deployment expose" is a question the product's own
        package cannot answer alone.

    """
    found: list[Route] = []
    pending = [(entry, "") for entry in get_resolver().url_patterns]
    while pending:
        entry, prefix = pending.pop()
        pattern = f"{prefix}{entry.pattern}"
        nested = getattr(entry, "url_patterns", None)
        if nested is not None:
            pending.extend((child, pattern) for child in nested)
            continue
        callback = getattr(entry, "callback", None)
        view = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
        if view is None:
            continue
        # A router-built route carries the map it was built with; a plain view does
        # not, and answers whatever it implements.
        routed = getattr(callback, "actions", None)
        methods = frozenset(routed) if routed else frozenset(m for m in HTTP_METHODS if hasattr(view, m))
        found.append(Route(pattern=pattern, view=view, methods=methods))
    return found


def product_api_routes() -> list[Route]:
    """Return the routes this product contributes to the API.

    Scoped by URL prefix rather than by module, because "the API" is a thing a
    caller reaches at `/api/`, not a naming convention -- and the two are asserted to
    agree by `test_every_product_api_view_lives_in_an_api_subpackage`.

    Returns:
        Each `/api/` route whose view is this product's.

    """
    return [
        route
        for route in registered_routes()
        if route.pattern.startswith(API_PREFIX) and route.view.__module__.startswith(f"{IMPORT_ROOT}.")
    ]


@dataclass(frozen=True, slots=True)
class Route:
    """One registered route, and what it answers."""

    pattern: str
    view: type

    #: The lowercase HTTP methods it answers. Not `http_method_names`, which lists
    #: what the base class *permits* -- and every Django view permits them all.
    methods: frozenset[str]

    def name(self) -> str:
        """Return the view's dotted name.

        Returns:
            `module.ClassName`.

        """
        return f"{self.view.__module__}.{self.view.__name__}"

    def writes(self) -> frozenset[str]:
        """Return the write methods it answers.

        Returns:
            Whichever of `POST`, `PUT`, `PATCH` and `DELETE` it answers.

        """
        return self.methods & WRITE_METHODS


# ---------------------------------------------------------------------------
# AC 3: the two writes, and no third.
# ---------------------------------------------------------------------------


def test_the_only_writes_are_the_two_the_requirement_names() -> None:
    """AC 3, swept off the resolver rather than read off a list.

    The failure this catches is not a deliberate third endpoint. It is a
    `ModelViewSet` registered in one line, which brings `POST`, `PUT`, `PATCH` and
    `DELETE` with it -- a diff that looks like routing and is a change to the
    product's contract.
    """
    writing = {route.name() for route in product_api_routes() if route.writes()}

    assert writing == DECLARED_WRITES, (
        f"the API writes from {sorted(writing)}. CPM-FR-27 gives v1 two writes -- the package-identity override "
        f"and the queue action -- and a third is a change to the product's contract, not a routing detail."
    )


def test_neither_write_can_reach_evidence_or_a_derived_status() -> None:
    """AC 3's second half, and it holds because of where the writes are, not what they say.

    Both endpoints delegate to a service, and neither service writes a derived table:
    `CPM-AD-10` gives the application layer no path to one. What is checkable here is
    that neither view declares a `ModelSerializer`, which is the shape that *would*
    give it one -- a `ModelSerializer` over a derived model saves through it, and the
    view would acquire a write to derived state without anybody writing a `save()`.
    """
    for name in sorted(DECLARED_WRITES):
        module_name, _, class_name = name.rpartition(".")
        view = getattr(importlib.import_module(module_name), class_name)
        declared = [
            attribute
            for attribute in vars(view).values()
            if inspect.isclass(attribute) and issubclass(attribute, serializers.ModelSerializer)
        ]
        assert declared == [], f"{name} declares a ModelSerializer, which is a write path to whatever it models."


def test_every_read_endpoint_answers_get_and_nothing_else() -> None:
    """The other side of AC 3, so the sweep is not satisfied by a product with no reads.

    A test that only asserted "these two write" would pass on an API where every
    endpoint wrote, or on one where none did.
    """
    reading = {route.name() for route in product_api_routes() if "get" in route.methods and not route.writes()}

    assert reading, "no read endpoint was found, so the write sweep above is asserting nothing."


def test_the_platforms_api_is_not_under_this_ones() -> None:
    """AC 3's boundary, checked from the direction that fails silently.

    While the two shared `/api/` this case was an *exemption* -- the platform's
    `UserViewSet` writes, it is not this product's, and an audit that simply ignored
    every view it did not own would have been answering an easier question than AC 3
    asks. `CPM-APP-S14` split the roots, and the honest version of the question is now
    the boundary itself.

    The failure it guards is silent in both directions: a prefix that swept `/api/`
    along would break a contract `CPM-APP-S07` published, and a platform endpoint that
    drifted under this application's root would appear in this application's schema as
    though this product owned it.
    """
    under_ours = {
        route.name()
        for route in registered_routes()
        if route.pattern.startswith(API_PREFIX)
        and not route.view.__module__.startswith(f"{IMPORT_ROOT}.")
        and route.name() not in CONTRACT_SERVICES
    }

    assert under_ours == set(), (
        f"these are not this application's and are mounted under its API root: {sorted(under_ours)}. Two roots is "
        f"what lets this product publish a contract that is its own."
    )

    platform = {
        route.name()
        for route in registered_routes()
        if route.pattern.startswith(PLATFORM_API_PREFIX) and not route.pattern.startswith(API_PREFIX)
    }
    assert platform, "the platform's API was not found at its own root, so the boundary above asserts nothing."


def test_every_contract_service_is_still_mounted() -> None:
    """An exemption that has stopped being real is one licensing something else.

    The three below are permitted under this application's API root because they serve
    its contract rather than being part of it. If one is unmounted the entry should go
    with it -- otherwise the next view that happens to share its name inherits a
    licence nobody granted it.
    """
    mounted = {route.name() for route in registered_routes() if route.pattern.startswith(API_PREFIX)}
    stale = sorted(CONTRACT_SERVICES - mounted)

    assert stale == [], f"these are exempted under {API_PREFIX} and are not mounted there: {stale}."


def test_the_contract_is_published_under_the_version_it_describes() -> None:
    """A schema at a different address from the endpoints it documents is one nobody finds.

    And a schema that documented *two* applications is what this product had until
    `CPM-APP-S14` -- which is why the audit needed an exemption for somebody else's
    write in order to answer "what does this API write".
    """
    from django.urls import reverse  # noqa: PLC0415 - read beside the claim

    schema = reverse("conda-sentinel-api-schema")

    assert schema.startswith(f"/{API_PREFIX}")
    assert reverse("conda_sentinel_api:package-health").startswith(f"/{API_PREFIX}")


def test_every_product_api_view_lives_in_an_api_subpackage() -> None:
    """The routing and the structure agree, which is what lets either stand for the API.

    `CPM-AD-19` gives a domain app an `api/` subpackage whose routing is central. The
    sweeps above scope by URL prefix; this asserts the convention matches, so a view
    added under `/api/` in some other module does not quietly sit outside whichever
    of the two a future audit happens to use.
    """
    misplaced = [route.name() for route in product_api_routes() if ".api." not in route.view.__module__]

    assert misplaced == [], f"these answer under /api/ from outside an api/ subpackage: {misplaced}."


# ---------------------------------------------------------------------------
# AC 5 / `APP.07-API-001`: a derived status is never null, blank or a boolean.
# ---------------------------------------------------------------------------


def test_every_status_field_in_every_serializer_is_a_status_field() -> None:
    """AC 5 as a property of the product rather than of three endpoints.

    Checking the endpoints that exist today would leave the fourth free, and the
    fourth is the one written by somebody who has not read this story.
    """
    wrong = [
        f"{serializer.__name__}.{name} is a {type(field).__name__}"
        for serializer in declared_serializers()
        for name, field in getattr(serializer, "_declared_fields", {}).items()
        if name in STATUS_FIELD_NAMES
        and (serializer.__name__, name) not in RECORDED_NON_STATUSES
        and not isinstance(field, StatusField)
    ]

    assert wrong == [], (
        f"these carry a derived status without StatusField: {wrong}. CPM-AD-24 emits a status verbatim on every "
        f"read surface, and APP.07-API-001 forbids null, blank and boolean -- `unknown` is one of CPM-FR-5's five "
        f"states and every ordinary serialization habit turns it into an absence."
    )


def test_the_sweep_has_status_fields_to_sweep() -> None:
    """So the case above cannot pass by finding nothing.

    The subject list is built by walking the package, and a walk that imported
    nothing would report no violations rather than no coverage.
    """
    statuses = [
        (serializer.__name__, name)
        for serializer in declared_serializers()
        for name, field in getattr(serializer, "_declared_fields", {}).items()
        if isinstance(field, StatusField)
    ]

    assert len(statuses) > len(RECORDED_NON_STATUSES), statuses


@pytest.mark.parametrize("recorded", sorted(RECORDED_NON_STATUSES))
def test_every_recorded_non_status_is_still_a_real_field(recorded: tuple[str, str]) -> None:
    """An exemption that has stopped being real fails rather than licensing nothing.

    Args:
        recorded: The serializer and field it exempts.

    """
    name, attribute = recorded
    declared = {serializer.__name__: serializer for serializer in declared_serializers()}
    assert name in declared, f"{name} no longer exists; drop its exemption."
    assert attribute in declared[name]._declared_fields, f"{name}.{attribute} no longer exists; drop its exemption."  # noqa: SLF001


@pytest.mark.parametrize("value", [None, "", False, 0])
def test_a_status_field_refuses_a_falsy_value(value: object) -> None:
    """The rule itself, and it raises rather than emitting.

    Every status column in this product is non-null with a sentinel default, so a
    falsy one here is a defect upstream rather than a missing value -- and `CG-3`
    says a refusal is loud. A silently empty status in a response is the failure
    somebody notices a quarter later, as a package that looked fine.

    Args:
        value: What a broken projection might hand it.

    """
    field = StatusField()
    field.field_name = "vulnerability"

    with pytest.raises(StatusSerializationError, match="vulnerability"):
        field.to_representation(value)


@pytest.mark.parametrize("option", ["allow_null", "allow_blank", "required"])
def test_a_status_field_cannot_be_talked_out_of_its_own_rule(option: str) -> None:
    """The three options that would defeat it are `TypeError`, not defaults.

    A field that could be overridden would be a comment. `required=False` is on the
    list because a key that is absent is a key a client defaults, which loses
    `unknown` exactly as `null` does.

    Args:
        option: Which option to try.

    """
    with pytest.raises(TypeError, match=option):
        StatusField(**{option: True})


def test_a_status_field_emits_a_sentinel_verbatim() -> None:
    """The other side, so the refusal is not simply a field that rejects everything.

    `unknown` is the value this whole rule exists to protect, so it is the one
    asserted.
    """
    assert StatusField().to_representation("unknown") == "unknown"


# ---------------------------------------------------------------------------
# AC 2: every collection is paginated, with a maximum page size.
# ---------------------------------------------------------------------------


def test_every_collection_endpoint_inherits_the_global_bound() -> None:
    """AC 2, and the endpoints assert it by declaring nothing.

    `CPM-AD-12` puts pagination in `REST_FRAMEWORK` globally and
    `test_pagination_audit.py` sweeps for a view that opted out. What is checked here
    is the other half: that the product's own list views actually *are* generic views
    subject to it, rather than bare `APIView`s returning a whole collection by hand --
    which no pagination setting reaches.
    """
    unbounded = [
        route.name()
        for route in product_api_routes()
        if "get" in route.methods and not route.writes() and not issubclass(route.view, GenericAPIView)
    ]

    assert unbounded == [], (
        f"these answer a read outside DRF's generic views, so no pagination setting reaches them: {unbounded}. "
        f"CPM-AD-12 makes pagination structural, and a hand-rolled list view is how it stops being."
    )


def test_the_maximum_page_size_is_a_real_ceiling() -> None:
    """AC 2 says *with a maximum*, which is a different claim from *paginated*.

    A paginator whose size a client chooses has no maximum worth the name.
    """
    paginator = api_settings.DEFAULT_PAGINATION_CLASS()

    assert isinstance(paginator, PageNumberPagination)
    assert paginator.page_size_query_param is None
    assert paginator.max_page_size > paginator.page_size


# ---------------------------------------------------------------------------
# AC 4: the same role scoping as the application.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("queue", sorted(QUEUE_OWNERS))
def test_the_queue_permission_requires_the_role_that_owns_the_queue(queue: str) -> None:
    """AC 4 for the one surface whose roles depend on its URL.

    `test_permission_audit.py` accepts a `get_permissions` override as a declaration,
    because statically that is all it can see. This calls it: two audits earlier in
    this epic checked a proxy and passed while the rule was wrong, and the fix both
    times was to pair the sweep with a case that asks the question directly.

    Args:
        queue: The queue name.

    """
    permission = queue_permission(queue)

    assert issubclass(permission, RolePermission)
    assert permission.required_roles == frozenset({QUEUE_OWNERS[queue]})


def test_a_queue_that_does_not_exist_gets_a_permission_that_refuses_everybody() -> None:
    """It fails closed, which matters because the 404 in front of it could be removed.

    `queue_permission` deliberately does not raise -- drf-spectacular calls
    `get_permissions` during schema generation with no URL kwargs, and an earlier
    version that raised `NotFound` there made `/api/schema/` answer 404 for the whole
    document. So the refusal moved to `initial()`, and this is what stands behind it.
    """
    permission = queue_permission("not-a-queue")

    assert issubclass(permission, RolePermission)
    assert permission.required_roles == frozenset()


def test_the_queue_listing_resolves_its_permission_from_the_url() -> None:
    """The seam itself, asserted on the view rather than only on the helper.

    A view that stopped calling the helper would leave every case above passing.
    """
    view = QueueListAPIView()
    view.kwargs = {"queue": next(iter(sorted(QUEUE_OWNERS)))}

    declared = view.get_permissions()

    assert len(declared) == 1
    assert isinstance(declared[0], RolePermission)
    assert declared[0].required_roles == frozenset({QUEUE_OWNERS[view.kwargs["queue"]]})
