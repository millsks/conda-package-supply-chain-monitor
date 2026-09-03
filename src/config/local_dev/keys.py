"""The development signing keypair: generated on demand, locally and nowhere else.

NFR-7 is the whole of this module, and it carries more weight here than the same
rule does in an ordinary repository. This tree is a template: a keypair committed
to it ships inside *every component generated from it*, so one published private
key would be shared by every service the accelerator ever produces. There is no
key in source, there is no key in a packaging manifest, and `DEV_KEY_DIR` is
gitignored. The only key that ever exists is the one a developer's own machine
generated for itself.

**Nothing here runs at import.** FR-23 makes a boot-time side effect a defect,
and RSA-2048 generation is an expensive one: called from an `AppConfig.ready()`
or a settings module, every `pixi run manage` invocation would generate a keypair
before doing anything else. `ensure_keypair()` is called by the minting entry
point and by tests, and by nothing on the start path. `config/settings/local.py`
imports `DEV_KEY_DIR` from this module to name the JWKS location -- importing the
name is not calling the function, and this module reads no settings, so the
import direction stays acyclic.

**It refuses unless the run is local**, before it touches the filesystem. The
refusal is `ImproperlyConfigured` rather than `Http404`: this is operator-invoked
code like `config/local_dev/seeding.py`, not a request-reachable view, and an
operator who ran it in a deployed environment needs to be told which declaration
was missing.

**The mode protection is POSIX-only, and `win-64` is a declared platform.**
`0o700` on the directory and `0o600` on the PEM are enforced on every call, not
only at creation -- but Windows carries no POSIX permission bits, so on that
platform `os.open`'s mode argument and `Path.chmod` control the read-only flag
and nothing else. NFR-7's "readable only by its owner" is therefore a guarantee
this module makes on POSIX and cannot make on Windows, where the directory is
protected by the user profile's ACL or not at all. Stated here rather than left
for `_KEY_DIR_MODE` and `_PRIVATE_KEY_MODE` to imply: a constant that names a
protection reads as a protection delivered.

The `kid` is the RFC 7638 thumbprint of the public key rather than a counter or a
timestamp, so it is a function of the key material and nothing else. A reload
derives the same identifier as the generation did, which is what makes
`ensure_keypair()` idempotent in the sense that matters: the JWKS document served
from disk and the `kid` header on a token minted an hour later still agree.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Final

import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.exceptions import ImproperlyConfigured
from jwt.algorithms import RSAAlgorithm

from config.locality import RUNTIME_ENV_VAR
from config.locality import is_local

__all__ = [
    "DEV_KEY_DIR",
    "JWKS_FILENAME",
    "PRIVATE_KEY_FILENAME",
    "SIGNING_ALGORITHM",
    "DevKeypair",
    "ensure_keypair",
    "load_private_key",
]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: Repository root: local_dev -> config -> src -> root. The idiom
#: `config/observability/__init__.py` already uses, rather than a fifth spelling
#: of the same walk.
BASE_DIR: Final[Path] = Path(__file__).resolve().parents[3]

#: Where the development keypair lives. **The one declaration site** -- nothing
#: else in the tree spells this directory name, and `.gitignore` carries the
#: matching entry. Keeping it here rather than in settings is what lets a unit
#: test relocate it into `tmp_path` with one `monkeypatch.setattr`.
DEV_KEY_DIR: Final[Path] = BASE_DIR / ".local-dev-keys"

#: The two files inside it. The JWKS document is what `config/settings/local.py`
#: points `OIDC_JWKS_URL` at, so its name is part of this module's contract.
PRIVATE_KEY_FILENAME: Final[str] = "signing-key.pem"
JWKS_FILENAME: Final[str] = "jwks.json"

#: Directory and file permissions. `0o700` and `0o600` are not decoration: the
#: directory sits in the repository root on a machine that may be shared, and the
#: PEM is written unencrypted because a passphrase a task would have to supply
#: from source is not a passphrase.
_KEY_DIR_MODE: Final[int] = 0o700
_PRIVATE_KEY_MODE: Final[int] = 0o600

#: The key parameters. 2048 bits is the smallest modulus a real IdP would publish
#: -- small enough that generation does not dominate a test run, large enough that
#: what the Bearer class verifies locally is the shape it verifies in production.
KEY_SIZE: Final[int] = 2048
PUBLIC_EXPONENT: Final[int] = 65537

#: The one algorithm the component's default allowlist admits
#: (`config/authorization/authentication.py`'s `_DEFAULT_ALGORITHMS`). Published
#: in the JWK so the document says what the key is for; the allowlist, never the
#: token header, is what decides at verification time.
SIGNING_ALGORITHM: Final[str] = "RS256"

#: The refusal, named rather than written at the `raise`, in the shape
#: `config/local_dev/seeding.py` established. It states the variable an operator
#: has to look at, because the one thing they cannot infer from the exception is
#: which declaration was missing.
_DEPLOYED_REFUSAL: Final[str] = (
    f"a development signing keypair is never generated in a deployed environment. "
    f"{RUNTIME_ENV_VAR} does not declare this run local, and locality fails closed: "
    f"absent or unrecognized means deployed. Locally, run it as `pixi run -e dev mint-token <persona>`."
)

#: The members of an RSA public JWK the RFC 7638 thumbprint is computed over, in
#: the lexicographic order the RFC mandates. Written out rather than sorted from
#: whatever the rendering happened to produce: the thumbprint is only stable
#: because this list and this order are fixed.
_THUMBPRINT_MEMBERS: Final[tuple[str, ...]] = ("e", "kty", "n")


@dataclass(frozen=True, slots=True)
class DevKeypair:
    """The development keypair as it exists on disk.

    Attributes:
        kid: The key identifier, derived from the public key itself. Tokens carry
            it in their header and `config/authorization/jwks.py` indexes the
            published document on it.
        private_key_path: The PEM holding the private half.
        jwks_path: The JWK Set document holding the public half, which is what
            `settings.OIDC_JWKS_URL` names locally.

    """

    kid: str
    private_key_path: Path
    jwks_path: Path


def ensure_keypair() -> DevKeypair:
    """Generate the development keypair if it is absent, and describe it either way.

    Idempotent by construction: a second call finds the PEM, loads it, and derives
    the same `kid` from the same public key. Nothing is rewritten, so a token
    minted against an earlier call still names a key the document on disk
    publishes.

    Returns:
        The keypair on disk.

    Raises:
        ImproperlyConfigured: The run is not local. Raised before the directory is
            created, so a deployed invocation leaves nothing behind at all.

    """
    if not is_local():
        raise ImproperlyConfigured(_DEPLOYED_REFUSAL)

    key_dir = DEV_KEY_DIR
    private_key_path = key_dir / PRIVATE_KEY_FILENAME
    jwks_path = key_dir / JWKS_FILENAME

    key_dir.mkdir(mode=_KEY_DIR_MODE, parents=True, exist_ok=True)

    if private_key_path.exists():
        private_key = _read_private_key(private_key_path)
    else:
        private_key = rsa.generate_private_key(public_exponent=PUBLIC_EXPONENT, key_size=KEY_SIZE)
        _write_private_key(private_key_path, private_key)
        logger.info("local_dev.keypair_generated", path=str(private_key_path), key_size=KEY_SIZE)

    # Tightened on every call, not only on the call that created them. `mkdir`
    # ignores `mode` entirely when the directory already exists, and an existing
    # PEM is loaded without its mode ever being looked at -- so a directory
    # restored from a backup, copied between machines with `cp -r`, or unpacked
    # from a tarball comes back at `0o755`/`0o644` and is reused in silence. The
    # guarantee NFR-7 states would then be false on a machine this module's own
    # docstring says may be shared, with nothing anywhere reporting it.
    _restrict(key_dir, _KEY_DIR_MODE)
    _restrict(private_key_path, _PRIVATE_KEY_MODE)

    jwk = _public_jwk(private_key)
    kid = jwk["kid"]
    # Rewritten on every call even when the key was loaded rather than generated.
    # The document is derived state, it costs nothing to re-render, and the
    # alternative is a directory holding a key whose published half was deleted
    # by hand and never comes back without deleting the key too.
    _write_jwks(jwks_path, jwk)

    return DevKeypair(kid=kid, private_key_path=private_key_path, jwks_path=jwks_path)


def load_private_key(keypair: DevKeypair) -> rsa.RSAPrivateKey:
    """Read the private half of a keypair `ensure_keypair` already described.

    Exists so `config/local_dev/tokens.py` signs with the same material this
    module wrote without spelling the PEM's location a second time.

    Args:
        keypair: The keypair to read, as returned by `ensure_keypair`.

    Returns:
        The private key.

    Raises:
        ImproperlyConfigured: The file does not hold an RSA private key.

    """
    return _read_private_key(keypair.private_key_path)


def _read_private_key(path: Path) -> rsa.RSAPrivateKey:
    """Load an unencrypted PEM private key and insist it is RSA.

    Args:
        path: The PEM to read.

    Returns:
        The private key.

    Raises:
        ImproperlyConfigured: The file does not parse, is passphrase-encrypted, or
            parses as some other key type. Refused rather than carried, because
            everything downstream signs `RS256` and an EC key here would surface
            as a `TypeError` inside PyJWT with nothing naming the file that caused
            it.

    """
    try:
        private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    # A truncated or half-written PEM raises a bare `ValueError`, and a
    # passphrase-encrypted one a bare `TypeError`. Neither carries the path, so
    # left uncaught they reach the developer as `ValueError: Could not
    # deserialize key data` with no way to tell which file to delete -- and the
    # remedy is always the same one sentence, so say it.
    except (ValueError, TypeError) as unusable:
        message = f"{path} is not a readable unencrypted PEM private key; delete it and let it be generated again"
        raise ImproperlyConfigured(message) from unusable
    if not isinstance(private_key, rsa.RSAPrivateKey):
        message = f"{path} does not hold an RSA private key; delete it and let it be generated again"
        raise ImproperlyConfigured(message)
    return private_key


def _write_private_key(path: Path, private_key: rsa.RSAPrivateKey) -> None:
    """Write a private key as unencrypted PKCS#8 PEM, readable only by its owner.

    The mode is set on the descriptor rather than with a `chmod` after the fact:
    between a default-mode `write_bytes` and a following `chmod` there is a window
    in which the key is world-readable, and a window is all a secret needs.

    Args:
        path: Where to write it.
        private_key: The key to write.

    """
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PRIVATE_KEY_MODE)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)


def _restrict(path: Path, mode: int) -> None:
    """Bring an existing path back to the mode this module requires.

    POSIX only, and silently a no-op elsewhere: Windows has no permission bits for
    `chmod` to set, so calling it there would toggle the read-only flag -- making
    the *private key file* read-only, which is not the protection asked for and
    would break the next regeneration.

    Args:
        path: The directory or file to restrict.
        mode: The mode it must carry.

    """
    if os.name != "posix":
        return
    path.chmod(mode)


def _write_jwks(path: Path, jwk: dict[str, Any]) -> None:
    """Publish the single-key JWK Set, replacing any previous document atomically.

    Written to a sibling temporary file and moved into place rather than truncated
    and rewritten. A dev server reading the document during a plain `write_text`
    sees an empty file, `json.loads` fails, and `JWKSKeyStore._refresh` records a
    *failed* fetch -- which stamps the rate-limit clock, so the next sixty seconds
    of Bearer requests are refused with `refetch refused by the rate limit` long
    after the file is intact again. `os.replace` is atomic on POSIX and on
    Windows, so a reader sees either the old document or the new one.

    Args:
        path: Where the document must end up.
        jwk: The public JWK to publish.

    """
    document = json.dumps({"keys": [jwk]}, indent=2, sort_keys=True) + "\n"
    # A sibling rather than the system temp directory: `os.replace` is only atomic
    # within one filesystem, and `/tmp` is routinely a different one.
    staged = path.with_name(f"{path.name}.tmp")
    staged.write_text(document, encoding="utf-8")
    staged.replace(path)


def _public_jwk(private_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    """Render the public half as the JWK an IdP would publish.

    Args:
        private_key: The keypair whose public half to render.

    Returns:
        The JWK with `kid`, `alg` and `use` filled in -- the shape
        `tests/jwt_keys.py` produces and `jwt.PyJWKSet.from_dict` consumes. Only
        the public half is rendered: a JWK Set carrying private material would be
        a document no IdP serves and a secret in a file nothing protects.

    """
    rendered: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    return {**rendered, "kid": _thumbprint(rendered), "alg": SIGNING_ALGORITHM, "use": "sig"}


def _thumbprint(jwk: dict[str, Any]) -> str:
    """Compute the RFC 7638 SHA-256 thumbprint of an RSA public JWK.

    Args:
        jwk: The rendered public JWK. Only `e`, `kty` and `n` are read; anything
            else the rendering carried is excluded by the RFC.

    Returns:
        The thumbprint, base64url-encoded without padding, which is how a `kid`
        is written into a JWT header.

    """
    canonical = json.dumps({member: jwk[member] for member in _THUMBPRINT_MEMBERS}, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
