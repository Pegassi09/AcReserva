import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from .config import Settings


def hash_password(password: str, iterations: int = 310_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, raw_iterations, salt, stored_digest = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(raw_iterations)
        ).hex()
        return hmac.compare_digest(digest, stored_digest)
    except (AttributeError, ValueError):
        return False


def create_token(user_id: str, roles: list[str]) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "roles": roles, "iat": now, "exp": now + timedelta(hours=8)},
        Settings.jwt_secret,
        algorithm="HS256",
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, Settings.jwt_secret, algorithms=["HS256"])
