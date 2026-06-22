"""
Identity and signing for Mesh Canary nodes.

Each node's identity IS its Ed25519 public key (hex-encoded) — there is no
central registry. This is the same self-certifying identity model used by
Tor and SSH: anyone can generate an identity, and anyone can verify a
signature against a claimed node_id without trusting whoever forwarded it.
"""
import os
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


def generate_keypair():
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def save_private_key(priv: Ed25519PrivateKey, path: str) -> None:
    data = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o600)


def load_private_key(path: str) -> Ed25519PrivateKey:
    with open(path, "rb") as f:
        data = f.read()
    return Ed25519PrivateKey.from_private_bytes(data)


def load_or_create_identity(path: str):
    """Returns (private_key, node_id_hex). Creates a new identity if path doesn't exist."""
    if os.path.exists(path):
        priv = load_private_key(path)
    else:
        priv, _ = generate_keypair()
        save_private_key(priv, path)
    pub = priv.public_key()
    return priv, public_key_hex(pub)


def public_key_hex(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return raw.hex()


def pubkey_from_hex(hexstr: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hexstr))


def sign(priv: Ed25519PrivateKey, message: bytes) -> str:
    return priv.sign(message).hex()


def verify(node_id_hex: str, message: bytes, sig_hex: str) -> bool:
    """Verify that `message` was signed by the holder of the private key
    matching node_id_hex (the node's public key, which IS its identity)."""
    try:
        pub = pubkey_from_hex(node_id_hex)
        pub.verify(bytes.fromhex(sig_hex), message)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False
