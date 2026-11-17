"""Password hashing (stdlib scrypt) and JWT helpers."""
import base64
import hashlib
import hmac
import os
import time
import uuid

import jwt

ALGORITHM = "HS256"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    actual = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return hmac.compare_digest(actual, expected)


def create_token(secret: str, user_id: uuid.UUID, tenant_id: uuid.UUID | None, role: str,
                 expires_minutes: int, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id) if tenant_id else None,
        "role": role,
        "iat": issued,
        "exp": issued + expires_minutes * 60,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_token(secret: str, token: str) -> dict:
    """Raises jwt.PyJWTError for expired, tampered, or malformed tokens."""
    return jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
