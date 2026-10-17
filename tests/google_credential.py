import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_credential(client_id: str) -> str:
    """A well-formed, plausible-looking Google ID token (RS256, Google issuer,
    the given audience, not expired). The signature belongs to a throwaway key,
    so only tests that mock the verification call can accept it."""
    return jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": client_id,
            "sub": "google-subject",
            "exp": int(time.time()) + 600,
        },
        _KEY,
        algorithm="RS256",
    )


def google_credential_key() -> rsa.RSAPrivateKey:
    """The throwaway signing key, for tests that need a token with other
    claims than google_credential() sets."""
    return _KEY
