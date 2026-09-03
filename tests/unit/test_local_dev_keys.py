"""The development keypair: refused unless local, generated once, never rewritten.

Every case here relocates `DEV_KEY_DIR` into `tmp_path` with `monkeypatch`, the
way `tests/unit/test_observability_init.py` relocates `BASE_DIR`. Nothing touches
the database, the network or the repository root -- the module reads the constant
at call time precisely so a test can move it.

The suite runs in the `dev` pixi environment, which declares
`COMPONENT_RUNTIME=local`, so the *absent* cases are reached by deleting the
variable rather than by setting it.

RSA-2048 generation is the slowest thing in the unit suite. Each case gets its
own directory because idempotence, first-generation and refusal are all
statements about a directory's *history*, and a shared keypair would erase the
only state they are about.
"""

from __future__ import annotations

import json
import os
import stat
from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.local_dev import keys
from config.local_dev.keys import JWKS_FILENAME
from config.local_dev.keys import PRIVATE_KEY_FILENAME
from config.local_dev.keys import SIGNING_ALGORITHM
from config.local_dev.keys import DevKeypair
from config.local_dev.keys import ensure_keypair
from config.local_dev.keys import load_private_key
from config.locality import RUNTIME_ENV_VAR

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def key_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module at a directory this test owns."""
    target = tmp_path / ".local-dev-keys"
    monkeypatch.setattr(keys, "DEV_KEY_DIR", target)
    return target


#: The modes NFR-7 requires, named rather than written at the assertion so the
#: numbers read as the policy they are.
PRIVATE_KEY_MODE = 0o600
KEY_DIR_MODE = 0o700


@pytest.fixture
def keypair(key_dir: Path) -> DevKeypair:
    """One generated keypair, for the cases that only read it."""
    return ensure_keypair()


@pytest.mark.parametrize(
    "runtime",
    [
        pytest.param(None, id="unset"),
        pytest.param("production", id="unrecognized"),
        pytest.param("", id="empty"),
    ],
)
def test_generation_is_refused_unless_the_run_is_local(
    key_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime: str | None,
) -> None:
    """AD-13 fails closed: absent or unrecognized means deployed, and deployed means no key."""
    if runtime is None:
        monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(RUNTIME_ENV_VAR, runtime)

    with pytest.raises(ImproperlyConfigured, match=RUNTIME_ENV_VAR):
        ensure_keypair()

    # Refused before the filesystem is touched, so a deployed invocation leaves
    # nothing at all behind -- not even an empty directory whose presence would
    # later read as "a key was generated here once".
    assert not key_dir.exists()


def test_the_keypair_is_generated_on_demand(key_dir: Path) -> None:
    """Absent before the first call, present after it (AC #1, #4)."""
    assert not key_dir.exists()

    keypair = ensure_keypair()

    assert keypair.private_key_path == key_dir / PRIVATE_KEY_FILENAME
    assert keypair.jwks_path == key_dir / JWKS_FILENAME
    assert keypair.private_key_path.is_file()
    assert keypair.jwks_path.is_file()
    assert keypair.kid


def test_a_second_call_reuses_the_key_it_finds(key_dir: Path) -> None:
    """Idempotent: the same `kid`, and the PEM on disk is byte-for-byte the one already there.

    This is what makes a token minted an hour ago still verifiable against the
    document served now -- a regenerated key would publish a `kid` no outstanding
    token names.
    """
    first = ensure_keypair()
    original_pem = first.private_key_path.read_bytes()

    second = ensure_keypair()

    assert second.kid == first.kid
    assert second.private_key_path.read_bytes() == original_pem
    assert json.loads(key_dir.joinpath(JWKS_FILENAME).read_text(encoding="utf-8"))["keys"][0]["kid"] == first.kid


def test_the_private_key_is_written_with_the_restricted_mode_requested(
    key_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NFR-7's request, asserted on every platform: `os.open` is handed `0o600`.

    The mode *bits on disk* are asserted separately and only on POSIX -- see
    `test_the_key_material_is_readable_only_by_its_owner`. This case is the
    platform-independent half: Windows synthesises `st_mode`, so on the
    `windows-latest` leg of the compatibility matrix the filesystem can never
    report `0o600` no matter what the module asked for. What is portable is the
    argument the module passes, and a regression that dropped it -- writing the
    PEM with `write_bytes` and its default `0o666` -- would be invisible to a
    POSIX-only assertion running on a green Windows job.
    """
    requested: list[int] = []
    real_open = os.open

    def recording_open(path: object, flags: int, mode: int = 0o777, **kwargs: object) -> int:
        requested.append(mode)
        return real_open(path, flags, mode, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(keys.os, "open", recording_open)

    ensure_keypair()

    assert PRIVATE_KEY_MODE in requested


def test_the_key_material_is_readable_only_by_its_owner(keypair: DevKeypair) -> None:
    """NFR-7: `0o600` on the PEM and `0o700` on the directory holding it.

    Branched rather than skipped. `tests/unit/test_suite_policy.py` bans
    `skip`/`skipif`/`xfail`, and the compatibility matrix in
    `.github/workflows/ci.yml` runs `pixi run test` on `windows-latest`, where
    `os.stat` synthesises `st_mode` from the read-only flag alone and no mode
    this module sets can produce `0o600`. The guarantee is POSIX-only and
    `config/local_dev/keys.py` says so; asserting it where it cannot hold would
    fail the gate on a platform doing nothing wrong.
    """
    if os.name != "posix":
        return

    assert stat.S_IMODE(keypair.private_key_path.stat().st_mode) == PRIVATE_KEY_MODE
    assert stat.S_IMODE(keypair.private_key_path.parent.stat().st_mode) == KEY_DIR_MODE


def test_loose_modes_on_an_existing_directory_are_tightened(key_dir: Path) -> None:
    """A key directory restored at `0o755` does not stay at `0o755` (NFR-7).

    `mkdir(mode=..., exist_ok=True)` ignores `mode` for a directory that already
    exists, and an existing PEM is loaded without its mode being looked at. A
    directory recovered from a backup, copied with `cp -r`, or unpacked from a
    tarball arrives world-readable, and without the tightening it is reused in
    silence -- NFR-7 false on a shared machine with nothing reporting it.
    """
    if os.name != "posix":
        return

    ensure_keypair()
    key_dir.chmod(0o755)
    (key_dir / PRIVATE_KEY_FILENAME).chmod(0o644)

    ensure_keypair()

    assert stat.S_IMODE(key_dir.stat().st_mode) == KEY_DIR_MODE
    assert stat.S_IMODE((key_dir / PRIVATE_KEY_FILENAME).stat().st_mode) == PRIVATE_KEY_MODE


def test_a_deleted_published_document_is_restored(key_dir: Path) -> None:
    """Deleting only `jwks.json` is recoverable without deleting the key too.

    `settings.OIDC_JWKS_URL` names that exact file, so its absence refuses every
    Bearer request. Without the unconditional re-render the document would only
    ever be written on the call that *generated* the key -- so a hand-deleted
    document could never come back while the PEM remained, and local
    authorization would be permanently broken by removing a file that carries no
    secret at all.
    """
    first = ensure_keypair()
    original_pem = first.private_key_path.read_bytes()
    first.jwks_path.unlink()

    second = ensure_keypair()

    assert second.jwks_path.is_file()
    assert second.kid == first.kid
    # The key itself was not regenerated to bring the document back: an
    # outstanding token still names a published `kid`.
    assert second.private_key_path.read_bytes() == original_pem
    assert json.loads(second.jwks_path.read_text(encoding="utf-8"))["keys"][0]["kid"] == first.kid


def test_an_unreadable_pem_is_refused_by_name(key_dir: Path) -> None:
    """A corrupt PEM names itself in the refusal (AC #1).

    `load_pem_private_key` raises a bare `ValueError` for a truncated file and a
    bare `TypeError` for a passphrase-encrypted one, neither carrying the path.
    Left uncaught the developer sees `Could not deserialize key data` with no way
    to tell which file to delete -- and deleting it is always the remedy.
    """
    keypair = ensure_keypair()
    keypair.private_key_path.write_text("-----BEGIN PRIVATE KEY-----\nnot a key\n", encoding="utf-8")

    with pytest.raises(ImproperlyConfigured, match=PRIVATE_KEY_FILENAME):
        ensure_keypair()


def test_the_published_document_holds_exactly_one_public_key(keypair: DevKeypair) -> None:
    """The JWK Set is what `jwt.PyJWKSet.from_dict` consumes, and it names this key alone."""
    document = json.loads(keypair.jwks_path.read_text(encoding="utf-8"))

    assert list(document) == ["keys"]
    assert len(document["keys"]) == 1
    published = document["keys"][0]
    assert published["kid"] == keypair.kid
    assert published["kty"] == "RSA"
    assert published["alg"] == SIGNING_ALGORITHM
    assert published["use"] == "sig"
    # The private half never reaches the document. A JWK Set carrying `d` would be
    # a secret in a file nothing protects, published at a location the component
    # is configured to read.
    assert "d" not in published


def test_the_private_half_is_loadable_and_matches_what_was_published(keypair: DevKeypair) -> None:
    """`load_private_key` is how `tokens.py` signs without spelling the PEM's path again."""
    private_key = load_private_key(keypair)
    published = json.loads(keypair.jwks_path.read_text(encoding="utf-8"))["keys"][0]

    assert private_key.key_size == keys.KEY_SIZE
    # `n` is the modulus of the published half; deriving it from the loaded
    # private key is what proves the two files describe one keypair rather than
    # two that happen to sit in the same directory.
    assert keys._public_jwk(private_key)["n"] == published["n"]  # noqa: SLF001 - the rendering under test


def test_a_key_file_of_the_wrong_type_is_refused_rather_than_carried(key_dir: Path) -> None:
    """An EC key here would surface as a `TypeError` inside PyJWT with nothing naming the file."""
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415 - one case needs it
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415 - see above

    key_dir.mkdir(parents=True)
    key_dir.joinpath(PRIVATE_KEY_FILENAME).write_bytes(
        ec.generate_private_key(ec.SECP256R1()).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )

    with pytest.raises(ImproperlyConfigured, match="does not hold an RSA private key"):
        ensure_keypair()
