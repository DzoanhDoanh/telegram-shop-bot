import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request

from app.config import settings
from app.web.auth import get_admin_actor, is_authenticated


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _write_event(event: dict[str, Any]) -> None:
    try:
        path = Path(settings.AUDIT_LOG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def write_audit_event(request: Request, action: str, **details: Any) -> None:
    event = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "ip": client_ip(request),
        "actor": get_admin_actor(request) if is_authenticated(request) else "anonymous",
        "action": action,
        "details": details,
    }
    _write_event(event)


def write_bot_admin_audit(actor_id: int, action: str, **details: Any) -> None:
    event = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "ip": "telegram",
        "actor": f"telegram_admin:{actor_id}",
        "action": action,
        "details": details,
    }
    _write_event(event)
