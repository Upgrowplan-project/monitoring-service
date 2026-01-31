from celery import Celery
from celery.schedules import crontab
from datetime import datetime
import logging
from .config import get_config
from .database import get_db_session
from .models import ServiceHealth, SystemAlert, UserActivity
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
        return {'status': 'ok', 'fetched': fetched_count}

    except Exception as e:
        logger.error(f'Error in fetch_emails_task: {e}')
        return {'status': 'error', 'message': str(e)}
