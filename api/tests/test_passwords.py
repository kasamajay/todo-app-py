"""Ports of todo-app api/internal/auth/pbkdf2_test.go, plus the parameters
that make hashes interchangeable with the Go backend."""

import pytest

from app.auth.passwords import PBKDF2_ITERATIONS, PBKDF2_KEY_LEN, SALT_LEN, hash_password, pbkdf2_key, verify_password

# The same vectors the Go tests use (originally generated with hashlib).
KNOWN_VECTORS = [
    ("iterations=1", b"password", b"salt", 1, 64,
     "867f70cf1ade02cff3752599a3a53dc4af34c7a669815ae5d513554e1c8cf252c02d470a285a0501bad999bfe943c08f050235d7d68b1da55e63f73b60a57fce"),
    ("iterations=2", b"password", b"salt", 2, 64,
     "e1d9c16aa681708a45f5c7c4e215ceb66e011a2e9f0040713f18aefdb866d53cf76cab2868a39b9f7840edce4fef5a82be67335c77a6068e04112754f27ccf4e"),
    ("iterations=4096", b"password", b"salt", 4096, 64,
     "d197b1b33db0143e018b12f3d1d1479e6cdebdcc97c5c0f87f6902e072f457b5143f30602641b3d55cd335988cb36b84376060ecd532e039b742a239434af2d5"),
    ("long password and salt", b"passwordPASSWORDpassword", b"saltSALTsaltSALTsaltSALTsaltSALTsalt", 4096, 64,
     "8c0511f4c6e597c6ac6315d8f0362e225f3c501495ba23b868c005174dc4ee71115b59f9e60cd9532fa33e0f75aefe30225c583a186cd82bd4daea9724a3d3b8"),
    ("embedded null bytes", b"pass\x00word", b"sa\x00lt", 4096, 64,
     "9d9e9c4cd21fe4be24d5b8244c759665f39d98fc12a9ca759bb021db3cfadf345844aebe70dd8b2f6966f25f3613e1187bbd24ed2ca43ed13b246e4675be7ab9"),
]


@pytest.mark.parametrize("name,password,salt,iterations,key_len,want_hex", KNOWN_VECTORS, ids=[v[0] for v in KNOWN_VECTORS])
def test_pbkdf2_key_known_vectors(name, password, salt, iterations, key_len, want_hex):
    assert pbkdf2_key(password, salt, iterations, key_len).hex() == want_hex


def test_pbkdf2_key_deterministic_and_distinct():
    a = pbkdf2_key(b"pw", b"salt1", 1000, 64)
    assert a == pbkdf2_key(b"pw", b"salt1", 1000, 64)
    assert a != pbkdf2_key(b"pw", b"salt2", 1000, 64)


def test_pbkdf2_key_short_key_len():
    got = pbkdf2_key(b"password", b"salt", 1, 16)
    assert len(got) == 16
    assert got == pbkdf2_key(b"password", b"salt", 1, 64)[:16]


def test_hash_parameters_match_go_backend():
    assert (PBKDF2_ITERATIONS, PBKDF2_KEY_LEN, SALT_LEN) == (100_000, 64, 16)
    h, s = hash_password("correct horse")
    assert len(h) == 64 and len(s) == 16
    assert verify_password("correct horse", h, s)
    assert not verify_password("wrong horse", h, s)
