from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List, Dict, Optional


class MonitoringConfig(BaseSettings):
    """Конфигурация системы мониторинга"""

    # Vercel
    VERCEL_TOKEN: Optional[str] = None
    VERCEL_PROJECT_ID: Optional[str] = None

    # Heroku
    HEROKU_API_KEY: Optional[str] = None
    HEROKU_APP_NAMES: List[str] = []  # ["app1", "app2", "app3"]

    # OpenAI
    OPENAI_API_KEY: Optional[str] = None

    # Другие API ключи для проверки
    OTHER_API_KEYS: Dict[str, str] = {}  # {"service_name": "api_key"}

    # -------------------------------------------------------------------------
    # Бэкенд-сервисы для HTTP health-проверки (пинг {url}{health_path}).
    # JSON-список: [{"name": "Market Research", "url": "https://...", "health_path": "/health"}]
    # health_path опционален (по умолчанию "/health").
    # -------------------------------------------------------------------------
    MONITORED_SERVICES: List[Dict[str, str]] = []

    # API-ключи внешних сервисов.
    # Apify — есть бесплатный эндпоинт баланса/лимитов (проверяем активно + сумма).
    APIFY_API_TOKEN: Optional[str] = None
    # Serper / Google CSE — активная проверка сожгла бы платную квоту, поэтому
    # показываем только индикатор "настроен" (presence), без активных вызовов.
    SERPER_API_KEY: Optional[str] = None
    GOOGLE_CSE_API_KEY: Optional[str] = None

    # user-service: агрегаты регистраций через токен-защищённый /api/stats/public.
    USER_SERVICE_URL: Optional[str] = None
    USER_SERVICE_STATS_TOKEN: Optional[str] = None

    # Авторизация API: общий с user-service секрет JWT (HS512) — проверка admin-роли.
    # Если не задан — авторизация выключена (dev). В проде обязателен.
    JWT_SECRET: Optional[str] = None
    # Токен для server-to-server ingest (market-research-service → /reports, /synthesis-logs).
    MONITORING_INGEST_TOKEN: Optional[str] = None

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/monitoring"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_postgres_scheme(cls, v: str) -> str:
        # Heroku выдаёт postgres://, а SQLAlchemy 2.0+ требует postgresql://
        if v and v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        return v

    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Alerting
    ADMIN_EMAIL: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None  # отображаемый From-адрес (info@upgrowplan.com)
    BREVO_API_KEY: Optional[str] = None    # REST API key (xkeysib-...), отдельно от SMTP key
    
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    
    # Frontend URL (для CORS)
    FRONTEND_URL: str = "http://localhost:3000"
    
    # IMAP/POP/SMTP настройки для почты (Zoho)
    IMAP_HOST: Optional[str] = None
    IMAP_PORT: Optional[int] = 993
    IMAP_USER: Optional[str] = None
    IMAP_PASSWORD: Optional[str] = None
    IMAP_SSL: bool = True
    IMAP_FOLDER: str = "INBOX"
    IMAP_POLL_INTERVAL_SECONDS: int = 60  # как часто опрашивать папку

    POP_HOST: Optional[str] = None
    POP_PORT: Optional[int] = 995
    POP_USER: Optional[str] = None
    POP_PASSWORD: Optional[str] = None
    POP_SSL: bool = True

    # SMTP для отправки писем
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: Optional[int] = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None

    # Общий App Password (если вы используете один пароль для IMAP/SMTP)
    MAIL_APP_PASSWORD: Optional[str] = None
    
    # Redis мониторинг (market-research-service)
    MARKET_RESEARCH_REDIS_URL: Optional[str] = None
    REDIS_PLAN_LIMIT_MB: float = 27.0          # лимит плана Redis Cloud в MB
    REDIS_MEMORY_WARNING_THRESHOLD: float = 70.0   # % → degraded
    REDIS_MEMORY_CLEANUP_THRESHOLD: float = 80.0   # % → авто-очистка research:* ключей

    # Пороги для алертов
    RESPONSE_TIME_WARNING_THRESHOLD: float = 2.0  # секунды
    RESPONSE_TIME_CRITICAL_THRESHOLD: float = 5.0  # секунды

    # -------------------------------------------------------------------------
    # Visibility Monitor V1 — реальные метрики поиска (GSC + Bing Webmaster).
    # Без ключей задачи просто пропускаются (graceful skip). Интервал скана
    # читается из env VISIBILITY_SCAN_INTERVAL_SECONDS (по умолчанию 4ч ≈ 6×/день).
    # -------------------------------------------------------------------------
    VISIBILITY_SITE_URL: str = "https://www.upgrowplan.com/"
    VISIBILITY_LOOKBACK_DAYS: int = 30

    # Google Search Console. Два способа (приоритет у service-account):
    #  1) Service-account: GSC_SERVICE_ACCOUNT_JSON (инлайн-JSON для прода/Heroku)
    #     или GSC_SERVICE_ACCOUNT_FILE (путь к .json для локали). Email SA должен
    #     быть добавлен пользователем в свойство GSC.
    #  2) OAuth refresh-token: GSC_CLIENT_ID/SECRET/REFRESH_TOKEN.
    GSC_SERVICE_ACCOUNT_JSON: Optional[str] = None
    GSC_SERVICE_ACCOUNT_FILE: Optional[str] = None
    GSC_CLIENT_ID: Optional[str] = None
    GSC_CLIENT_SECRET: Optional[str] = None
    GSC_REFRESH_TOKEN: Optional[str] = None

    # Bing Webmaster Tools (apikey из кабинета)
    BING_WEBMASTER_API_KEY: Optional[str] = None
    BING_SITE_URL: Optional[str] = None  # по умолчанию = VISIBILITY_SITE_URL

    # GEO Visibility — проверка упоминаний бренда в ответах нейросетей
    GEMINI_API_KEY: Optional[str] = None
    GEO_BRAND: str = "upgrowplan"
    GEO_SCAN_INTERVAL_SECONDS: int = 48 * 3600  # раз в 2 дня
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        # Игнорировать env-переменные, не объявленные в модели (их читают другие
        # модули через os.getenv: ENABLE_INPROCESS_SCHEDULER, *_INTERVAL_SECONDS и т.п.).
        # Без этого pydantic падает на "extra inputs" и роняет старт всего сервиса.
        extra = "ignore"


# Singleton instance
_config = None

def get_config() -> MonitoringConfig:
    global _config
    if _config is None:
        _config = MonitoringConfig()
    return _config
