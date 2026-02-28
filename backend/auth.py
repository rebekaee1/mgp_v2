"""
JWT authentication for the Dashboard.
- Access token (short-lived) + Refresh token (long-lived)
- bcrypt password hashing
- @require_auth decorator that populates flask.g with current_user / company_id
"""

import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional

import bcrypt
import jwt
from flask import g, jsonify, request

from config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(payload: dict, expires_delta: timedelta) -> str:
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_access_token(user_id: uuid.UUID, company_id: uuid.UUID, role: str) -> str:
    return _create_token(
        {"sub": str(user_id), "cid": str(company_id), "role": role, "type": "access"},
        timedelta(minutes=settings.jwt_access_minutes),
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _create_token(
        {"sub": str(user_id), "type": "refresh"},
        timedelta(days=settings.jwt_refresh_days),
    )


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def require_auth(f):
    """Decorator: rejects request if no valid access token is present."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing authorization token"}), 401

        payload = decode_token(auth_header[7:])
        if payload is None or payload.get("type") != "access":
            return jsonify({"error": "Invalid or expired token"}), 401

        g.current_user_id = uuid.UUID(payload["sub"])
        g.company_id = uuid.UUID(payload["cid"])
        g.user_role = payload.get("role", "viewer")
        return f(*args, **kwargs)

    return decorated
