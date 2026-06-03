# Deployment Checklist

## Pre-deployment Security

- [ ] **Generate strong SESSION_SECRET**: Use 32+ random characters (e.g., `openssl rand -base64 32`)
- [ ] **Enable secure cookies**: Set `SESSION_COOKIE_SECURE=true` when running behind HTTPS
- [ ] **Reverse proxy setup**: Put web admin behind reverse proxy (nginx/Caddy) or firewall
- [ ] **Rotate bot token**: If `BOT_TOKEN` was leaked, regenerate via @BotFather and update `.env`

## Backup Strategy

- [ ] **Postgres volume**: Schedule regular backups of Docker volume or database directory
- [ ] **Audit logs**: Backup `logs/admin_audit.jsonl` regularly (contains admin action history)

## Post-deployment Verification

- [ ] **CSV exports work**: Test `/admin/export/orders.csv`, `/admin/export/products.csv`, `/admin/export/inventory.csv`
- [ ] **Login rate limit**: Attempt 5+ failed logins from same IP, verify 6th attempt is blocked
- [ ] **CSRF protection**: Try POST to admin route without `csrf_token` field, verify rejection/redirect

## Production Environment Variables

Ensure these are set in production `.env`:

```bash
SESSION_SECRET=<32+ random chars>
SESSION_COOKIE_SECURE=true
LOGIN_RATE_LIMIT_ATTEMPTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=300
AUDIT_LOG_PATH=logs/admin_audit.jsonl
```

## Notes

- In-memory rate limit resets on restart (single-process only)
- Audit logs are append-only JSONL files
- CSRF tokens expire with session max age (24h default)
