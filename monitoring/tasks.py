from celery import Celery
from celery.schedules import crontab
from datetime import datetime
import logging
from .config import get_config
from .database import get_db_session
from .models import ServiceHealth, SystemAlert, UserActivity, GeoCheck
from .health_checkers import check_all_services
from .alerting import AlertManager

logger = logging.getLogger(__name__)

# Инициализация Celery
config = get_config()
celery_app = Celery(
    'monitoring',
    broker=config.REDIS_URL,
    backend=config.REDIS_URL
)

# Конфигурация Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)


@celery_app.task(name='monitoring.check_all_services')
def check_all_services_task():
    """
    Периодическая проверка всех сервисов
    Запускается каждые 5 минут
    """
    import asyncio
    
    try:
        logger.info("Starting service health checks...")
        
        # Запускаем async функцию
        results = asyncio.run(check_all_services(config))
        
        alert_manager = AlertManager()
        
        # Сохраняем результаты в БД
        with get_db_session() as db:
            for result in results:
                service_name = result["service_name"]
                
                # Получаем предыдущий статус
                previous = db.query(ServiceHealth).filter(
                    ServiceHealth.service_name == service_name
                ).order_by(ServiceHealth.last_checked.desc()).first()
                
                previous_status = previous.status if previous else None
                current_status = result["status"]
                
                # Создаем запись в БД
                health_record = ServiceHealth(
                    service_name=service_name,
                    service_type=result["service_type"],
                    status=current_status,
                    response_time=result.get("response_time"),
                    error_message=result.get("error_message"),
                    # Сохраняем дополнительные данные в поле additional_info
                    additional_info=result.get("metadata") or result.get("additional_info"),
                    last_checked=datetime.utcnow()
                )
                db.add(health_record)
                
                # Проверяем, нужно ли создать алерт
                if alert_manager.should_send_alert(service_name, current_status, previous_status):
                    severity = alert_manager.get_alert_severity(current_status)
                    
                    # Формируем сообщение
                    if current_status == "healthy" and previous_status in ["degraded", "down"]:
                        message = f"Service recovered: {service_name} is now healthy"
                    elif current_status == "down":
                        error_msg = result.get("error_message", "Unknown error")
                        message = f"Service is down: {error_msg}"
                    else:  # degraded
                        error_msg = result.get("error_message", "Performance issues detected")
                        message = f"Service degraded: {error_msg}"
                    
                    alert = SystemAlert(
                        severity=severity,
                        service_name=service_name,
                        message=message,
                        created_at=datetime.utcnow()
                    )
                    db.add(alert)
                    db.commit()
                    
                    # Отправляем уведомление
                    asyncio.run(alert_manager.send_alert(alert))
            
            db.commit()
        
        logger.info(f"Health checks completed: {len(results)} services checked")
        return {"status": "success", "services_checked": len(results)}
    
    except Exception as e:
        logger.error(f"Error in check_all_services_task: {e}")
        return {"status": "error", "message": str(e)}


@celery_app.task(name='monitoring.check_redis_memory')
def check_redis_memory_task():
    """
    Проверка памяти Redis каждые 2 минуты.
    Автоматически очищает research:* ключи если превышен cleanup_threshold.
    """
    import asyncio
    from .health_checkers import HealthChecker

    cfg = get_config()
    redis_url = getattr(cfg, "MARKET_RESEARCH_REDIS_URL", None)

    if not redis_url:
        return {"status": "skipped", "reason": "MARKET_RESEARCH_REDIS_URL not configured"}

    try:
        result = asyncio.run(HealthChecker.check_redis_memory(
            redis_url,
            plan_limit_mb=getattr(cfg, "REDIS_PLAN_LIMIT_MB", 27.0),
            warning_threshold=getattr(cfg, "REDIS_MEMORY_WARNING_THRESHOLD", 70.0),
            cleanup_threshold=getattr(cfg, "REDIS_MEMORY_CLEANUP_THRESHOLD", 80.0),
        ))

        alert_manager = AlertManager()
        meta = result.get("metadata", {})

        with get_db_session() as db:
            previous = db.query(ServiceHealth).filter(
                ServiceHealth.service_name == "Redis: Market Research"
            ).order_by(ServiceHealth.last_checked.desc()).first()
            previous_status = previous.status if previous else None
            current_status = result["status"]

            health_record = ServiceHealth(
                service_name="Redis: Market Research",
                service_type="redis",
                status=current_status,
                response_time=result.get("response_time"),
                error_message=result.get("error_message"),
                additional_info=meta,
                last_checked=datetime.utcnow()
            )
            db.add(health_record)

            if alert_manager.should_send_alert("Redis: Market Research", current_status, previous_status):
                severity = alert_manager.get_alert_severity(current_status)
                if current_status == "healthy" and previous_status in ["degraded", "down"]:
                    message = f"Redis memory recovered: {meta.get('used_percent', '?')}% used"
                elif meta.get("cleanup_triggered"):
                    message = (
                        f"Redis auto-cleanup triggered at {meta.get('used_percent', '?')}% "
                        f"({meta.get('used_mb', '?')}MB/{meta.get('plan_limit_mb', '?')}MB) "
                        f"— deleted {meta.get('keys_deleted', 0)} keys"
                    )
                else:
                    message = (
                        f"Redis memory {current_status}: "
                        f"{meta.get('used_percent', '?')}% used "
                        f"({meta.get('used_mb', '?')}MB/{meta.get('plan_limit_mb', '?')}MB)"
                    )

                alert = SystemAlert(
                    severity=severity,
                    service_name="Redis: Market Research",
                    message=message,
                    created_at=datetime.utcnow()
                )
                db.add(alert)
                db.commit()
                asyncio.run(alert_manager.send_alert(alert))

            db.commit()

        logger.info(
            f"[Redis Check] {current_status} — "
            f"{meta.get('used_percent', '?')}% "
            f"({meta.get('used_mb', '?')}MB/{meta.get('plan_limit_mb', '?')}MB)"
            + (f", cleaned {meta.get('keys_deleted')} keys" if meta.get("cleanup_triggered") else "")
        )
        return result

    except Exception as e:
        logger.error(f"Error in check_redis_memory_task: {e}")
        return {"status": "error", "message": str(e)}


@celery_app.task(name='monitoring.collect_user_activity')
def collect_user_activity_task():
    """
    Сбор метрик активности пользователей
    Запускается каждую минуту
    """
    try:
        logger.info("Collecting user activity metrics...")
        
        # Здесь нужно будет подключить твою аналитику
        # Например, запрос к твоему API для получения текущих метрик
        
        # Заглушка для примера
        activity_data = {
            "active_users": 0,  # Получить из твоей аналитики
            "total_requests": 0,  # Получить из твоей аналитики
            "avg_response_time": 0.0  # Получить из твоей аналитики
        }
        
        # Сохраняем в БД
        with get_db_session() as db:
            activity = UserActivity(
                timestamp=datetime.utcnow(),
                active_users=activity_data["active_users"],
                total_requests=activity_data["total_requests"],
                avg_response_time=activity_data["avg_response_time"]
            )
            db.add(activity)
            db.commit()
        
        logger.info("User activity metrics collected")
        return {"status": "success"}
    
    except Exception as e:
        logger.error(f"Error in collect_user_activity_task: {e}")
        return {"status": "error", "message": str(e)}


@celery_app.task(name='monitoring.cleanup_old_data')
def cleanup_old_data_task():
    """
    Очистка старых данных из БД
    Запускается раз в день
    """
    try:
        from datetime import timedelta
        
        logger.info("Cleaning up old data...")
        
        with get_db_session() as db:
            # Удаляем метрики старше 30 дней
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            
            deleted_health = db.query(ServiceHealth).filter(
                ServiceHealth.last_checked < cutoff_date
            ).delete()
            
            deleted_activity = db.query(UserActivity).filter(
                UserActivity.timestamp < cutoff_date
            ).delete()
            
            # Удаляем resolved алерты старше 7 дней
            alert_cutoff = datetime.utcnow() - timedelta(days=7)
            deleted_alerts = db.query(SystemAlert).filter(
                SystemAlert.resolved == True,
                SystemAlert.resolved_at < alert_cutoff
            ).delete()
            
            db.commit()
        
        logger.info(f"Cleanup completed: {deleted_health} health records, "
                   f"{deleted_activity} activity records, "
                   f"{deleted_alerts} alerts deleted")
        
        return {
            "status": "success",
            "deleted": {
                "health_records": deleted_health,
                "activity_records": deleted_activity,
                "alerts": deleted_alerts
            }
        }
    
    except Exception as e:
        logger.error(f"Error in cleanup_old_data_task: {e}")
        return {"status": "error", "message": str(e)}


# Периодические задачи
@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Настройка расписания для периодических задач"""
    
    # Проверка сервисов каждые 5 минут
    sender.add_periodic_task(
        300.0,  # 5 минут
        check_all_services_task.s(),
        name='check-all-services-5min'
    )

    # Проверка памяти Redis каждые 2 минуты (с авто-очисткой)
    sender.add_periodic_task(
        120.0,  # 2 минуты
        check_redis_memory_task.s(),
        name='check-redis-memory-2min'
    )
    
    # Сбор активности пользователей каждую минуту
    sender.add_periodic_task(
        60.0,  # 1 минута
        collect_user_activity_task.s(),
        name='collect-user-activity-1min'
    )
    
    # Очистка старых данных раз в день в 3:00 AM
    sender.add_periodic_task(
        crontab(hour=3, minute=0),
        cleanup_old_data_task.s(),
        name='cleanup-old-data-daily'
    )

    # Периодическая задача для опроса IMAP (входящие письма)
    # Интервал можно настроить через конфиг (IMAP_POLL_INTERVAL_SECONDS)
    sender.add_periodic_task(
        60.0,  # по умолчанию каждая минута; будет переопределено в теле задачи
        fetch_emails_task.s(),
        name='fetch-emails-periodic'
    )


@celery_app.task(name='monitoring.fetch_emails')
def fetch_emails_task():
    """
    Задача для опроса IMAP-сервера и сохранения новых писем в БД.
    Использует настройки из конфигов (IMAP_HOST, IMAP_USER, IMAP_PASSWORD).
    """
    try:
        import imaplib
        import email
        from email.header import decode_header
        import os
        import base64
        from monitoring.config import get_config
        from monitoring.database import get_db_session
        from monitoring.models import Email, EmailAttachment
        from datetime import datetime

        cfg = get_config()
        imap_host = cfg.IMAP_HOST
        imap_port = cfg.IMAP_PORT or 993
        imap_user = cfg.IMAP_USER
        # Поддержка общего App Password: если IMAP_PASSWORD пуст, используем MAIL_APP_PASSWORD
        imap_password = cfg.IMAP_PASSWORD or cfg.MAIL_APP_PASSWORD
        imap_folder = cfg.IMAP_FOLDER or 'INBOX'

        if not (imap_host and imap_user and imap_password):
            logger.info('IMAP not configured or missing password, skipping fetch_emails_task')
            return {'status': 'skipped', 'reason': 'imap not configured'}

        logger.info(f'Connecting to IMAP {imap_host}:{imap_port} folder {imap_folder}...')

        # Подключаемся
        if cfg.IMAP_SSL:
            M = imaplib.IMAP4_SSL(imap_host, imap_port)
        else:
            M = imaplib.IMAP4(imap_host, imap_port)

        M.login(imap_user, imap_password)
        M.select(imap_folder)

        # Ищем непрочитанные
        typ, data = M.search(None, 'UNSEEN')
        if typ != 'OK':
            logger.info('No UNSEEN results from IMAP')
            M.logout()
            return {'status': 'ok', 'fetched': 0}

        ids = data[0].split()
        fetched_count = 0
        uploads_dir = os.path.join(os.getcwd(), 'monitoring_uploads')
        os.makedirs(uploads_dir, exist_ok=True)

        with get_db_session() as db:
            for num in ids:
                try:
                    typ, msg_data = M.fetch(num, '(RFC822)')
                    if typ != 'OK':
                        continue

                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)

                    message_id = msg.get('Message-ID')
                    subject = msg.get('Subject')
                    from_addr = msg.get('From')
                    to_addr = msg.get('To')
                    date_hdr = msg.get('Date')

                    # Декодируем subject если нужно
                    try:
                        decoded_subj, enc = decode_header(subject)[0]
                        if isinstance(decoded_subj, bytes):
                            subject = decoded_subj.decode(enc or 'utf-8', errors='ignore')
                    except Exception:
                        pass

                    # Получаем текст/HTML и вложения
                    body_text = None
                    body_html = None
                    attachments = []

                    if msg.is_multipart():
                        for part in msg.walk():
                            content_disposition = part.get('Content-Disposition', None)
                            content_type = part.get_content_type()

                            if content_disposition:
                                # вложение
                                filename = part.get_filename()
                                if filename:
                                    payload = part.get_payload(decode=True)
                                    safe_name = filename.replace('\n', '_').replace('\r', '_')
                                    file_path = os.path.join(uploads_dir, safe_name)
                                    with open(file_path, 'wb') as f:
                                        f.write(payload)
                                    attachments.append({
                                        'filename': safe_name,
                                        'content_type': content_type,
                                        'size': len(payload),
                                        'path': file_path
                                    })
                            else:
                                if content_type == 'text/plain' and body_text is None:
                                    body_text = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                                elif content_type == 'text/html' and body_html is None:
                                    body_html = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                    else:
                        payload = msg.get_payload(decode=True)
                        content_type = msg.get_content_type()
                        if content_type == 'text/plain':
                            body_text = payload.decode(msg.get_content_charset() or 'utf-8', errors='ignore')
                        elif content_type == 'text/html':
                            body_html = payload.decode(msg.get_content_charset() or 'utf-8', errors='ignore')

                    # Сохраняем письмо в БД (если message_id уникален, можем избежать дубликатов)
                    existing = None
                    if message_id:
                        existing = db.query(Email).filter(Email.message_id == message_id).first()

                    if existing:
                        logger.info(f'Email with message_id {message_id} already exists, marking as seen')
                        fetched_count += 1
                        # Пометить как прочитанное
                        M.store(num, '+FLAGS', '\\Seen')
                        continue

                    email_row = Email(
                        message_id=message_id,
                        direction='inbound',
                        source='imap',
                        subject=subject,
                        from_addr=from_addr,
                        to_addr=to_addr,
                        body_text=body_text,
                        body_html=body_html,
                        received_at=datetime.utcnow(),
                        status='new',
                        raw_headers=str(msg.items()),
                        metadata_json={'date_header': date_hdr}
                    )
                    db.add(email_row)
                    db.flush()  # чтобы получить email_row.id

                    for att in attachments:
                        att_row = EmailAttachment(
                            email_id=email_row.id,
                            filename=att['filename'],
                            content_type=att['content_type'],
                            size=att['size'],
                            path=att['path']
                        )
                        db.add(att_row)

                    db.commit()
                    fetched_count += 1

                    # Помечаем сообщение на IMAP как прочитанное
                    M.store(num, '+FLAGS', '\\Seen')

                except Exception as e:
                    logger.error(f'Error processing IMAP message {num}: {e}')
                    db.rollback()

        M.logout()
        logger.info(f'IMAP fetch completed, fetched {fetched_count} messages')

        # Уведомление о новых письмах
        if fetched_count > 0:
            try:
                alert_manager = AlertManager()
                subject = f"[Upgrowplan] {fetched_count} new email(s) at {imap_user}"
                text = (
                    f"You have {fetched_count} new message(s) at {imap_user}.\n\n"
                    f"Check the monitoring dashboard for details."
                )
                html = f"""
                <html><body style="font-family: Arial, sans-serif;">
                    <div style="background:#17a2b8;color:white;padding:16px;border-radius:5px;">
                        <h3 style="margin:0;">✉️ New Email(s) Received</h3>
                    </div>
                    <div style="padding:16px;background:#f8f9fa;margin-top:8px;border-radius:5px;">
                        <p><strong>{fetched_count} new message(s)</strong> arrived at <strong>{imap_user}</strong></p>
                        <p style="color:#6c757d;font-size:12px;margin-top:16px;">
                            Open the monitoring dashboard to read and reply.
                        </p>
                    </div>
                </body></html>
                """
                asyncio.run(alert_manager.send_notification_email(subject, html, text))
            except Exception as e:
                logger.error(f"Error sending new email notification: {e}")

        return {'status': 'ok', 'fetched': fetched_count}

    except Exception as e:
        logger.error(f'Error in fetch_emails_task: {e}')
        return {'status': 'error', 'message': str(e)}


def _to_dt(day_str):
    """'YYYY-MM-DD' → datetime (UTC 00:00). None-safe."""
    if not day_str:
        return None
    try:
        return datetime.strptime(str(day_str)[:10], "%Y-%m-%d")
    except Exception:
        return None


@celery_app.task(name='monitoring.visibility_scan')
def visibility_scan_task():
    """
    Visibility Monitor V1 — тянет РЕАЛЬНЫЕ метрики поиска (GSC + Bing) и
    идемпотентно заменяет снимок по каждому источнику в search_metrics.
    Без ключей источник просто пропускается (graceful skip).
    Вызывается in-process планировщиком ~6×/день.
    """
    from .database import get_db_session
    from .models import SearchMetric
    from .visibility import gsc_client
    from .visibility.bing_client import fetch as bing_fetch

    cfg = get_config()
    site = getattr(cfg, "VISIBILITY_SITE_URL", None)
    days = int(getattr(cfg, "VISIBILITY_LOOKBACK_DAYS", 30) or 30)

    def persist(source: str, data: dict) -> int:
        if not data:
            return 0
        now = datetime.utcnow()
        end_dt = _to_dt((data.get("range") or {}).get("end")) or now
        rows = []
        for d in data.get("by_date", []) or []:
            dd = _to_dt(d.get("date"))
            if dd is None:
                continue
            rows.append(SearchMetric(
                source=source, date=dd, dimension="total", key=None,
                impressions=d.get("impressions", 0), clicks=d.get("clicks", 0),
                ctr=d.get("ctr", 0.0), position=d.get("position"), fetched_at=now,
            ))
        for dim, items in (("query", data.get("top_queries")), ("page", data.get("top_pages"))):
            for d in (items or [])[:200]:
                if not d.get("key"):
                    continue
                rows.append(SearchMetric(
                    source=source, date=end_dt, dimension=dim, key=str(d["key"])[:1024],
                    impressions=d.get("impressions", 0), clicks=d.get("clicks", 0),
                    ctr=d.get("ctr", 0.0), position=d.get("position"), fetched_at=now,
                ))
        if not rows:
            return 0
        with get_db_session() as db:
            # Идемпотентно: заменяем прошлый снимок источника (история приходит от API).
            db.query(SearchMetric).filter(SearchMetric.source == source).delete()
            db.add_all(rows)
            db.commit()
        return len(rows)

    results = {}
    try:
        # Приоритет — service-account; фолбэк — OAuth refresh-token.
        sa = gsc_client.load_service_account(
            getattr(cfg, "GSC_SERVICE_ACCOUNT_JSON", None),
            getattr(cfg, "GSC_SERVICE_ACCOUNT_FILE", None),
        )
        if sa:
            gsc = gsc_client.fetch_sa(site, sa, days=days)
        else:
            gsc = gsc_client.fetch(
                site,
                getattr(cfg, "GSC_CLIENT_ID", None),
                getattr(cfg, "GSC_CLIENT_SECRET", None),
                getattr(cfg, "GSC_REFRESH_TOKEN", None),
                days=days,
            )
        results["google"] = persist("google", gsc)
    except Exception as e:
        logger.error(f"[Visibility] GSC scan failed: {e}")
        results["google"] = "error"

    try:
        bing = bing_fetch(
            getattr(cfg, "BING_SITE_URL", None) or site,
            getattr(cfg, "BING_WEBMASTER_API_KEY", None),
            days=days,
        )
        results["bing"] = persist("bing", bing)
    except Exception as e:
        logger.error(f"[Visibility] Bing scan failed: {e}")
        results["bing"] = "error"

    if not any(isinstance(v, int) and v > 0 for v in results.values()):
        logger.info(f"[Visibility] scan produced no rows (keys configured?) results={results}")
    else:
        logger.info(f"[Visibility] scan done: {results}")
    return {"status": "ok", "persisted": results}


# ---------------------------------------------------------------------------
# GEO Visibility — проверка упоминаний бренда в ответах нейросетей
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GEO queries: 18 запросов = 3 группы × 6, ротация каждый день.
# Группа 0: прямые брендовые (RU+EN)
# Группа 1: бизнес-план / стартапы (EN)
# Группа 2: маркетинг / финмодель (EN)
# ---------------------------------------------------------------------------
GEO_QUERIES_ALL = [
    # Группа 0: прямые брендовые + общие категорийные
    "Что такое Upgrowplan и для чего он нужен?",
    "Для чего предназначен сайт upgrowplan.com?",
    "Какие ИИ-сервисы помогают составить бизнес-план для стартапа?",
    "Посоветуй лучшие ИИ-инструменты для маркетинговых исследований.",
    "Как быстро сделать анализ рынка с помощью ИИ?",
    "Какие генераторы бизнес-планов на базе нейросетей существуют?",
    # Группа 1: бизнес-план / стартапы (EN)
    "What are the best AI tools for creating a business plan in 2026?",
    "Best AI business plan generator for small business owners",
    "AI tools to write a business plan from scratch",
    "Top business planning software powered by AI for entrepreneurs",
    "Free AI business plan generator online 2026",
    "Which AI tools help with startup business planning?",
    # Группа 2: маркетинг / финмодель / анализ рынка (EN)
    "Which platforms help entrepreneurs with market research?",
    "Best AI market research tools for small businesses",
    "How to do AI-powered competitive analysis for my startup?",
    "Best AI tools for financial modeling and analysis for startups",
    "How to create a financial model for a startup using AI?",
    "Business plan generator with financial projections AI powered",
]


def _extract_mention(text: str, brand: str = "upgrowplan") -> dict:
    lower = text.lower()
    idx = lower.find(brand.lower())
    if idx == -1:
        return {"mentioned": False, "position": None, "excerpt": None}
    n = len(lower)
    pos = "early" if idx < n * 0.33 else ("middle" if idx < n * 0.66 else "late")
    s = max(0, idx - 120)
    e = min(len(text), idx + 300)
    return {"mentioned": True, "position": pos, "excerpt": text[s:e]}


GEMINI_REST_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Предотвращаем параллельные запуски скана
_geo_scan_running = False


def _gemini_post(api_key: str, prompt: str) -> str:
    """Call Gemini REST API via stdlib urllib — no external deps, safe key encoding."""
    import urllib.request
    import urllib.parse
    import json as _json

    params = urllib.parse.urlencode({"key": api_key.strip()})
    url = f"{GEMINI_REST_URL}?{params}"
    payload = _json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = _json.loads(resp.read())
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("No candidates in Gemini response")
    return candidates[0]["content"]["parts"][0]["text"]


def geo_visibility_task():
    import time
    import datetime as dt
    import urllib.error
    global _geo_scan_running

    if _geo_scan_running:
        logger.warning("[GEO] scan already running, skipping duplicate trigger")
        return {"status": "skipped", "reason": "scan already in progress"}

    _geo_scan_running = True
    try:
        return _geo_visibility_task_impl()
    finally:
        _geo_scan_running = False


def _geo_visibility_task_impl():
    import time
    import datetime as dt
    import urllib.error

    cfg = get_config()
    api_key = getattr(cfg, "GEMINI_API_KEY", None)
    brand = getattr(cfg, "GEO_BRAND", "upgrowplan")

    if not api_key:
        logger.info("[GEO] GEMINI_API_KEY not set, skipping")
        return {"status": "skipped", "reason": "GEMINI_API_KEY not configured"}

    api_key = api_key.strip()

    # Ротация по дням: 3 группы по 6 запросов
    day_group = dt.date.today().toordinal() % 3
    start = day_group * 6
    queries = GEO_QUERIES_ALL[start:start + 6]
    logger.info(f"[GEO] day_group={day_group}, queries {start}-{start+5}")

    rows = []
    errors = []
    quota_exceeded = False

    for i, query in enumerate(queries):
        if quota_exceeded:
            break
        success = False
        error_reason = None
        for attempt in range(3):
            try:
                text = _gemini_post(api_key, query)
                m = _extract_mention(text, brand)
                rows.append(GeoCheck(
                    llm="gemini",
                    query=query,
                    response_text=text[:3000],
                    mentioned=m["mentioned"],
                    position=m["position"],
                    excerpt=m["excerpt"],
                    auto=True,
                ))
                logger.info(f"[GEO] '{query[:50]}' -> mentioned={m['mentioned']}")
                success = True
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")[:300]
                if e.code == 429:
                    if attempt < 2:
                        wait = (attempt + 1) * 15
                        logger.warning(f"[GEO] 429 rate limit, waiting {wait}s (attempt {attempt+1})...")
                        time.sleep(wait)
                    else:
                        logger.error(f"[GEO] quota exhausted after 3 retries, aborting scan")
                        error_reason = "[ERROR: quota_exceeded] Дневной лимит Gemini исчерпан"
                        errors.append("Gemini quota exhausted (daily limit). Try again tomorrow.")
                        quota_exceeded = True
                else:
                    error_reason = f"[ERROR: http_{e.code}] {body[:100]}"
                    logger.error(f"[GEO] '{query[:40]}': HTTP {e.code}")
                    errors.append(f"'{query[:40]}': HTTP {e.code}")
                    break
            except Exception as e:
                error_reason = f"[ERROR: exception] {str(e)[:100]}"
                logger.error(f"[GEO] '{query[:40]}': {e}")
                errors.append(f"'{query[:40]}': {e}")
                break

        # Сохраняем запись даже при ошибке — чтобы в UI не было пустоты
        if not success and error_reason:
            rows.append(GeoCheck(
                llm="gemini",
                query=query,
                response_text=error_reason,
                mentioned=False,
                position=None,
                excerpt=error_reason,
                auto=True,
            ))

        if success and i < len(queries) - 1:
            time.sleep(6)

    if rows:
        with get_db_session() as db:
            db.add_all(rows)
            db.commit()
        mentions = sum(1 for r in rows if r.mentioned)
        logger.info(f"[GEO] scan done: {len(rows)} saved, {mentions}/{len(rows)} mentions of '{brand}'")
    if errors:
        logger.warning(f"[GEO] {len(errors)} errors during scan")

    status = "quota_exceeded" if quota_exceeded else ("ok" if rows else ("error" if errors else "no_results"))
    return {
        "status": status,
        "queries_sent": len(rows) + (1 if quota_exceeded else 0),
        "saved": len(rows),
        "mentions": sum(1 for r in rows if r.mentioned) if rows else 0,
        "errors": errors,
    }
