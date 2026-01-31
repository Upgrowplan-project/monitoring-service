from pydantic_settings import BaseSettings
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
    
    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/monitoring"
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Alerting
    ADMIN_EMAIL: Optional[str] = None
    
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
    
    # Пороги для алертов
    RESPONSE_TIME_WARNING_THRESHOLD: float = 2.0  # секунды
    RESPONSE_TIME_CRITICAL_THRESHOLD: float = 5.0  # секунды
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Singleton instance
_config = None

def get_config() -> MonitoringConfig:
    global _config
    if _config is None:
        _config = MonitoringConfig()
    return _config
