from decouple import config


class Settings:
    BOT_TOKEN = config('BOT_TOKEN', default='')
    ADMIN_IDS = [int(id.strip()) for id in config('ADMIN_IDS', default='').split(',') if id.strip()]
    ADMIN_PASSWORD = config('ADMIN_PASSWORD', default='admin_secret')
    SESSION_SECRET = config('SESSION_SECRET', default='change_me_session_secret')
    SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=False, cast=bool)
    WEB_HOST = config('WEB_HOST', default='127.0.0.1')
    WEB_PORT = config('WEB_PORT', default=8000, cast=int)
    LOGIN_RATE_LIMIT_ATTEMPTS = config('LOGIN_RATE_LIMIT_ATTEMPTS', default=5, cast=int)
    LOGIN_RATE_LIMIT_WINDOW_SECONDS = config('LOGIN_RATE_LIMIT_WINDOW_SECONDS', default=300, cast=int)
    AUDIT_LOG_PATH = config('AUDIT_LOG_PATH', default='logs/admin_audit.jsonl')

    DATABASE_URL = config('DATABASE_URL', default='postgresql+asyncpg://shopbot:shopbot_secret@localhost:5432/shopbot')
    REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/0')

    BANK_NAME = config('BANK_NAME', default='Vietcombank')
    BANK_ACCOUNT_NO = config('BANK_ACCOUNT_NO', default='')
    BANK_ACCOUNT_NAME = config('BANK_ACCOUNT_NAME', default='')
    VIETQR_URL = config('VIETQR_URL', default='')

    SHOP_NAME = config('SHOP_NAME', default='Digital Shop')
    SHOP_SUPPORT_USERNAME = config('SHOP_SUPPORT_USERNAME', default='')

    BANK_WEBHOOK_SECRET = config('BANK_WEBHOOK_SECRET', default='')
    PAYMENT_ADMIN_PIN = config('PAYMENT_ADMIN_PIN', default='')
    APP_ENV = config('APP_ENV', default='development')

    def validate(self) -> None:
        is_production = self.APP_ENV.lower() in {'prod', 'production'}
        if self.ADMIN_PASSWORD == 'admin_secret':
            raise RuntimeError('ADMIN_PASSWORD must be changed from the default value.')
        if self.SESSION_SECRET == 'change_me_session_secret':
            raise RuntimeError('SESSION_SECRET must be changed from the default value.')
        if is_production and not self.PAYMENT_ADMIN_PIN:
            raise RuntimeError('PAYMENT_ADMIN_PIN is required in production.')


settings = Settings()
settings.validate()
