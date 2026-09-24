# 0002. PBKDF2-HMAC-SHA512 via `hashlib`, with the Go backend's exact parameters

*Replaces todo-app's 0002 ("Hand-rolled PBKDF2-HMAC-SHA512, no external crypto package").*

## Context
The spec calls for PBKDF2-SHA512 password hashing with 100k iterations. In the Go backend, PBKDF2 had to be implemented by hand from RFC 8018, because Go's standard library doesn't include it (only the external `golang.org/x/crypto` module does). Python's standard library does: `hashlib.pbkdf2_hmac`, backed by OpenSSL.

The Python API also has to stay **data-compatible** with the Go backend (decisions/0014). A `users.json` written by either backend must verify passwords in the other.

## Decision
`api/app/auth/passwords.py` uses `hashlib.pbkdf2_hmac("sha512", password, salt, 100_000, dklen=64)` with a 16-byte salt from `secrets.token_bytes`. These are the same algorithm, iteration count, key length and salt length as the Go `HashPassword`. `verify_password` compares digests with `hmac.compare_digest`, which runs in constant time. Hashes and salts are stored as standard base64, the way Go's `encoding/json` marshals `[]byte`.

`tests/test_passwords.py` runs the same known-answer vectors as the Go test suite, and asserts the parameters directly, so a change to either would fail the tests.

## Alternatives considered
- **Hand-rolling PBKDF2 as in Go:** pointless when the stdlib has an audited, faster (C/OpenSSL) implementation.
- **`passlib` / `argon2-cffi` / bcrypt:** a stronger or more fashionable KDF would break password compatibility with the Go backend and existing data, and the spec names PBKDF2-SHA512.

## Consequences
- No project-owned crypto primitive to maintain.
- Password hashes are interchangeable with todo-app (Go): verified by logging into Go-created accounts from Python and vice versa.
- `hashlib.pbkdf2_hmac` releases the GIL while it runs, so a login (~100 ms of CPU) doesn't block other requests in FastAPI's threadpool.
