"""Admin logins. Owner: everything, including user management and settings.
Delegate: manage events and review results."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .db import AuditLog, User, get_session

ITERATIONS = 310_000


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, iters, salt, dk = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(test.hex(), dk)
    except Exception:
        return False


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if not user or not user.active:
        raise LoginRequired()
    request.state.user = user
    return user


def owner_required(user: User = Depends(current_user)) -> User:
    if user.role != "owner":
        raise Forbidden()
    return user


def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        request.session["csrf"] = tok
    return tok


async def check_csrf(request: Request) -> None:
    form = await request.form()
    if not hmac.compare_digest(str(form.get("csrf", "")), request.session.get("csrf", "")):
        raise Forbidden()


def audit(db: Session, user: User | None, action: str, target: str = "", detail: str = "") -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            user_name=user.name if user else "",
            action=action,
            target=target,
            detail=detail,
        )
    )
