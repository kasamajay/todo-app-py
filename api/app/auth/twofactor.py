import secrets


def generate_six_digit_code() -> str:
    """A zero-padded 6-digit code for a one-time two-factor login challenge,
    from the secrets module (a CSPRNG, not random) since it gates account access."""
    return f"{secrets.randbelow(1_000_000):06d}"
