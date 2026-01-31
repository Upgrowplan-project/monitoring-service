"""
Upgrowplan Monitoring System

Модуль для мониторинга здоровья всех сервисов системы Upgrowplan
"""

from .config import get_config, MonitoringConfig
from .database import get_db, get_db_session, init_db
from .models import ServiceHealth, UserActivity, SystemAlert, APIUsageMetrics, Email, EmailAttachment
from .health_checkers import HealthChecker, check_all_services
from .alerting import AlertManager
from .tasks import celery_app

__version__ = "1.0.0"

__all__ = [
    "get_config",
    "MonitoringConfig",
    "get_db",
    "get_db_session",
    "init_db",
    "ServiceHealth",
    "UserActivity",
    "SystemAlert",
    "APIUsageMetrics",
    "Email",
    "EmailAttachment",
    "HealthChecker",
    "check_all_services",
    "AlertManager",
    "celery_app",
]
