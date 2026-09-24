import secrets


def new_id() -> str:
    """A random 32-character hex identifier (16 random bytes), like the Go idgen.New."""
    return secrets.token_hex(16)
