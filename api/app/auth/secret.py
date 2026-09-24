import os
import secrets

from ..storage import write_file_atomic

SECRET_LEN = 32


def load_or_create_secret(data_dir: str) -> bytes:
    """Read the HMAC signing secret from <data_dir>/secret.key, generating and
    persisting a new random one on first run (or if the file is the wrong
    length) so tokens remain valid across restarts."""
    path = os.path.join(data_dir, "secret.key")
    try:
        with open(path, "rb") as f:
            existing = f.read()
        if len(existing) == SECRET_LEN:
            return existing
    except FileNotFoundError:
        pass

    secret = secrets.token_bytes(SECRET_LEN)
    write_file_atomic(path, secret)
    return secret
