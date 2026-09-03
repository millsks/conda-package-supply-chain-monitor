"""Eight forbidden states, refused at settings import (AC #1-#5, FR-16).

One test per forbidden state, each asserting the exception *type* and a
distinguishing substring of its message -- the setting or the environment
variable -- so that no two conditions can pass each other's test. This module
covers the eight unconditional stage-1 states and nothing else; the two
feature-scoped ones are `test_feature_scoped_refusals.py`, and the stage-2 ones
are split -- `test_stage_two_urlconf.py` holds the two URLconf states, and
`tests/integration/startup/test_stage_two_database_conditions.py` holds the ones
that need a real connection, the designated group and the migration state. Story
4.5 audits that every state is covered somewhere. No total is asserted here on
purpose -- a count maintained in a module docstring goes stale without anything
failing.

Every case drives the public `run_stage_one`, never a condition function
directly. What is under test is the refusal a deployed component actually meets,
and a condition called by hand would pass whether or not it was ever wired into
the roster.

Every case is deployed. `COMPONENT_RUNTIME` is deleted rather than set to a
deployed value, because locality fails closed (AD-13) and absent is the spelling
a real deployment that lost the variable would have. `OTEL_SDK_DISABLED` is
deleted alongside it: it is the one input stage 1 reads from the environment
rather than from the namespace, so a developer's shell holding it would refuse
every case in this module for the wrong reason.

Each case starts from the fully valid namespace in `tests/conftest.py` and
breaks exactly one thing. That is what makes the assertions specific: the
positive case below proves the namespace passes, so a refusal in any other case
is the one state that case constructed.

**Not an integration test.** Stage 1 opens no socket, issues no query and reads
no file. The socket half is asserted here for condition 4, which is the only one
that handles a URL and therefore the only one anything could mistake for a fetch;
the query half is asserted for the whole stage by
`tests/unit/startup/test_no_network_no_queries.py` and
`tests/integration/startup/test_no_queries.py`, and is not duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from django.conf import global_settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from config.authorization.claims import CLAIMS_ENVIRONMENT_VARIABLES
from config.authorization.claims import ClaimsContract
from config.locality import RUNTIME_ENV_VAR
from config.observability.telemetry import OTEL_SDK_DISABLED_ENV_VAR
from config.startup import run_stage_one
from config.startup import stage_one
from tests.conftest import DEPLOYED_AUTHENTICATION_BACKEND
from tests.conftest import DEPLOYED_OIDC_ISSUER
from tests.conftest import valid_deployed_settings_namespace

if TYPE_CHECKING:
    from types import ModuleType

# The evaluation order AD-26 requires be fixed, spelled here so a reordering is a
# failing test rather than a silent change of which refusal an operator sees.
#
# The last two entries carry AD-24 marker pairs, and this is the one place in the
# core suite that needs them. `_refuse_in_process_cache` and `_refuse_eager_tasks`
# are feature-owned regions in `stage_one.py`, so in a combination that selected
# neither Redis nor background task processing the materializer removes both
# definitions *and* their roster entries -- and an assertion here naming a
# function that is no longer in the roster would fail on a tree that is correct.
# The markers make this tuple shrink in step with the roster it mirrors.
EXPECTED_EVALUATION_ORDER = (
    "_refuse_the_local_settings_module",
    "_refuse_sqlite",
    "_refuse_local_credential_paths",
    "_refuse_otel_disabled",
    "_refuse_untrusted_jwks_anchor",
    "_refuse_unconfigured_claims_contract",
    # feature:redis
    "_refuse_in_process_cache",
    # /feature:redis
    # feature:celery
    "_refuse_eager_tasks",
    # /feature:celery
)

SQLITE_ENGINE = "django.db.backends.sqlite3"

# sqlite with the GIS extensions loaded. It ends in `spatialite`, not in
# `sqlite3`, so a single-suffix predicate reads it as a real backend -- while it
# is the same file on the same ephemeral disk, which is the state condition 1
# refuses.
SPATIALITE_ENGINE = "django.contrib.gis.db.backends.spatialite"

POSTGRES_ENGINE = "django.db.backends.postgresql"
MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"
AUTHTOKEN_APP = "rest_framework.authtoken"

# The same app, installed by its `AppConfig` path -- the spelling Django's own
# documentation shows. An equality test against the module path above lets it
# through.
AUTHTOKEN_APP_CONFIG = f"{AUTHTOKEN_APP}.apps.AuthTokenConfig"

TOKEN_AUTHENTICATION = "rest_framework.authentication.TokenAuthentication"  # noqa: S105 - a dotted class path, not a credential

# Two things a URL can carry that a refusal message must not repeat. Chosen to be
# unmistakable in a log line, because the assertion is that they are absent.
SENSITIVE_USERINFO = "svc:hunter2"
SENSITIVE_QUERY_VALUE = "abc123"

# The location Keycloak publishes its keys at, which is why an explicit override
# exists at all: it is under the issuer's path but is not the conventional
# `/.well-known/jwks.json`.
DERIVED_JWKS_URL = f"{DEPLOYED_OIDC_ISSUER}/protocol/openid-connect/certs"

# A location on a host the issuer does not control. It contains the issuer's host
# as a substring on purpose -- a derivation rule written with `startswith` or `in`
# would accept it.
FOREIGN_JWKS_URL = "https://idp.example.invalid.attacker.test/realms/component/certs"

# The state AC #4 names in full: a component anchored to a keypair generated onto
# a developer's laptop, with no key file present at all. Nothing here touches the
# filesystem, so the absence of the file is exactly why an existence check would
# be the wrong mechanism.
LAPTOP_JWKS_URL = "file:///Users/somebody/.local-dev-keys/jwks.json"

# The claims-contract field names, in declaration order, so the parametrization
# below pairs each with its own environment variable by position rather than by a
# second hand-written list that could drift out of step.
CLAIMS_FIELD_NAMES = tuple(field.name for field in fields(ClaimsContract))


@dataclass(frozen=True, slots=True)
class _ContractWithAFifthField(ClaimsContract):
    """A `ClaimsContract` subclass carrying a field no environment variable names.

    `isinstance` admits it, so the condition reaches the point where it pairs
    fields with variables by position -- and that pairing is `strict`, which
    would raise `ValueError` out of a condition contracted to raise
    `ImproperlyConfigured` and nothing else. Declared here rather than mocked
    because the whole question is what `dataclasses.fields` reports for a real
    subclass.
    """

    tenant_claim: str = ""


@pytest.fixture(autouse=True)
def _deployed_and_traced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put every case in this module in a deployed component with tracing on."""
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    monkeypatch.delenv(OTEL_SDK_DISABLED_ENV_VAR, raising=False)


@pytest.fixture
def namespace() -> ModuleType:
    """A deployed settings namespace no condition objects to, ready to be broken."""
    return valid_deployed_settings_namespace()


def _refusal(settings_module: ModuleType) -> str:
    """Run stage 1, insist that it refused, and return the message it refused with.

    Args:
        settings_module: The namespace to evaluate.

    Returns:
        The refusal message, for the caller to assert its distinguishing
        substring on. Substring assertions rather than `pytest.raises(match=...)`
        because the messages carry regex metacharacters -- `DATABASES['default']`
        above all -- and escaping them at every call site reads as noise rather
        than as the claim being made.

    """
    with pytest.raises(ImproperlyConfigured) as refused:
        run_stage_one(settings_module)
    return str(refused.value)


class TestTheRosterAndThePositiveCase:
    """The two claims every case below rests on."""

    def test_the_roster_records_the_evaluation_order(self) -> None:
        """AD-26: one location, one owner, and a *fixed* order.

        Order is contract rather than convenience. A component with two forbidden
        states live meets exactly one refusal, and which one it meets is what an
        operator reads -- so a reordering changes the diagnostic every deployment
        in that state receives.
        """
        roster = stage_one._STAGE_ONE  # noqa: SLF001 - the declared order is the thing under test

        assert tuple(condition.__name__ for condition in roster) == EXPECTED_EVALUATION_ORDER

    def test_a_fully_valid_deployed_namespace_is_accepted(self, namespace: ModuleType) -> None:
        """Without this, a condition that raised unconditionally would pass every case below.

        It is also the assertion that a correctly configured deployment can
        actually boot, which is the half of a refusal contract that nothing else
        in this module says.
        """
        run_stage_one(namespace)


class TestTheSqliteBackendIsReached:
    """Condition 1, over every configured alias (AC #1, AD-9)."""

    @pytest.mark.forbidden_state("sqlite-backend")
    def test_sqlite_on_the_default_alias_refuses(self, namespace: ModuleType) -> None:
        """The state `production.py:26-28` already refuses, in its general form."""
        namespace.DATABASES["default"]["ENGINE"] = SQLITE_ENGINE

        message = _refusal(namespace)

        assert "DATABASES['default']" in message
        assert SQLITE_ENGINE in message

    def test_sqlite_on_a_second_configured_alias_refuses(self, namespace: ModuleType) -> None:
        """AD-9's reason for iterating: `default` is not the only database a component has.

        A contributed database (Epic 9) adds its alias in the leaf settings
        module, and `base.py` fills any alias left unconfigured with the FR-18
        sqlite substitution. Reading only `DATABASES["default"]` would let a
        deployment serve a whole second database off a file on ephemeral disk.
        """
        namespace.DATABASES["reporting"] = {"ENGINE": SQLITE_ENGINE, "NAME": "reporting"}

        message = _refusal(namespace)

        assert "DATABASES['reporting']" in message
        assert "default" not in message, "the refusal named the wrong alias"

    def test_a_second_alias_on_a_real_backend_is_accepted(self, namespace: ModuleType) -> None:
        """Iterating every alias must not become refusing every alias."""
        namespace.DATABASES["reporting"] = {"ENGINE": POSTGRES_ENGINE, "NAME": "reporting"}

        run_stage_one(namespace)

    def test_the_gis_sqlite_backend_refuses_too(self, namespace: ModuleType) -> None:
        """`spatialite` is the same forbidden state under a different suffix.

        `django.contrib.gis.db.backends.spatialite` does not end in `sqlite3`, so
        a one-suffix predicate reads it as a real backend. It is sqlite with the
        GIS extensions loaded: the same file, on the same ephemeral disk, holding
        geometry as well as rows. Put on a second alias here because that is the
        shape it plausibly takes -- a GIS alias beside a PostGIS `default`, which
        is exactly the case AD-9 iterates every alias for.
        """
        namespace.DATABASES["geo"] = {"ENGINE": SPATIALITE_ENGINE, "NAME": "geo.sqlite"}

        message = _refusal(namespace)

        assert "DATABASES['geo']" in message
        assert SPATIALITE_ENGINE in message

    def test_no_databases_at_all_is_not_this_condition_to_refuse(self, namespace: ModuleType) -> None:
        """The scope of condition 1 is *the sqlite backend is reached*, and nothing wider.

        A component with no `DATABASES` at all never reaches sqlite; it is
        refused by Django's own `ConnectionHandler`, which raises
        `ImproperlyConfigured` for a mapping with no `default` alias before any
        query can be issued. Widening this condition to cover it would put a
        second owner on a refusal Django already makes -- and would then have to
        stay in step with it.
        """
        del namespace.DATABASES

        run_stage_one(namespace)


class TestALocalCredentialPathIsLive:
    """Condition 2, four distinct forbidden states, each with its own message (AC #2)."""

    @pytest.mark.forbidden_state("model-backend-installed")
    def test_model_backend_in_the_authentication_backends_refuses(self, namespace: ModuleType) -> None:
        """State 2a: Django's own username-and-password check against the local user table."""
        namespace.AUTHENTICATION_BACKENDS = [MODEL_BACKEND, DEPLOYED_AUTHENTICATION_BACKEND]

        message = _refusal(namespace)

        assert "AUTHENTICATION_BACKENDS" in message
        assert MODEL_BACKEND in message

    def test_the_backend_a_deployed_component_keeps_is_accepted_though_it_subclasses_model_backend(
        self,
        namespace: ModuleType,
    ) -> None:
        """Why condition 2a compares identity and not ancestry.

        `allauth.account.auth_backends.AuthenticationBackend` **is** a
        `ModelBackend` subclass -- asserted here rather than asserted about,
        because the whole point is that it is a fact about the installed
        distribution and not a claim in a comment. It is also the one backend a
        deployed component must keep: every IdP sign-in goes through it. So a
        condition written as `issubclass(resolved, ModelBackend)` refuses the
        correct configuration, which is the first of two reasons the condition
        compares dotted paths.

        The second reason is that it could not resolve them anyway. Stage 1 runs
        inside `apps.populate(settings.INSTALLED_APPS)`, before the app registry
        is ready, and importing either class there raises `AppRegistryNotReady`.
        That failure is invisible to this suite -- pytest-django completes
        `django.setup()` during collection, which is exactly why `import_string`
        works in the two lines below and would not work in a deployed boot.

        The consequence, stated rather than left to be discovered: a `ModelBackend`
        subclass re-exported under another dotted path is **not** refused by this
        condition. Closing that is FR-17's allowlist (Story 4.6), which AD-26
        already specifies as holding objects rather than strings and which
        therefore runs where objects can be resolved.
        """
        assert issubclass(import_string(DEPLOYED_AUTHENTICATION_BACKEND), import_string(MODEL_BACKEND))

        run_stage_one(namespace)

    def test_an_absent_authentication_backends_refuses(self, namespace: ModuleType) -> None:
        """State 2a: deleting the setting does not remove the backend, it restores it.

        `django.conf.global_settings.AUTHENTICATION_BACKENDS` is exactly
        `['django.contrib.auth.backends.ModelBackend']` -- asserted here against
        Django itself rather than quoted, because the whole case rests on it. So a
        settings module that never declares the name runs on `ModelBackend`, and
        a condition that read absence as an empty roster would report a clean
        configuration for the forbidden state at its most complete.

        This is not hypothetical. Deleting `base.py:203-206` is a plausible way
        for Epic 2 Story 2.6/2.8 to "remove `ModelBackend`", and it would
        reinstate it.
        """
        assert global_settings.AUTHENTICATION_BACKENDS == [MODEL_BACKEND]
        del namespace.AUTHENTICATION_BACKENDS

        message = _refusal(namespace)

        assert "AUTHENTICATION_BACKENDS" in message
        assert "absent" in message
        assert MODEL_BACKEND in message

    @pytest.mark.forbidden_state("account-login-methods-declared")
    def test_a_declared_login_method_refuses(self, namespace: ModuleType) -> None:
        """State 2b: any declared method keeps allauth's local sign-in form reachable."""
        namespace.ACCOUNT_LOGIN_METHODS = {"username"}

        message = _refusal(namespace)

        assert "ACCOUNT_LOGIN_METHODS" in message
        assert "username" in message

    def test_an_absent_account_login_methods_refuses(self, namespace: ModuleType) -> None:
        """State 2b: allauth's fallback resolves the username method, so the form stays reachable.

        Asserted against allauth's own resolution rather than against a comment:
        with the setting deleted, `LOGIN_METHODS` still comes back as
        `{LoginMethod.USERNAME}`. Absence is therefore indistinguishable from
        declaring the very thing this state forbids, and the same "Epic 2 deletes
        the line" story applies as for 2a -- `base.py:431` is the line.
        """
        del namespace.ACCOUNT_LOGIN_METHODS

        message = _refusal(namespace)

        assert "ACCOUNT_LOGIN_METHODS" in message
        assert "absent" in message
        assert "empty collection" in message

    @pytest.mark.parametrize(
        ("name", "declared"),
        [
            pytest.param("AUTHENTICATION_BACKENDS", None, id="backends-none"),
            pytest.param("AUTHENTICATION_BACKENDS", MODEL_BACKEND, id="backends-bare-string"),
            pytest.param("ACCOUNT_LOGIN_METHODS", None, id="login-methods-none"),
            pytest.param("INSTALLED_APPS", None, id="installed-apps-none"),
            pytest.param("INSTALLED_APPS", 7, id="installed-apps-not-iterable"),
        ],
    )
    def test_a_setting_that_is_not_a_roster_refuses_rather_than_escaping(
        self,
        namespace: ModuleType,
        name: str,
        declared: object,
    ) -> None:
        """A name the condition cannot read is refused, not skipped and not crashed through.

        Two failures collapse into one guard. Iterating `None` or an `int` raises
        `TypeError` straight out of a condition whose whole contract is that it
        raises `ImproperlyConfigured` and nothing else (CG-3) -- a boot failure
        that reads as a bug in the refusal contract rather than as a
        misconfiguration. And a bare string is *iterable*, so
        `AUTHENTICATION_BACKENDS = "…ModelBackend"` would be read one character
        at a time and match nothing at all: a typo presenting as a clean
        configuration, which is the one thing a refusal contract must never do.
        """
        setattr(namespace, name, declared)

        message = _refusal(namespace)

        assert name in message
        assert type(declared).__name__ in message

    @pytest.mark.parametrize(
        "configured",
        [
            pytest.param(False, id="false"),
            pytest.param("true", id="a-truthy-string-that-is-not-True"),
            pytest.param(1, id="a-truthy-int-that-is-not-True"),
            pytest.param(None, id="declared-as-none"),
        ],
    )
    def test_an_admin_not_forced_through_allauth_refuses(
        self,
        namespace: ModuleType,
        configured: object,
    ) -> None:
        """State 2c: anything other than `True` leaves `/admin/` serving Django's own form.

        The truthy-but-not-`True` cases are the ones a looser predicate would let
        through. `DJANGO_ADMIN_FORCE_ALLAUTH` reaching settings as the *string*
        `"true"` -- a variable read with `env.str` instead of `env.bool` somewhere
        down the line -- is truthy and is not the setting allauth reads.
        """
        namespace.DJANGO_ADMIN_FORCE_ALLAUTH = configured

        message = _refusal(namespace)

        assert "DJANGO_ADMIN_FORCE_ALLAUTH" in message
        assert repr(configured) in message

    @pytest.mark.forbidden_state("admin-not-forced-through-allauth")
    def test_an_absent_admin_force_setting_refuses(self, namespace: ModuleType) -> None:
        """State 2c: absent counts as not true, and says so rather than saying `None`."""
        del namespace.DJANGO_ADMIN_FORCE_ALLAUTH

        message = _refusal(namespace)

        assert "DJANGO_ADMIN_FORCE_ALLAUTH" in message
        assert "absent" in message

    @pytest.mark.forbidden_state("static-token-surface")
    def test_the_authtoken_app_being_installed_refuses(self, namespace: ModuleType) -> None:
        """State 2d, first half: the app that mints and stores local API tokens."""
        namespace.INSTALLED_APPS = [*namespace.INSTALLED_APPS, AUTHTOKEN_APP]

        message = _refusal(namespace)

        assert "INSTALLED_APPS" in message
        assert AUTHTOKEN_APP in message

    def test_the_authtoken_app_installed_by_its_config_path_refuses(self, namespace: ModuleType) -> None:
        """State 2d, first half: the same app, spelled the other way Django accepts.

        `INSTALLED_APPS` takes an `AppConfig` path as readily as a module path,
        and `rest_framework.authtoken.apps.AuthTokenConfig` installs exactly the
        app the bare path does -- same models, same table, same tokens. An
        equality test against the module path is escapable by spelling, and by
        the spelling Django's own documentation recommends, so it would fail
        against a component that had done nothing unusual at all.
        """
        namespace.INSTALLED_APPS = [*namespace.INSTALLED_APPS, AUTHTOKEN_APP_CONFIG]

        message = _refusal(namespace)

        assert "INSTALLED_APPS" in message
        assert AUTHTOKEN_APP_CONFIG in message

    def test_an_app_whose_name_merely_starts_with_the_authtoken_path_is_accepted(
        self,
        namespace: ModuleType,
    ) -> None:
        """The prefix match is on a dotted boundary, not on characters.

        Without the separator, `rest_framework.authtoken2` would refuse -- a
        different app, refused for having a name that begins the same way.
        """
        namespace.INSTALLED_APPS = [*namespace.INSTALLED_APPS, f"{AUTHTOKEN_APP}2"]

        run_stage_one(namespace)

    def test_token_authentication_among_the_api_defaults_refuses(self, namespace: ModuleType) -> None:
        """State 2d, second half: the class is a credential surface with or without the app.

        Both halves are covered because either alone admits a credential the IdP
        does not own and cannot revoke -- the app without the class stores tokens
        nothing reads, and the class without the app reads a table that has to
        exist for the deployment to have got this far.
        """
        namespace.REST_FRAMEWORK = {
            "DEFAULT_AUTHENTICATION_CLASSES": (
                "config.authorization.authentication.OIDCBearerAuthentication",
                TOKEN_AUTHENTICATION,
            ),
        }

        message = _refusal(namespace)

        assert "DEFAULT_AUTHENTICATION_CLASSES" in message
        assert TOKEN_AUTHENTICATION in message

    def test_a_rest_framework_block_that_is_not_a_mapping_refuses(self, namespace: ModuleType) -> None:
        """The same "unreadable is refused, not skipped" rule, one level down."""
        namespace.REST_FRAMEWORK = ["DEFAULT_AUTHENTICATION_CLASSES"]

        message = _refusal(namespace)

        assert "REST_FRAMEWORK" in message
        assert "list" in message

    def test_an_api_class_list_that_is_not_a_roster_refuses(self, namespace: ModuleType) -> None:
        """And one level down again, where the label has to name the key as well as the setting."""
        namespace.REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": None}

        message = _refusal(namespace)

        assert "DEFAULT_AUTHENTICATION_CLASSES" in message
        assert "NoneType" in message

    def test_the_two_names_whose_framework_default_is_harmless_are_neutral_when_absent(
        self,
        namespace: ModuleType,
    ) -> None:
        """Absence is judged against the framework default, so it is not uniformly refused.

        Django's own `INSTALLED_APPS` default is empty and DRF's default
        authentication classes are session and basic -- neither names the token
        surface, so an undeclared name here is genuinely not the forbidden state.
        The asymmetry with `AUTHENTICATION_BACKENDS` above is the whole point:
        what decides is what the framework falls back to, never whether the line
        is present.
        """
        del namespace.INSTALLED_APPS
        del namespace.REST_FRAMEWORK

        run_stage_one(namespace)


class TestTheOpenTelemetrySdkIsDisabled:
    """Condition 3, the one input read from the environment rather than the namespace (AC #3)."""

    @pytest.mark.parametrize(
        "configured",
        [
            pytest.param("true", id="true"),
            pytest.param("TRUE", id="uppercased"),
            pytest.param("  true  ", id="padded"),
            pytest.param("1", id="one"),
            pytest.param("yes", id="yes"),
        ],
    )
    @pytest.mark.forbidden_state("otel-sdk-disabled")
    def test_a_disabled_sdk_refuses(
        self,
        monkeypatch: pytest.MonkeyPatch,
        namespace: ModuleType,
        configured: str,
    ) -> None:
        """Every spelling `config.observability.telemetry` acts on is a spelling this refuses.

        `1` and `yes` are here deliberately, and they are wider than the
        specification's literal `"true"`. The reader that decides whether tracing
        is installed recognizes all three, so a refusal matching only `"true"`
        would leave `OTEL_SDK_DISABLED=1` disabling tracing in a deployed
        component with nothing refusing it.
        """
        monkeypatch.setenv(OTEL_SDK_DISABLED_ENV_VAR, configured)

        message = _refusal(namespace)

        assert OTEL_SDK_DISABLED_ENV_VAR in message

    @pytest.mark.parametrize(
        "configured",
        [
            pytest.param("false", id="false"),
            pytest.param("0", id="zero"),
            pytest.param("", id="empty"),
        ],
    )
    def test_an_enabled_sdk_is_accepted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        namespace: ModuleType,
        configured: str,
    ) -> None:
        """The other half of the widening: `0` and `false` are not an opt-out."""
        monkeypatch.setenv(OTEL_SDK_DISABLED_ENV_VAR, configured)

        run_stage_one(namespace)


class TestTheJwksTrustAnchorIsNotDerivedFromTheIssuer:
    """Condition 4, syntactic and nothing else (AC #4, AD-23)."""

    def test_an_unset_issuer_refuses(self, namespace: ModuleType) -> None:
        """With no issuer there is no anchor, so there is nothing to derive from."""
        namespace.OIDC_ISSUER = ""

        message = _refusal(namespace)

        assert "OIDC_ISSUER" in message
        assert "unset" in message

    def test_a_location_that_resolves_to_nothing_refuses(self, namespace: ModuleType) -> None:
        """A declared issuer that derives no location at all.

        Narrow but real: an issuer of nothing but separators reads as declared --
        it is a non-empty string -- and then strips to nothing when the
        conventional location is derived from it, leaving the component with no
        JWKS location and no diagnostic saying so.
        """
        namespace.OIDC_ISSUER = "/"
        namespace.OIDC_JWKS_URL = ""

        message = _refusal(namespace)

        assert "derives no JWKS location" in message
        # The variable at fault is the issuer, and the message has to name it.
        # This branch is reachable *only* when the explicit location was left
        # unset, so a message telling the operator to leave
        # `COMPONENT_OIDC_JWKS_URL` unset would be telling them to keep doing the
        # one thing they already did -- correct advice pointed at the wrong
        # variable, which costs more than no advice.
        assert "COMPONENT_OIDC_ISSUER" in message
        assert "COMPONENT_OIDC_JWKS_URL unset" not in message

    def test_a_refusal_never_echoes_a_credential_carried_in_a_url(self, namespace: ModuleType) -> None:
        """NFR-7: a boot failure ends up in deployment logs, so it echoes nothing that could be a secret.

        Both interpolated values carry something they should not: the issuer has
        userinfo and the location has userinfo and a query-string token. A URL is
        a perfectly ordinary place for a credential to be hiding -- basic-auth
        userinfo in front of an internal endpoint, an `?access_token=` on a
        location copied out of a browser -- and the refusal is written before
        anybody has had a chance to notice.

        What survives redaction is what a reader actually needs: scheme, host,
        port and path are what decide whether the location derives from the
        issuer, and none of them is where a secret lives.
        """
        namespace.OIDC_ISSUER = f"https://{SENSITIVE_USERINFO}@idp.example.invalid/realms/component"
        namespace.OIDC_JWKS_URL = f"https://{SENSITIVE_USERINFO}@attacker.test/certs?bearer={SENSITIVE_QUERY_VALUE}"

        message = _refusal(namespace)

        assert SENSITIVE_USERINFO not in message
        assert SENSITIVE_QUERY_VALUE not in message
        assert "attacker.test" in message, "redaction removed the host, which is the finding itself"
        assert "/realms/component" in message

    def test_a_location_whose_authority_will_not_parse_is_suppressed_rather_than_partly_shown(
        self,
        namespace: ModuleType,
    ) -> None:
        """Redaction fails safe: what cannot be parsed cannot be shown to be secret-free.

        `SplitResult.port` raises `ValueError` on a port outside 0-65535, so the
        renderer cannot separate the parts it keeps from the parts it drops. It
        suppresses the whole location rather than reconstructing part of it,
        which costs a little diagnostic detail on an input that is already
        malformed and costs nothing else.

        The refusal itself still fires: `jwks_url_derives_from_issuer` answers
        False for an unparseable authority rather than raising, which is the
        property Story 2.7 built into it for exactly this caller.
        """
        namespace.OIDC_JWKS_URL = f"https://{SENSITIVE_USERINFO}@idp.example.invalid:99999/certs"

        message = _refusal(namespace)

        assert "<unreadable location>" in message
        assert SENSITIVE_USERINFO not in message

    @pytest.mark.forbidden_state("untrusted-jwks-anchor")
    def test_a_location_on_a_host_the_issuer_does_not_control_refuses(self, namespace: ModuleType) -> None:
        """The refusal AD-23 exists for: a trust anchor somebody else can rotate."""
        namespace.OIDC_JWKS_URL = FOREIGN_JWKS_URL

        message = _refusal(namespace)

        assert "OIDC_JWKS_URL" in message
        assert FOREIGN_JWKS_URL in message
        assert DEPLOYED_OIDC_ISSUER in message

    def test_a_location_on_a_developers_laptop_refuses(self, namespace: ModuleType) -> None:
        """AC #4 in full: a `file://` anchor, with no key file present at all.

        The file named here does not exist and is never looked for. That is the
        point rather than an oversight -- a condition that checked the filesystem
        would pass this case on any machine where the developer had since deleted
        the directory, which is the machine least likely to be the one deploying.
        """
        namespace.OIDC_JWKS_URL = LAPTOP_JWKS_URL

        message = _refusal(namespace)

        assert LAPTOP_JWKS_URL in message

    def test_an_explicit_location_under_the_issuer_is_accepted(self, namespace: ModuleType) -> None:
        """Keycloak does not publish at the conventional path, which is why the override exists."""
        namespace.OIDC_JWKS_URL = DERIVED_JWKS_URL

        run_stage_one(namespace)

    def test_the_condition_makes_no_network_call(self, no_network: None, namespace: ModuleType) -> None:
        """FR-23 and NFR-1: derived from, never confirmed against.

        Confirming the location against the issuer's published discovery document
        would mean fetching it, and boot makes no outbound request. Asserted with
        the delivered socket guard rather than by patching one library, because a
        guard installed on `requests` proves nothing about the library a condition
        actually reached for.
        """
        namespace.OIDC_JWKS_URL = DERIVED_JWKS_URL

        run_stage_one(namespace)

    def test_the_refusal_path_makes_no_network_call_either(
        self,
        no_network: None,
        namespace: ModuleType,
    ) -> None:
        """The likelier regression: a condition that fetches only to explain itself."""
        namespace.OIDC_JWKS_URL = FOREIGN_JWKS_URL

        assert FOREIGN_JWKS_URL in _refusal(namespace)


class TestTheClaimsContractIsUnconfigured:
    """Condition 5, its stage-1 half (AC #5). The stage-2 half is Story 4.3's."""

    def test_a_contract_carrying_all_four_names_is_accepted(self) -> None:
        """This condition's own positive control (FR-16, Story 4.5 Task 7).

        Every other condition in this module has one beside its refusals; this
        one had only the module-wide `test_a_fully_valid_deployed_namespace_is_
        accepted`, which is an assertion about the namespace rather than about
        the predicate. A condition hardcoded to raise would pass all six of the
        refusal cases below and be caught only by a case that hands it a contract
        it must accept.

        Driven through `run_stage_one` like everything else here, and asserted by
        the absence of a refusal: the four names are the ones
        `config.authorization.claims` declares, so a contract that satisfied a
        weaker reading of "configured" would not satisfy this.
        """
        namespace = valid_deployed_settings_namespace()
        namespace.CLAIMS_CONTRACT = ClaimsContract(
            identity_key_claim="sub",
            group_claim="groups",
            staff_group="platform-staff",
            superuser_group="platform-superuser",
        )

        run_stage_one(namespace)

    @pytest.mark.forbidden_state("unconfigured-claims-contract")
    def test_an_absent_contract_refuses(self, namespace: ModuleType) -> None:
        """Nothing having built the contract at all is itself a forbidden state."""
        del namespace.CLAIMS_CONTRACT

        message = _refusal(namespace)

        assert "CLAIMS_CONTRACT" in message
        assert "absent" in message

    def test_a_contract_that_is_not_a_contract_refuses(self, namespace: ModuleType) -> None:
        """A mapping carrying the right keys is not the contract the mapper reads.

        `settings.CLAIMS_CONTRACT` is consumed as an object with four attributes,
        so a dict there fails at the first authenticated request rather than at
        boot -- which is the inversion this whole contract exists to undo.
        """
        namespace.CLAIMS_CONTRACT = {"identity_key_claim": "sub", "group_claim": "groups"}

        message = _refusal(namespace)

        assert "CLAIMS_CONTRACT" in message
        assert "dict" in message

    @pytest.mark.parametrize(
        ("field_name", "variable"),
        list(zip(CLAIMS_FIELD_NAMES, CLAIMS_ENVIRONMENT_VARIABLES, strict=True)),
        ids=CLAIMS_ENVIRONMENT_VARIABLES,
    )
    def test_each_missing_claims_value_refuses_and_names_its_own_variable(
        self,
        namespace: ModuleType,
        field_name: str,
        variable: str,
    ) -> None:
        """FR-16: four states, four tests, four distinguishable messages.

        The pairing is positional, taken from the dataclass's own field order and
        `CLAIMS_ENVIRONMENT_VARIABLES`, so this parametrization cannot drift from
        the condition's -- both read the same two declarations. `strict=True`
        turns a fifth field added without a fifth variable into a collection
        error rather than a silently shortened list.

        The negative half of the assertion is the load-bearing one. An operator
        told "the claims contract is unconfigured" has to go and check four
        variables; an operator told which one is unset has to check one.
        """
        namespace.CLAIMS_CONTRACT = replace(namespace.CLAIMS_CONTRACT, **{field_name: ""})

        message = _refusal(namespace)

        assert variable in message
        assert [other for other in CLAIMS_ENVIRONMENT_VARIABLES if other != variable and other in message] == []

    def test_a_contract_carrying_an_unnamed_field_refuses_rather_than_raising_value_error(
        self,
        namespace: ModuleType,
    ) -> None:
        """CG-3: the only exception out of a condition is `ImproperlyConfigured`.

        A subclass with a fifth field passes `isinstance` and then meets the
        positional pairing of fields against `CLAIMS_ENVIRONMENT_VARIABLES`.
        `strict=True` is right to object -- pairing four variables against five
        fields would silently name the wrong one -- but `ValueError` out of a
        settings import is a boot failure that reads as a defect in the refusal
        contract rather than as the misconfiguration it is.

        Every field is populated here on purpose, so the case cannot pass by
        being caught as an ordinary unconfigured contract: what is wrong is the
        contract's *shape*, and a field no variable names cannot be configured by
        an operator however the object was built.
        """
        namespace.CLAIMS_CONTRACT = _ContractWithAFifthField(
            identity_key_claim="sub",
            group_claim="groups",
            staff_group="platform-staff",
            superuser_group="platform-superuser",
            tenant_claim="tenant",
        )

        message = _refusal(namespace)

        assert "CLAIMS_CONTRACT" in message
        assert "5 fields" in message
        assert f"{len(CLAIMS_ENVIRONMENT_VARIABLES)} environment variables" in message

    def test_the_shape_is_checked_before_the_pairing_that_would_have_raised(
        self,
        namespace: ModuleType,
    ) -> None:
        """The literal regression: a fifth field *and* an unset base name.

        This is the input that reached the strict zip. `is_configured` is False,
        so the case above -- which populates everything and returns early on the
        old code -- does not cover it. What it asserts is placement: the count
        guard has to sit above the `is_configured` return, or this input still
        arrives at the pairing and still raises `ValueError`.
        """
        namespace.CLAIMS_CONTRACT = _ContractWithAFifthField(
            identity_key_claim="sub",
            group_claim="groups",
            staff_group="platform-staff",
            superuser_group="",
            tenant_claim="tenant",
        )

        assert "5 fields" in _refusal(namespace)

    def test_more_than_one_missing_value_names_every_one_of_them(self, namespace: ModuleType) -> None:
        """A half-configured contract is the likely case, not the single-variable one.

        Reporting only the first would send an operator round the loop once per
        variable: fix one, redeploy, meet the next refusal.
        """
        namespace.CLAIMS_CONTRACT = replace(namespace.CLAIMS_CONTRACT, staff_group="", superuser_group="")

        message = _refusal(namespace)

        assert "COMPONENT_STAFF_GROUP" in message
        assert "COMPONENT_SUPERUSER_GROUP" in message
