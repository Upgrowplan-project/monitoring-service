from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta
from typing import List, Optional
import asyncio
import logging
import json

from monitoring import (
    get_db, 
    init_db,
    ServiceHealth, 
    UserActivity, 
    SystemAlert,
    get_config,
    check_all_services,
    Email,
    EmailAttachment
)
from monitoring.ratings_api import router as ratings_router

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создание FastAPI app
app = FastAPI(
    title="Upgrowplan Monitoring API",
    description="API для мониторинга здоровья всех сервисов Upgrowplan",
    version="1.0.0"
)

# Подключаем роутеры
app.include_router(ratings_router)

# Получаем конфигурацию
config = get_config()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        config.FRONTEND_URL,
        "https://www.upgrowplan.com",
        "https://upgrowplan.com",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация БД при старте
@app.on_event("startup")
async def startup_event():
    """Инициализация при старте приложения"""
    logger.info("Initializing database...")
    init_db()
    logger.info("Application started successfully")


# WebSocket для real-time обновлений
class ConnectionManager:
    """Менеджер WebSocket соединений"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Отправка сообщения всем подключенным клиентам"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to websocket: {e}")


manager = ConnectionManager()


@app.websocket("/ws/monitoring")
async def websocket_endpoint(websocket: WebSocket, db: Session = Depends(get_db)):
    """WebSocket endpoint для real-time обновлений"""
    await manager.connect(websocket)
    try:
        while True:
            # Отправляем обновления каждые 5 секунд
            data = await get_monitoring_snapshot(db)
            await websocket.send_json(data)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


async def get_monitoring_snapshot(db: Session) -> dict:
    """Получение текущего снимка состояния системы"""
    
    # Последние статусы всех сервисов
    subquery = (
        db.query(
            ServiceHealth.service_name,
            func.max(ServiceHealth.last_checked).label('max_checked')
        )
        .group_by(ServiceHealth.service_name)
        .subquery()
    )
    
    services = db.query(ServiceHealth).join(
        subquery,
        (ServiceHealth.service_name == subquery.c.service_name) &
        (ServiceHealth.last_checked == subquery.c.max_checked)
    ).all()
    
    # Активные алерты
    active_alerts = db.query(SystemAlert).filter(
        SystemAlert.resolved == False
    ).order_by(SystemAlert.created_at.desc()).limit(10).all()
    
    # Статистика за последние 24 часа
    yesterday = datetime.utcnow() - timedelta(days=1)
    recent_activity = db.query(UserActivity).filter(
        UserActivity.timestamp >= yesterday
    ).all()
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "services": [
            {
                "name": s.service_name,
                "type": s.service_type,
                "status": s.status,
                "response_time": s.response_time,
                "last_checked": s.last_checked.isoformat(),
                "error": s.error_message,
                "additional_info": s.additional_info
            } for s in services
        ],
        "alerts": [
            {
                "id": a.id,
                "severity": a.severity,
                "service": a.service_name,
                "message": a.message,
                "created_at": a.created_at.isoformat()
            } for a in active_alerts
        ],
        "activity": {
            "total_users_24h": sum(a.active_users for a in recent_activity),
            "total_requests_24h": sum(a.total_requests for a in recent_activity),
            "avg_response_time": (
                sum(a.avg_response_time for a in recent_activity) / len(recent_activity)
                if recent_activity else 0
            )
        },
        "emails": [
            {
                "id": e.id,
                "subject": e.subject,
                "from": e.from_addr,
                "to": e.to_addr,
                "status": e.status,
                "received_at": e.received_at.isoformat() if e.received_at else None
            } for e in db.query(Email).order_by(Email.received_at.desc()).limit(10)
        ],
        "overall_health": calculate_overall_health(services)
    }


def calculate_overall_health(services: List[ServiceHealth]) -> str:
    """Рассчитываем общее здоровье системы"""
    if not services:
        return "unknown"
    
    statuses = [s.status for s in services]
    down_count = statuses.count("down")
    degraded_count = statuses.count("degraded")
    
    if down_count > 0:
        return "critical"
    elif degraded_count > 0:
        return "degraded"
    else:
        return "healthy"


# API Endpoints

@app.get("/")
async def root():
    """Главная страница API"""
    return {
        "name": "Upgrowplan Monitoring API",
        "version": "1.0.0",
        "status": "operational"
    }


@app.get("/api/monitoring/overview")
async def get_overview(db: Session = Depends(get_db)):
    """
    Получение общего обзора состояния системы
    
    Returns:
        Dict с информацией о всех сервисах, алертах и активности
    """
    return await get_monitoring_snapshot(db)


@app.get("/api/monitoring/services")
async def get_all_services(db: Session = Depends(get_db)):
    """
    Получение списка всех сервисов с их последними статусами
    """
    subquery = (
        db.query(
            ServiceHealth.service_name,
            func.max(ServiceHealth.last_checked).label('max_checked')
        )
        .group_by(ServiceHealth.service_name)
        .subquery()
    )
    
    services = db.query(ServiceHealth).join(
        subquery,
        (ServiceHealth.service_name == subquery.c.service_name) &
        (ServiceHealth.last_checked == subquery.c.max_checked)
    ).all()
    
    return {
        "services": [
            {
                "name": s.service_name,
                "type": s.service_type,
                "status": s.status,
                "response_time": s.response_time,
                "last_checked": s.last_checked.isoformat(),
                "error": s.error_message,
                "additional_info": s.additional_info
            } for s in services
        ]
    }


@app.get("/api/monitoring/service/{service_name}/history")
async def get_service_history(
    service_name: str,
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Получение истории метрик для конкретного сервиса
    
    Args:
        service_name: Название сервиса
        hours: Количество часов истории (по умолчанию 24)
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    history = db.query(ServiceHealth).filter(
        ServiceHealth.service_name == service_name,
        ServiceHealth.last_checked >= cutoff
    ).order_by(ServiceHealth.last_checked).all()
    
    if not history:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    
    return {
        "service_name": service_name,
        "period_hours": hours,
        "data_points": [
            {
                "timestamp": h.last_checked.isoformat(),
                "status": h.status,
                "response_time": h.response_time,
                "error": h.error_message
            } for h in history
        ]
    }


@app.get("/api/monitoring/alerts")
async def get_alerts(
    resolved: Optional[bool] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Получение списка алертов с фильтрацией
    
    Args:
        resolved: Фильтр по resolved статусу
        severity: Фильтр по severity (info, warning, critical)
        limit: Максимальное количество результатов
    """
    query = db.query(SystemAlert)
    
    if resolved is not None:
        query = query.filter(SystemAlert.resolved == resolved)
    
    if severity:
        query = query.filter(SystemAlert.severity == severity)
    
    alerts = query.order_by(SystemAlert.created_at.desc()).limit(limit).all()
    
    return {
        "alerts": [
            {
                "id": a.id,
                "severity": a.severity,
                "service": a.service_name,
                "message": a.message,
                "created_at": a.created_at.isoformat(),
                "resolved": a.resolved,
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
                "resolved_by": a.resolved_by
            } for a in alerts
        ]
    }


@app.post("/api/monitoring/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    resolved_by: str = "admin",
    db: Session = Depends(get_db)
):
    """
    Отметить алерт как resolved
    
    Args:
        alert_id: ID алерта
        resolved_by: Кто разрешил алерт
    """
    alert = db.query(SystemAlert).filter(SystemAlert.id == alert_id).first()
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.resolved = True
    alert.resolved_at = datetime.utcnow()
    alert.resolved_by = resolved_by
    db.commit()
    
    return {
        "message": "Alert resolved successfully",
        "alert_id": alert_id
    }


@app.post('/api/monitoring/contact')
async def post_contact(payload: dict, db: Session = Depends(get_db)):
    """Приём сообщений с контактной формы: отправка на SMTP и сохранение в БД"""
    try:
        name = payload.get('name')
        email_addr = payload.get('email')
        message_text = payload.get('message')

        if not email_addr or not message_text:
            raise HTTPException(status_code=400, detail='Missing required fields')

        cfg = get_config()
        # Формируем EmailMessage
        from email.message import EmailMessage
        import smtplib

        msg = EmailMessage()
        subject = f"Website contact: {name or email_addr}"
        msg['Subject'] = subject
        msg['From'] = cfg.SMTP_USER or email_addr
        msg['To'] = cfg.ADMIN_EMAIL or (cfg.SMTP_USER or 'info@upgrowplan.com')
        msg['Reply-To'] = email_addr
        msg.set_content(f"From: {name or ''} <{email_addr}>\n\n{message_text}")

        # Отправляем через SMTP (опциональна для разработки)
        smtp_password = cfg.SMTP_PASSWORD or cfg.MAIL_APP_PASSWORD
        logger.info(f"SMTP Config: host={cfg.SMTP_HOST}, port={cfg.SMTP_PORT}, user={cfg.SMTP_USER}, has_password={bool(smtp_password)}")
        
        if cfg.SMTP_HOST and cfg.SMTP_USER and smtp_password:
            # Пытаемся отправить
            smtp_port = cfg.SMTP_PORT or 587
            try:
                if smtp_port == 465:
                    server = smtplib.SMTP_SSL(cfg.SMTP_HOST, smtp_port)
                else:
                    server = smtplib.SMTP(cfg.SMTP_HOST, smtp_port)
                    server.starttls()
                
                logger.info(f"Attempting SMTP login with user={cfg.SMTP_USER}, password_len={len(smtp_password)}")
                server.login(cfg.SMTP_USER, smtp_password)
                logger.info("SMTP login successful")
                server.send_message(msg)
                server.quit()
                logger.info("Email sent via SMTP successfully")
            except Exception as smtp_err:
                logger.warning(f"SMTP send failed (may be free tier limitation): {smtp_err}. Email will be saved to database only.")
        else:
            logger.info("SMTP not configured - email will be saved to database only")


        # Сохраняем исходящее письмо в БД
        email_row = Email(
            message_id=None,
            direction='outbound',
            source='contact_form',
            subject=subject,
            from_addr=msg['From'],
            to_addr=msg['To'],
            body_text=msg.get_content(),
            sent_at=datetime.utcnow(),
            status='sent',
            metadata_json={'reply_to': email_addr}
        )
        db.add(email_row)
        db.commit()

        return { 'message': 'sent' }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in post_contact: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/monitoring/emails')
async def list_emails(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    """Список писем (входящие/исходящие)"""
    query = db.query(Email).order_by(Email.received_at.desc().nullslast(), Email.created_at.desc()).limit(limit).offset(offset)
    rows = query.all()
    items = []
    for r in rows:
        items.append({
            'id': r.id,
            'subject': r.subject,
            'from': r.from_addr,
            'to': r.to_addr,
            'status': r.status,
            'direction': r.direction,
            'received_at': r.received_at.isoformat() if r.received_at else None,
            'created_at': r.created_at.isoformat()
        })
    return { 'items': items }


@app.get('/api/monitoring/emails/{email_id}')
async def get_email(email_id: int, db: Session = Depends(get_db)):
    row = db.query(Email).filter(Email.id == email_id).first()
    if not row:
        raise HTTPException(status_code=404, detail='Email not found')
    # attachments
    attachments = db.query(EmailAttachment).filter(EmailAttachment.email_id == row.id).all()
    return {
        'id': row.id,
        'subject': row.subject,
        'from': row.from_addr,
        'to': row.to_addr,
        'cc': row.cc,
        'body_text': row.body_text,
        'body_html': row.body_html,
        'status': row.status,
        'direction': row.direction,
        'received_at': row.received_at.isoformat() if row.received_at else None,
        'attachments': [ { 'id': a.id, 'filename': a.filename, 'path': a.path } for a in attachments ]
    }


@app.post('/api/monitoring/emails/{email_id}/reply')
async def reply_email(email_id: int, payload: dict, db: Session = Depends(get_db)):
    """Ответить на письмо: отправить через SMTP и сохранить исходящее сообщение"""
    try:
        row = db.query(Email).filter(Email.id == email_id).first()
        if not row:
            raise HTTPException(status_code=404, detail='Email not found')

        body = payload.get('body')
        if not body:
            raise HTTPException(status_code=400, detail='Missing body')

        cfg = get_config()
        from email.message import EmailMessage
        import smtplib

        msg = EmailMessage()
        subj = f"Re: {row.subject or ''}"
        msg['Subject'] = subj
        msg['From'] = cfg.SMTP_USER
        # Получаем адрес для ответа из Reply-To или From
        reply_to = None
        # Попробуем извлечь адрес
        if row.metadata_json and row.metadata_json.get('reply_to'):
            reply_to = row.metadata_json.get('reply_to')
        elif row.from_addr:
            reply_to = row.from_addr
        msg['To'] = reply_to
        msg.set_content(body)

        # Используем MAIL_APP_PASSWORD как fallback
        smtp_password = cfg.SMTP_PASSWORD or cfg.MAIL_APP_PASSWORD
        if not (cfg.SMTP_HOST and cfg.SMTP_USER and smtp_password):
            raise HTTPException(status_code=500, detail='SMTP not configured')

        smtp_port = cfg.SMTP_PORT or 587
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(cfg.SMTP_HOST, smtp_port)
        else:
            server = smtplib.SMTP(cfg.SMTP_HOST, smtp_port)
            server.starttls()
        server.login(cfg.SMTP_USER, smtp_password)
        server.send_message(msg)
        server.quit()

        # Сохраняем исходящее письмо
        email_row = Email(
            direction='outbound',
            source='reply',
            subject=subj,
            from_addr=msg['From'],
            to_addr=msg['To'],
            body_text=body,
            sent_at=datetime.utcnow(),
            status='sent',
            metadata_json={'in_reply_to': row.id}
        )
        db.add(email_row)
        # Обновляем статус оригинала
        row.status = 'read'
        db.commit()

        return {'message': 'sent'}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in reply_email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/monitoring/activity")
async def get_user_activity(
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Получение статистики активности пользователей
    
    Args:
        hours: Период в часах (по умолчанию 24)
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    activity = db.query(UserActivity).filter(
        UserActivity.timestamp >= cutoff
    ).order_by(UserActivity.timestamp).all()
    
    return {
        "period_hours": hours,
        "data_points": [
            {
                "timestamp": a.timestamp.isoformat(),
                "active_users": a.active_users,
                "total_requests": a.total_requests,
                "avg_response_time": a.avg_response_time
            } for a in activity
        ],
        "summary": {
            "total_users": sum(a.active_users for a in activity),
            "total_requests": sum(a.total_requests for a in activity),
            "avg_response_time": (
                sum(a.avg_response_time for a in activity) / len(activity)
                if activity else 0
            )
        }
    }


@app.post("/api/monitoring/check-now")
async def trigger_health_check(db: Session = Depends(get_db)):
    """
    Триггер немедленной проверки всех сервисов
    """
    try:
        results = await check_all_services(config)
        
        # Сохраняем результаты
        for result in results:
            health_record = ServiceHealth(
                service_name=result["service_name"],
                service_type=result["service_type"],
                status=result["status"],
                response_time=result.get("response_time"),
                error_message=result.get("error_message"),
                additional_info=result.get("metadata"),
                last_checked=datetime.utcnow()
            )
            db.add(health_record)
        
        db.commit()
        
        # Отправляем обновление через WebSocket
        snapshot = await get_monitoring_snapshot(db)
        await manager.broadcast(snapshot)
        
        return {
            "message": "Health check completed",
            "services_checked": len(results),
            "results": results
        }
    except Exception as e:
        logger.error(f"Error in manual health check: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/monitoring/stats")
async def get_statistics(db: Session = Depends(get_db)):
    """
    Получение общей статистики системы мониторинга
    """
    # Подсчитываем количество проверок
    total_checks = db.query(func.count(ServiceHealth.id)).scalar()
    
    # Подсчитываем количество алертов
    total_alerts = db.query(func.count(SystemAlert.id)).scalar()
    active_alerts = db.query(func.count(SystemAlert.id)).filter(
        SystemAlert.resolved == False
    ).scalar()
    
    # Подсчитываем количество уникальных сервисов
    unique_services = db.query(func.count(func.distinct(ServiceHealth.service_name))).scalar()
    
    return {
        "total_health_checks": total_checks,
        "total_alerts": total_alerts,
        "active_alerts": active_alerts,
        "monitored_services": unique_services,
        "uptime_percentage": 99.9  # Можно рассчитать на основе реальных данных
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
