"""PBKDF2-HMAC-SHA512 password hashing with the exact parameters the Go API
uses, so password hashes are interchangeable between the two backends.

Unlike Go, Python's standard library ships PBKDF2 (hashlib.pbkdf2_hmac, backed
by OpenSSL), so there's nothing to hand-roll - see decisions/0002."""

import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 100_000
PBKDF2_KEY_LEN = 64  # SHA-512 output size
SALT_LEN = 16


def pbkdf2_key(password: bytes, salt: bytes, iterations: int, key_len: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha512", password, salt, iterations, dklen=key_len)


def hash_password(plaintext: str) -> tuple[bytes, bytes]:
    """Generate a random salt and derive a PBKDF2-HMAC-SHA512 hash of plaintext.
    Returns (hash, salt)."""
    salt = secrets.token_bytes(SALT_LEN)
    return pbkdf2_key(plaintext.encode("utf-8"), salt, PBKDF2_ITERATIONS, PBKDF2_KEY_LEN), salt


def verify_password(plaintext: str, hash: bytes | None, salt: bytes | None) -> bool:
    """Recompute the hash for plaintext with salt and compare in constant time."""
    computed = pbkdf2_key(plaintext.encode("utf-8"), salt or b"", PBKDF2_ITERATIONS, PBKDF2_KEY_LEN)
    return hmac.compare_digest(computed, hash or b"")
