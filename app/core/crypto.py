"""Device identity, key exchange, and encrypted channel primitives."""
import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings

_s = get_settings()


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


@dataclass
class Ed25519KeyPair:
    private: Ed25519PrivateKey
    public_bytes: bytes

    def sign(self, message: bytes) -> bytes:
        return self.private.sign(message)

    @property
    def public_b64(self) -> str:
        return b64e(self.public_bytes)


def generate_ed25519() -> Ed25519KeyPair:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return Ed25519KeyPair(private=priv, public_bytes=pub)


def ed25519_verify(public_b64: str, message: bytes, signature: bytes) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(b64d(public_b64))
        pub.verify(signature, message)
        return True
    except Exception:
        return False


def _hkdf(shared: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=info,
    ).derive(shared)


def derive_shared_key(
    private_key_bytes: bytes, peer_public_b64: str, *, context: str,
) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(private_key_bytes)
    peer_pub = X25519PublicKey.from_public_bytes(b64d(peer_public_b64))
    shared = priv.exchange(peer_pub)
    return _hkdf(shared, context.encode())


def generate_x25519() -> tuple[bytes, str]:
    priv = X25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv_bytes, b64e(pub_bytes)


def aes_gcm_encrypt(key: bytes, plaintext: bytes, *, aad: bytes = b"") -> str:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return b64e(nonce + ct)


def aes_gcm_decrypt(key: bytes, b64: str, *, aad: bytes = b"") -> bytes:
    raw = b64d(b64)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, aad)


# ---- Server X25519 keypair ------------------------------------------------
# In production, load from the persisted SystemKey table (see device_mesh
# bootstrap). If a persisted key is set via set_server_x25519_private(),
# it takes precedence over the derived-from-secret fallback.
_server_x25519_priv: bytes | None = None


def set_server_x25519_private(priv: bytes) -> None:
    """Install a persisted server X25519 private key. Called at startup after
    loading from DB. This is what allows rotation of SECRET_KEY without
    invalidating existing device channels."""
    global _server_x25519_priv
    if len(priv) != 32:
        raise ValueError("x25519 private must be 32 bytes")
    _server_x25519_priv = priv


def get_server_x25519_private() -> bytes:
    global _server_x25519_priv
    if _server_x25519_priv is None:
        seed = hashlib.sha256(_s.secret_key.encode() + b"x25519").digest()
        _server_x25519_priv = seed
    return _server_x25519_priv


def get_server_x25519_public_b64() -> str:
    priv = X25519PrivateKey.from_private_bytes(get_server_x25519_private())
    return b64e(priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))


def derive_device_channel_key(
    user_id: str, device_id: str, device_x25519_pub_b64: str,
) -> bytes:
    return derive_shared_key(
        get_server_x25519_private(),
        device_x25519_pub_b64,
        context=f"user:{user_id}:device:{device_id}",
    )
