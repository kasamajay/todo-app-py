"""First-run seeding: the default admin account."""

import base64
import logging
import secrets

from .auth.passwords import hash_password
from .idgen import new_id
from .jsonfmt import now
from .models import User
from .storage import UserStore

log = logging.getLogger("todo-app")

ADMIN_EMAIL = "admin@todo.io"


def bootstrap_admin(users: UserStore) -> None:
    """Create admin@todo.io with a random password if no users exist yet,
    logging the plaintext exactly once (it is never stored or shown again)."""
    if users.list():
        return

    plaintext = base64.urlsafe_b64encode(secrets.token_bytes(18)).rstrip(b"=").decode("ascii")
    hash_, salt = hash_password(plaintext)
    admin = User(id=new_id(), email=ADMIN_EMAIL, password_hash=hash_, salt=salt, is_admin=True, created_at=now())
    users.put(admin.id, admin)

    log.info("=====================================================")
    log.info("Bootstrapped admin account (shown only once):")
    log.info("  email:    %s", ADMIN_EMAIL)
    log.info("  password: %s", plaintext)
    log.info("=====================================================")
