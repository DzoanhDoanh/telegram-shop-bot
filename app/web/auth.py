import hmac
import time
from hashlib import sha256

from fastapi import Request
from fastapi.responses import Response

from app.config import settings

SESSION_COOKIE_NAME = "admin_session"
SESSION_MAX_AGE_SECONDS = 86400 * 7


def _signature(payload: str) -> str:
    return hmac.new(
        settings.SESSION_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        sha256,
    ).hexdigest()


def create_session_token(actor: str) -> str:
    issued_at = str(int(time.time()))
    safe_actor = actor.replace("|", "_") or "admin"
    payload = f"{issued_at}|{safe_actor}"
    signature = _signature(payload)
    return f"{issued_at}|{safe_actor}.{signature}"


def create_csrf_token(request: Request) -> str:
    session_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    issued_at = str(int(time.time()))
    payload = f"{session_token}:{issued_at}"
    return f"{issued_at}.{_signature(payload)}"


def validate_csrf_token(request: Request, token: str) -> bool:
    session_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not session_token or not token or "." not in token:
        return False

    issued_at, received_signature = token.split(".", 1)
    if not issued_at.isdigit():
        return False

    age = int(time.time()) - int(issued_at)
    if age < 0 or age > SESSION_MAX_AGE_SECONDS:
        return False

    payload = f"{session_token}:{issued_at}"
    expected_signature = _signature(payload)
    return hmac.compare_digest(received_signature, expected_signature)


def _parse_session_token(token: str) -> tuple[str, str, str] | None:
    if not token or "." not in token or "|" not in token:
        return None
    payload, received_signature = token.rsplit(".", 1)
    issued_at, actor = payload.split("|", 1)
    if not issued_at.isdigit() or not actor:
        return None
    return issued_at, actor, received_signature



def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    parsed = _parse_session_token(token or "")
    if not parsed:
        return False

    issued_at, actor, received_signature = parsed
    expected_signature = _signature(f"{issued_at}|{actor}")
    if not hmac.compare_digest(received_signature, expected_signature):
        return False

    age = int(time.time()) - int(issued_at)
    return 0 <= age <= SESSION_MAX_AGE_SECONDS



def get_admin_actor(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    parsed = _parse_session_token(token or "")
    if not parsed:
        return "admin"
    _, actor, _ = parsed
    return actor



def set_admin_session(response: Response, actor: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(actor),
        httponly=True,
        max_age=SESSION_MAX_AGE_SECONDS,
        samesite="lax",
        secure=settings.SESSION_COOKIE_SECURE,
    )


def clear_admin_session(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        samesite="lax",
        secure=settings.SESSION_COOKIE_SECURE,
    )
