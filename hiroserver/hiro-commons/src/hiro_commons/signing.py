"""Ed25519 signing helpers shared across Hiro services."""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .encoding import b64_decode, b64_encode


def sign_bytes(private_key: Ed25519PrivateKey, data: bytes) -> str:
    """Sign arbitrary bytes and return a base64 signature."""
    return b64_encode(private_key.sign(data))


def verify_signature(public_key: Ed25519PublicKey, data: bytes, signature_b64: str) -> bool:
    """Verify a base64 signature for arbitrary bytes."""
    try:
        signature = b64_decode(signature_b64)
        public_key.verify(signature, data)
    except Exception:
        return False
    return True


def sign_nonce(private_key: Ed25519PrivateKey, nonce_hex: str) -> str:
    """Sign a hex nonce value from the gateway challenge."""
    nonce_bytes = bytes.fromhex(nonce_hex)
    return sign_bytes(private_key, nonce_bytes)
