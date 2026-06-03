# Telegram Shop Web Admin Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the web admin for safer operation by adding CSRF checks, login rate limiting, audit logging, CSV exports, and production/deploy notes.

**Architecture:** Keep the current FastAPI/Jinja app. Avoid database migrations in this phase by using signed CSRF tokens, in-memory login throttling, and append-only file audit logs under `logs/`. Add CSV export routes using existing SQLAlchemy models.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLAlchemy async, aiogram, CSV stdlib, HMAC stdlib.

---

## Files and responsibilities

- Modify `app/config.py`: add `LOGIN_RATE_LIMIT_ATTEMPTS`, `LOGIN_RATE_LIMIT_WINDOW_SECONDS`, `AUDIT_LOG_PATH`.
- Modify `.env.example`: document Phase 3 config.
- Modify `app/web/auth.py`: add CSRF token generation/validation helpers.
- Create `app/web/audit.py`: append JSONL audit events.
- Modify `app/web/main.py`: enforce CSRF on POST routes, login rate limit, audit key admin actions, add CSV export routes.
- Modify `app/web/templates/base.html`: add export links in sidebar.
- Modify `app/web/templates/products.html`, `orders.html`, `inventory.html`: include hidden CSRF token in all POST forms.
- Create `docs/deploy-checklist.md`: concise deploy/backup checklist.

## Phase 3 scope

Included:
- CSRF protection for all web admin POST routes.
- Login rate limit per client IP in memory.
- Audit JSONL for login/logout/product/inventory/order actions.
- CSV export routes for orders, products, inventory summary.
- Deployment/backup notes.

Not included:
- Multi-admin roles.
- Database-backed audit table.
- Persistent distributed rate limit.
- Full test suite.
- Commit unless user explicitly asks.

---

### Task 1: Config, CSRF helpers, audit helper

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `app/web/auth.py`
- Create: `app/web/audit.py`

- [ ] Add config values:

```python
LOGIN_RATE_LIMIT_ATTEMPTS = config('LOGIN_RATE_LIMIT_ATTEMPTS', default=5, cast=int)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = config('LOGIN_RATE_LIMIT_WINDOW_SECONDS', default=300, cast=int)
AUDIT_LOG_PATH = config('AUDIT_LOG_PATH', default='logs/admin_audit.jsonl')
```

- [ ] Add `.env.example` values below web config:

```text
LOGIN_RATE_LIMIT_ATTEMPTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=300
AUDIT_LOG_PATH=logs/admin_audit.jsonl
```

- [ ] Add CSRF helpers to `app/web/auth.py`:

```python
def create_csrf_token(request: Request) -> str:
    session_token = request.cookies.get(SESSION_COOKIE_NAME, '')
    issued_at = str(int(time.time()))
    payload = f"{session_token}:{issued_at}"
    return f"{issued_at}.{_signature(payload)}"


def validate_csrf_token(request: Request, token: str) -> bool:
    session_token = request.cookies.get(SESSION_COOKIE_NAME, '')
    if not session_token or not token or '.' not in token:
        return False
    issued_at, received_signature = token.split('.', 1)
    if not issued_at.isdigit():
        return False
    age = int(time.time()) - int(issued_at)
    if age < 0 or age > SESSION_MAX_AGE_SECONDS:
        return False
    payload = f"{session_token}:{issued_at}"
    expected_signature = _signature(payload)
    return hmac.compare_digest(received_signature, expected_signature)
```

- [ ] Create `app/web/audit.py`:

```python
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request

from app.config import settings


def client_ip(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host if request.client else 'unknown'


def write_audit_event(request: Request, action: str, **details: Any) -> None:
    path = Path(settings.AUDIT_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        'ts': datetime.utcnow().isoformat() + 'Z',
        'ip': client_ip(request),
        'action': action,
        'details': details,
    }
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')
```

- [ ] Verify:

```bash
python -m compileall app/config.py app/web/auth.py app/web/audit.py
```

### Task 2: CSRF enforcement and template tokens

**Files:**
- Modify: `app/web/main.py`
- Modify: `app/web/templates/products.html`
- Modify: `app/web/templates/orders.html`
- Modify: `app/web/templates/inventory.html`

- [ ] Import `create_csrf_token`, `validate_csrf_token` in `main.py`.
- [ ] Add helper:

```python
def _template_context(request: Request, **context):
    return {'csrf_token': create_csrf_token(request), **context}

async def _require_csrf(request: Request, csrf_token: str) -> bool:
    return is_authenticated(request) and validate_csrf_token(request, csrf_token)
```

- [ ] Wrap admin template contexts with `_template_context(request, ...)`.
- [ ] Add `csrf_token: str = Form(...)` to every authenticated POST route:
  - `/admin/orders/{order_id}/approve`
  - `/admin/orders/{order_id}/reject`
  - `/admin/products/add`
  - `/admin/products/{product_id}/edit`
  - `/admin/products/{product_id}/disable`
  - `/admin/inventory/add`
- [ ] At start of each POST route after auth, reject invalid token:

```python
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)
```

- [ ] Add hidden token to every POST form in templates:

```html
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
```

- [ ] Verify:

```bash
python -m compileall app/web/main.py
```

### Task 3: Login rate limit and audit events

**Files:**
- Modify: `app/web/main.py`

- [ ] Add imports: `time`, `write_audit_event`, `client_ip`.
- [ ] Add module-level dict:

```python
_login_failures: dict[str, list[float]] = {}
```

- [ ] Add helper:

```python
def _login_limited(ip: str) -> bool:
    now = time.time()
    window_start = now - settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    failures = [ts for ts in _login_failures.get(ip, []) if ts >= window_start]
    _login_failures[ip] = failures
    return len(failures) >= settings.LOGIN_RATE_LIMIT_ATTEMPTS


def _record_login_failure(ip: str) -> None:
    _login_failures.setdefault(ip, []).append(time.time())
```

- [ ] In `post_login`, block if limited, audit failed/success login, clear failures on success.
- [ ] Audit logout.
- [ ] Audit product add/edit/disable, inventory import, order approve/reject.
- [ ] Verify:

```bash
python -m compileall app/web/main.py
```

### Task 4: CSV export routes and nav links

**Files:**
- Modify: `app/web/main.py`
- Modify: `app/web/templates/base.html`

- [ ] Add imports:

```python
import csv
from io import StringIO
from fastapi.responses import StreamingResponse
```

- [ ] Add helper:

```python
def _csv_response(filename: str, rows: list[dict[str, object]]) -> StreamingResponse:
    buffer = StringIO()
    fieldnames = list(rows[0].keys()) if rows else ['empty']
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows or [{'empty': ''}])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
```

- [ ] Add authenticated GET routes:
  - `/admin/export/orders.csv`
  - `/admin/export/products.csv`
  - `/admin/export/inventory.csv`
- [ ] Export orders with id/user_id/product/status/quantity/total/created/completed.
- [ ] Export products with id/category/name/price/stock/is_active/created.
- [ ] Export inventory summary with product_id/product_name/available/sold/total.
- [ ] Add sidebar links in `base.html` under navigation.
- [ ] Verify:

```bash
python -m compileall app/web/main.py
```

### Task 5: Deploy checklist and final verification

**Files:**
- Create: `docs/deploy-checklist.md`

- [ ] Create checklist covering:
  - generate strong `SESSION_SECRET`
  - set `SESSION_COOKIE_SECURE=true` behind HTTPS
  - put web behind reverse proxy / firewall
  - backup Postgres volume
  - backup audit log
  - rotate bot token if leaked
  - test export CSV
  - test login rate limit
  - test CSRF failure by POST without token

- [ ] Run:

```bash
python -m compileall app run.py
```

- [ ] Read lints for changed files.
- [ ] Verify no POST form lacks `csrf_token`.
- [ ] Verify export routes compile.

---

## Handoff notes

- In-memory rate limit resets on restart and is single-process only. This is acceptable for current bot deployment.
- File audit logs are append-only best-effort. If DB-backed audit is needed later, create migration in future phase.
- CSRF tokens are bound to signed session cookie and expire with session max age.
