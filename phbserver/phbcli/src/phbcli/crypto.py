"""Desktop master-key persistence helpers."""

from __future__ import annotations

from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from phb_commons.keys import (
    generate_private_key,
    load_private_key_pem,
    private_key_to_pem,
)

MASTER_KEY_FILE = "master_key.pem"

__all__ = [
    "MASTER_KEY_FILE",
    "load_or_create_master_key",
]

def load_or_create_master_key(app_dir: Path, filename: str = MASTER_KEY_FILE) -> Ed25519PrivateKey:
    """Load existing desktop master key or create one if absent."""
    app_dir.mkdir(parents=True, exist_ok=True)
    key_path = app_dir / filename
    if key_path.exists():
        return load_private_key_pem(key_path.read_bytes())

    private_key = generate_private_key()
    key_path.write_bytes(private_key_to_pem(private_key))
    try:
        key_path.chmod(0o600)
    except OSError:
        # Windows doesn't fully support POSIX perms via chmod.
        pass
    return private_key
