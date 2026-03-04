"""Ed25519 key helpers shared across PHB services."""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

from .encoding import b64_decode, b64_encode


def generate_private_key() -> Ed25519PrivateKey:
    """Generate a new Ed25519 private key."""
    return Ed25519PrivateKey.generate()


def public_key_to_b64(public_key: Ed25519PublicKey) -> str:
    """Encode an Ed25519 public key in base64 raw form."""
    raw = public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    return b64_encode(raw)


def load_public_key_b64(public_key_b64: str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from base64 raw bytes."""
    raw = b64_decode(public_key_b64)
    if len(raw) != 32:
        raise ValueError("Ed25519 public key must be exactly 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def private_key_to_pem(private_key: Ed25519PrivateKey) -> bytes:
    """Serialize a private key to unencrypted PKCS8 PEM."""
    return private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )


def load_private_key_pem(pem: bytes) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from unencrypted PKCS8 PEM bytes."""
    key = load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("Expected an Ed25519 private key")
    return key


def load_public_key_pem(pem: bytes) -> Ed25519PublicKey:
    """Load an Ed25519 public key from PEM bytes."""
    key = load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("Expected an Ed25519 public key")
    return key
