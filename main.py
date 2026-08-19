from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, text
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
    EmailAttachment,
    SynthesisLog,
    ResearchReport,
    UserRating,
    WebEvent,
)
from monitoring.models import GeoCheck, BotCrawlEvent
from monitoring.ratings_api import router as ratings_router
from monitoring import auth as mon_auth
from fastapi.responses import JSONResponse

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

# Auth middleware: ADMIN-JWT на чтение, X-Ingest-Token на ingest, публичные —
# открыты (см. monitoring/auth.py). Регистрируется ДО CORS, чтобы CORS остался
# внешним слоем и проставлял заголовки даже на ответах 401/403.
from starlette.middleware.base import BaseHTTPMiddleware


async def _auth_dispatch(request, call_next):
    verdict = mon_auth.check_request(
        request.method,
        request.url.path,
        request.headers.get("authorization"),
        request.headers.get("x-ingest-token"),
    )
    if verdict is not None:
        code, msg = verdict
        return JSONResponse(status_code=code, content={"detail": msg})
    return await call_next(request)


app.add_middleware(BaseHTTPMiddleware, dispatch=_auth_dispatch)

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
    # Запускаем встроенный планировщик (health-проверки, Redis, IMAP-почта),
    # т.к. в проде нет отдельных worker/beat дайно.
    try:
        from monitoring.scheduler import scheduler
        scheduler.start(config)
    except Exception as e:
        logger.error(f"Failed to start in-process scheduler: {e}")
    logger.info("Application started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Корректная остановка планировщика."""
    try:
        from monitoring.scheduler import scheduler
        await scheduler.stop()
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")


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
    """WebSocket endpoint для real-time обновлений (требует admin-токен в ?token=)"""
    if not mon_auth.verify_ws_token(websocket.query_params.get("token")):
        await websocket.close(code=1008)  # policy violation
        return
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

    # Последние этапные логи генерации бизнес-планов (если таблица доступна)
    recent_generation_logs = []
    try:
        rows = db.execute(
            text(
                """
                SELECT session_id, created_at, level, source, stage, progress, message
                FROM synthesis_logs
                WHERE service_name = :service_name
                ORDER BY created_at DESC
                LIMIT 15
                """
            ),
            {"service_name": "social-plan-master"},
        ).mappings().all()
        recent_generation_logs = [
            {
                "session_id": r["session_id"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "level": r["level"],
                "source": r["source"],
                "stage": r["stage"],
                "progress": float(r["progress"]) if r["progress"] is not None else None,
                "message": r["message"],
            }
            for r in rows
        ]
    except Exception:
        # Если таблица ещё не создана — не ломаем основной мониторинг.
        recent_generation_logs = []
    
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
        "recent_generation_logs": recent_generation_logs,
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


# ── Visibility Monitor V1 (реальные метрики поиска: GSC + Bing) ───────────────
# Под /api/monitoring/* → авто-защита admin-JWT существующим middleware.

@app.get("/api/monitoring/visibility/timeseries")
async def visibility_timeseries(days: int = 30, db: Session = Depends(get_db)):
    """Дневной ряд impressions/clicks/CTR/позиции по источникам (google, bing)."""
    from monitoring.models import SearchMetric

    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(SearchMetric)
        .filter(SearchMetric.dimension == "total", SearchMetric.date >= cutoff)
        .order_by(SearchMetric.date.asc())
        .all()
    )
    out: dict = {"google": [], "bing": []}
    for r in rows:
        out.setdefault(r.source, []).append({
            "date": r.date.date().isoformat(),
            "impressions": r.impressions,
            "clicks": r.clicks,
            "ctr": r.ctr,
            "position": r.position,
        })
    return out


@app.get("/api/monitoring/visibility/top")
async def visibility_top(
    source: str = "google", dimension: str = "query", limit: int = 25,
    db: Session = Depends(get_db),
):
    """Топ запросов/страниц источника по показам."""
    from monitoring.models import SearchMetric

    rows = (
        db.query(SearchMetric)
        .filter(SearchMetric.source == source, SearchMetric.dimension == dimension)
        .order_by(SearchMetric.impressions.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [
        {"key": r.key, "impressions": r.impressions, "clicks": r.clicks,
         "ctr": r.ctr, "position": r.position}
        for r in rows
    ]


@app.get("/api/monitoring/visibility/summary")
async def visibility_summary(db: Session = Depends(get_db)):
    """Сводка по источникам: суммарные показы/клики/CTR окна + свежесть данных."""
    from monitoring.models import SearchMetric

    out: dict = {}
    for source in ("google", "bing"):
        agg = (
            db.query(
                func.coalesce(func.sum(SearchMetric.impressions), 0),
                func.coalesce(func.sum(SearchMetric.clicks), 0),
                func.max(SearchMetric.fetched_at),
            )
            .filter(SearchMetric.source == source, SearchMetric.dimension == "total")
            .first()
        )
        impressions = int(agg[0] or 0)
        clicks = int(agg[1] or 0)
        out[source] = {
            "impressions": impressions,
            "clicks": clicks,
            "ctr": (clicks / impressions) if impressions else 0.0,
            "last_fetched": agg[2].isoformat() if agg[2] else None,
        }
    return out


@app.post("/api/monitoring/visibility/scan")
async def visibility_scan_now():
    """Запустить скан немедленно (для кнопки 'Scan now' во вкладке)."""
    import asyncio
    from monitoring.tasks import visibility_scan_task

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, visibility_scan_task)
    return {"status": "ok", "result": result}


@app.get("/api/monitoring/geo")
async def geo_results(limit: int = 100, db: Session = Depends(get_db)):
    """GEO Visibility: последние результаты проверки упоминаний бренда в нейросетях."""
    rows = (
        db.query(GeoCheck)
        .order_by(GeoCheck.created_at.desc())
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": r.id,
            "llm": r.llm,
            "query": r.query,
            "mentioned": r.mentioned,
            "position": r.position,
            "excerpt": r.excerpt,
            "auto": r.auto,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    # Сводка по LLM — error-записи не учитываются в проценте
    from collections import defaultdict
    summary: dict = defaultdict(lambda: {"total": 0, "mentioned": 0, "errors": 0, "last_check": None})
    for r in rows:
        s = summary[r.llm]
        is_error = (r.excerpt or "").startswith("[ERROR:") or (r.response_text or "").startswith("[ERROR:")
        if is_error:
            s["errors"] += 1
        else:
            s["total"] += 1
            if r.mentioned:
                s["mentioned"] += 1
        if s["last_check"] is None or r.created_at.isoformat() > s["last_check"]:
            s["last_check"] = r.created_at.isoformat()
    return {"items": items, "summary": dict(summary)}


@app.post("/api/monitoring/geo/scan")
async def geo_scan_now(background_tasks: BackgroundTasks):
    """Запускает GEO-скан в фоне, сразу возвращает ответ (Heroku H12 prevention)."""
    from monitoring.tasks import geo_visibility_task
    background_tasks.add_task(geo_visibility_task)
    return {"status": "started", "message": "Скан запущен в фоне (~60–90 сек). Данные появятся после завершения."}


@app.post("/api/monitoring/geo/manual")
async def geo_manual(body: dict, db: Session = Depends(get_db)):
    """Сохранить результат ручной проверки (вставить ответ из ChatGPT / Perplexity / etc)."""
    cfg = get_config()
    brand = getattr(cfg, "GEO_BRAND", "upgrowplan")
    from monitoring.tasks import _extract_mention
    text = body.get("response_text", "")
    m = _extract_mention(text, brand)
    row = GeoCheck(
        llm=body.get("llm", "manual"),
        query=body.get("query", ""),
        response_text=text[:3000],
        mentioned=m["mentioned"],
        position=m["position"],
        excerpt=m["excerpt"],
        auto=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "mentioned": row.mentioned, "position": row.position, "excerpt": row.excerpt}


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


@app.get("/api/monitoring/synthesis-logs/sessions")
async def get_synthesis_log_sessions(
    limit: int = 50,
    service_name: str = "social-plan-master",
    db: Session = Depends(get_db),
):
    """
    Список последних сессий генерации с агрегированной информацией по логам.
    """
    try:
        rows = db.execute(
            text(
                """
                SELECT
                    session_id,
                    MAX(created_at) AS last_log_at,
                    MAX(progress) AS max_progress,
                    COUNT(*) AS logs_count,
                    MAX(CASE WHEN level = 'ERROR' THEN 1 ELSE 0 END) AS has_error
                FROM synthesis_logs
                WHERE service_name = :service_name
                GROUP BY session_id
                ORDER BY MAX(created_at) DESC
                LIMIT :limit
                """
            ),
            {"service_name": service_name, "limit": max(1, min(limit, 500))},
        ).mappings().all()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось получить список сессий логов: {e}",
        )

    return {
        "service_name": service_name,
        "sessions": [
            {
                "session_id": r["session_id"],
                "last_log_at": r["last_log_at"].isoformat() if r["last_log_at"] else None,
                "max_progress": float(r["max_progress"]) if r["max_progress"] is not None else None,
                "logs_count": int(r["logs_count"] or 0),
                "has_error": bool(r["has_error"]),
            }
            for r in rows
        ],
    }


@app.get("/api/monitoring/synthesis-logs/{session_id}")
async def get_synthesis_logs_by_session(
    session_id: str,
    limit: int = 300,
    level: Optional[str] = None,
    service_name: str = "social-plan-master",
    db: Session = Depends(get_db),
):
    """
    Детальные логи конкретной сессии генерации бизнес-плана.
    """
    where_level = ""
    params = {
        "session_id": session_id,
        "service_name": service_name,
        "limit": max(1, min(limit, 5000)),
    }
    if level:
        where_level = " AND level = :level"
        params["level"] = level.upper()

    try:
        rows = db.execute(
            text(
                f"""
                SELECT id, session_id, created_at, level, source, stage, progress, message, payload_json
                FROM synthesis_logs
                WHERE session_id = :session_id
                  AND service_name = :service_name
                  {where_level}
                ORDER BY created_at ASC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось получить логи сессии: {e}",
        )

    return {
        "session_id": session_id,
        "service_name": service_name,
        "count": len(rows),
        "logs": [
            {
                "id": r["id"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "level": r["level"],
                "source": r["source"],
                "stage": r["stage"],
                "progress": float(r["progress"]) if r["progress"] is not None else None,
                "message": r["message"],
                "payload_json": r["payload_json"],
            }
            for r in rows
        ],
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
    """Приём сообщений с контактной формы: отправка через Brevo API и сохранение в БД"""
    try:
        name = payload.get('name')
        email_addr = payload.get('email')
        message_text = payload.get('message')

        if not email_addr or not message_text:
            raise HTTPException(status_code=400, detail='Missing required fields')

        cfg = get_config()
        subject = f"Website contact: {name or email_addr}"
        from_email = getattr(cfg, 'SMTP_FROM_EMAIL', None) or 'info@upgrowplan.com'
        to_email = cfg.ADMIN_EMAIL or 'naletovd@gmail.com'
        body_text = f"From: {name or ''} <{email_addr}>\n\n{message_text}"

        # Отправка через Brevo HTTP API (работает на Heroku, не требует SMTP-порта)
        brevo_key = (getattr(cfg, 'BREVO_API_KEY', None) or '').strip()
        sent = False
        if brevo_key:
            try:
                import httpx as _httpx
                resp = _httpx.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={"api-key": brevo_key, "Content-Type": "application/json"},
                    json={
                        "sender": {"name": "Upgrowplan", "email": from_email},
                        "to": [{"email": to_email}],
                        "replyTo": {"email": email_addr},
                        "subject": subject,
                        "textContent": body_text,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                sent = True
                logger.info(f"Email sent via Brevo API to {to_email}")
            except Exception as e:
                logger.warning(f"Brevo API send failed: {e}. Email saved to DB only.")
        else:
            logger.info("Brevo API key not configured — email saved to DB only")

        # Авто-ответ пользователю
        is_beta = 'beta' in message_text.lower() or 'бета' in message_text.lower() or 'wishlist' in message_text.lower()
        auto_reply_subject = "Thank you for your interest in Upgrowplan!"
        auto_reply_text = (
            f"Hi{' ' + name if name else ''},\n\n"
            + (
                "Thank you for signing up! We've added you to our early access list.\n"
                "We'll reach out as soon as your spot opens up.\n\n"
                if is_beta else
                "We've received your message and will get back to you as soon as possible.\n\n"
            )
            + "Best regards,\nThe Upgrowplan Team\nupgrowplan.com\n\n"
            + "---\n"
            + (
                "Спасибо за интерес к проекту! Мы добавили вас в список ранних пользователей и свяжемся с вами, когда место откроется.\n"
                if is_beta else
                "Мы получили ваше сообщение и ответим в ближайшее время. Спасибо за интерес к проекту Upgrowplan!\n"
            )
        )
        auto_reply_html = (
            "<html><body style='font-family:Arial,sans-serif;max-width:600px;margin:0 auto;'>"
            "<div style='background:#1e6078;padding:20px;border-radius:8px 8px 0 0;'>"
            "<img src='https://www.upgrowplan.com/logo.png' alt='Upgrowplan' style='height:32px;' onerror=\"this.style.display='none'\">"
            "<h2 style='color:#fff;margin:8px 0 0;'>Upgrowplan</h2></div>"
            "<div style='background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0;'>"
            + (f"<p>Hi{' <strong>' + name + '</strong>' if name else ''},</p>" )
            + (
                "<p>Thank you for signing up! 🎉<br>We've added you to our <strong>early access list</strong>. We'll reach out as soon as your spot opens up.</p>"
                if is_beta else
                "<p>We've received your message and will get back to you as soon as possible. Thank you for reaching out!</p>"
            )
            + "<p style='color:#64748b;font-size:13px;margin-top:24px;border-top:1px solid #e2e8f0;padding-top:12px;'>"
            + (
                "Спасибо за интерес к проекту! Мы добавили вас в список ранних пользователей и свяжемся с вами, когда место откроется."
                if is_beta else
                "Мы получили ваше сообщение и ответим в ближайшее время. Спасибо за интерес к проекту Upgrowplan!"
            )
            + "</p>"
            "<p style='color:#94a3b8;font-size:12px;'>The Upgrowplan Team · <a href='https://www.upgrowplan.com' style='color:#1e6078;'>upgrowplan.com</a></p>"
            "</div></body></html>"
        )

        if brevo_key and email_addr:
            try:
                import httpx as _httpx
                _httpx.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={"api-key": brevo_key, "Content-Type": "application/json"},
                    json={
                        "sender": {"name": "Upgrowplan Team", "email": from_email},
                        "to": [{"email": email_addr}],
                        "subject": auto_reply_subject,
                        "htmlContent": auto_reply_html,
                        "textContent": auto_reply_text,
                    },
                    timeout=15,
                )
                logger.info(f"Auto-reply sent to {email_addr}")
            except Exception as e:
                logger.warning(f"Auto-reply send failed: {e}")

        # Сохраняем в БД
        email_row = Email(
            message_id=None,
            direction='outbound',
            source='contact_form',
            subject=subject,
            from_addr=from_email,
            to_addr=to_email,
            body_text=body_text,
            sent_at=datetime.utcnow(),
            status='sent' if sent else 'db_only',
            metadata_json={'reply_to': email_addr}
        )
        db.add(email_row)
        db.commit()

        return {'message': 'sent'}

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
            'source': r.source,
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


# ============================================================
# Research Reports & Logs ingestion (market-research-service и др.)
# ============================================================

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


@app.post("/api/monitoring/reports")
async def ingest_research_report(payload: dict, db: Session = Depends(get_db)):
    """
    Приём готового отчёта от сервиса генерации (market-research-service).

    Идемпотентно по research_id (upsert): повторный POST обновляет запись.
    Тело: { research_id, service_name?, request?, report?, status?,
            duration_seconds?, completed_at? }.
    Краткие поля (product_name/country/...) берутся из request, если переданы.
    """
    research_id = payload.get("research_id") or payload.get("session_id")
    if not research_id:
        raise HTTPException(status_code=400, detail="research_id is required")

    request_json = payload.get("request") or payload.get("request_json") or {}
    report_json = payload.get("report") or payload.get("report_json")
    req = request_json if isinstance(request_json, dict) else {}

    def _g(*keys):
        for k in keys:
            v = req.get(k)
            if v:
                return v if isinstance(v, str) else str(v)
        return None

    try:
        row = (
            db.query(ResearchReport)
            .filter(ResearchReport.research_id == research_id)
            .first()
        )
        if row is None:
            row = ResearchReport(research_id=research_id)
            db.add(row)

        row.service_name = payload.get("service_name") or "market-research-service"
        row.product_name = _g("product_name", "productName")
        row.country = _g("country")
        row.region = _g("region")
        row.business_type = _g("business_type", "businessType")
        row.product_type = _g("product_type", "productType")
        row.industry = _g("industry")
        row.localization = _g("localization")
        row.report_language = _g("report_language", "reportLanguage")
        row.status = payload.get("status") or "completed"
        ds = payload.get("duration_seconds")
        row.duration_seconds = float(ds) if ds is not None else None
        row.request_json = req or None
        if report_json is not None:
            row.report_json = report_json
        row.completed_at = _parse_iso(payload.get("completed_at")) or datetime.utcnow()

        db.commit()
        db.refresh(row)
        return {"success": True, "id": row.id, "research_id": research_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error ingesting research report {research_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/monitoring/synthesis-logs")
async def ingest_synthesis_logs(payload: dict, db: Session = Depends(get_db)):
    """
    Батч-приём этапных логов пайплайна.

    Тело: { service_name?, environment?, session_id?, logs: [
        { session_id?, level?, source?, stage?, progress?, message?, payload_json?, created_at? } ] }
    session_id/service_name можно задать на верхнем уровне как дефолт для всех строк.
    """
    logs = payload.get("logs")
    if not isinstance(logs, list) or not logs:
        raise HTTPException(status_code=400, detail="logs (non-empty list) is required")

    default_service = payload.get("service_name") or "market-research-service"
    default_session = payload.get("session_id")
    default_env = payload.get("environment")

    inserted = 0
    try:
        for entry in logs:
            if not isinstance(entry, dict):
                continue
            session_id = entry.get("session_id") or default_session
            if not session_id:
                continue
            progress = entry.get("progress")
            db.add(
                SynthesisLog(
                    session_id=str(session_id),
                    service_name=entry.get("service_name") or default_service,
                    environment=entry.get("environment") or default_env,
                    created_at=_parse_iso(entry.get("created_at")) or datetime.utcnow(),
                    level=(entry.get("level") or "INFO").upper(),
                    source=(entry.get("source") or "backend"),
                    stage=entry.get("stage"),
                    progress=float(progress) if progress is not None else None,
                    message=entry.get("message"),
                    payload_json=entry.get("payload_json"),
                )
            )
            inserted += 1
        db.commit()
        return {"success": True, "inserted": inserted}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error ingesting synthesis logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/monitoring/reports")
async def list_research_reports(
    service_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Список сохранённых отчётов (краткие карточки) с привязкой оценки по research_id."""
    query = db.query(ResearchReport)
    if service_name:
        query = query.filter(ResearchReport.service_name == service_name)
    rows = (
        query.order_by(ResearchReport.created_at.desc())
        .limit(max(1, min(limit, 500)))
        .offset(max(0, offset))
        .all()
    )

    ids = [r.research_id for r in rows]
    ratings = {}
    if ids:
        for rt in db.query(UserRating).filter(UserRating.session_id.in_(ids)).all():
            ratings[rt.session_id] = rt.overall_rating

    return {
        "service_name": service_name,
        "total": query.count(),
        "reports": [
            {
                "research_id": r.research_id,
                "service_name": r.service_name,
                "product_name": r.product_name,
                "country": r.country,
                "region": r.region,
                "business_type": r.business_type,
                "product_type": r.product_type,
                "industry": r.industry,
                "localization": r.localization,
                "report_language": r.report_language,
                "status": r.status,
                "duration_seconds": r.duration_seconds,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "rating": ratings.get(r.research_id),
            }
            for r in rows
        ],
    }


@app.get("/api/monitoring/reports/{research_id}")
async def get_research_report(research_id: str, db: Session = Depends(get_db)):
    """Полный отчёт + входной запрос + этапные логи + оценка тестера."""
    row = (
        db.query(ResearchReport)
        .filter(ResearchReport.research_id == research_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")

    logs = (
        db.query(SynthesisLog)
        .filter(SynthesisLog.session_id == research_id)
        .order_by(SynthesisLog.created_at.asc())
        .limit(5000)
        .all()
    )
    rating = (
        db.query(UserRating)
        .filter(UserRating.session_id == research_id)
        .order_by(UserRating.created_at.desc())
        .first()
    )

    return {
        "research_id": row.research_id,
        "service_name": row.service_name,
        "product_name": row.product_name,
        "country": row.country,
        "region": row.region,
        "business_type": row.business_type,
        "product_type": row.product_type,
        "industry": row.industry,
        "localization": row.localization,
        "report_language": row.report_language,
        "status": row.status,
        "duration_seconds": row.duration_seconds,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "request": row.request_json,
        "report": row.report_json,
        "logs": [
            {
                "created_at": l.created_at.isoformat() if l.created_at else None,
                "level": l.level,
                "source": l.source,
                "stage": l.stage,
                "progress": l.progress,
                "message": l.message,
            }
            for l in logs
        ],
        "rating": (
            {
                "overall": rating.overall_rating,
                "clarity": rating.clarity,
                "usefulness": rating.usefulness,
                "accuracy": rating.accuracy,
                "design": rating.design,
                "recommend": rating.recommend,
                "feedback": rating.feedback,
                "created_at": rating.created_at.isoformat() if rating.created_at else None,
            }
            if rating
            else None
        ),
    }


# ============================================================
# Web analytics (posещаемость сайта) — beacon ingest + агрегаты
# ============================================================

def _hash_ip(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return None
    import hashlib
    return hashlib.sha256(f"upgrowplan-salt::{ip}".encode()).hexdigest()[:32]


def _parse_user_agent(ua: str) -> dict:
    """Грубое определение device/browser/os без внешних зависимостей."""
    if not ua:
        return {"device_type": None, "browser": None, "os": None}
    u = ua.lower()
    if any(k in u for k in ("ipad", "tablet")):
        device = "tablet"
    elif any(k in u for k in ("mobi", "iphone", "android")) and "ipad" not in u:
        device = "mobile" if "mobile" in u or "iphone" in u or "android" in u else "desktop"
    else:
        device = "desktop"
    if "edg" in u:
        browser = "Edge"
    elif "opr" in u or "opera" in u:
        browser = "Opera"
    elif "chrome" in u and "chromium" not in u:
        browser = "Chrome"
    elif "firefox" in u:
        browser = "Firefox"
    elif "safari" in u:
        browser = "Safari"
    else:
        browser = "Other"
    if "windows" in u:
        os_name = "Windows"
    elif "android" in u:
        os_name = "Android"
    elif any(k in u for k in ("iphone", "ipad", "ios")):
        os_name = "iOS"
    elif "mac os" in u or "macintosh" in u:
        os_name = "macOS"
    elif "linux" in u:
        os_name = "Linux"
    else:
        os_name = "Other"
    return {"device_type": device, "browser": browser, "os": os_name}


@app.post("/api/monitoring/pageview")
async def ingest_pageview(payload: dict, request: Request, db: Session = Depends(get_db)):
    """
    Приём beacon о просмотре страницы / событии с фронта. Анонимно, без авторизации.
    Тело: { path, referrer?, utm_source?, utm_medium?, utm_campaign?, visitor_id?,
            session_id?, locale?, timezone?, event_type?, event_name?, url? }
    """
    try:
        # IP из заголовков прокси (Heroku/Vercel/CF), берём первый.
        fwd = request.headers.get("x-forwarded-for", "")
        client_ip = (fwd.split(",")[0].strip() if fwd else None) or (
            request.client.host if request.client else None
        )
        country = (
            request.headers.get("x-vercel-ip-country")
            or request.headers.get("cf-ipcountry")
            or None
        )
        ua = request.headers.get("user-agent", "")
        ua_info = _parse_user_agent(ua)

        def _clip(v, n):
            return v[:n] if isinstance(v, str) else v

        row = WebEvent(
            event_type=(payload.get("event_type") or "pageview")[:50],
            event_name=_clip(payload.get("event_name"), 120),
            path=_clip(payload.get("path"), 1024),
            referrer=_clip(payload.get("referrer"), 1024),
            utm_source=_clip(payload.get("utm_source"), 255),
            utm_medium=_clip(payload.get("utm_medium"), 255),
            utm_campaign=_clip(payload.get("utm_campaign"), 255),
            visitor_id=_clip(payload.get("visitor_id"), 64),
            session_id=_clip(payload.get("session_id"), 64),
            device_type=ua_info["device_type"],
            browser=ua_info["browser"],
            os=ua_info["os"],
            locale=_clip(payload.get("locale"), 20),
            timezone=_clip(payload.get("timezone"), 64),
            country=_clip(country, 8),
            ip_hash=_hash_ip(client_ip),
            user_agent=_clip(ua, 1000),
            locale_url=_clip(payload.get("url"), 1024),
        )
        db.add(row)
        db.commit()
        return {"ok": True}
    except Exception as e:
        db.rollback()
        logger.error(f"Error ingesting pageview: {e}")
        # Beacon должен быть «тихим» — не отдаём 500, чтобы не плодить ошибки в консоли клиента.
        return {"ok": False}


@app.get("/api/monitoring/analytics")
async def get_analytics(days: int = 30, db: Session = Depends(get_db)):
    """Агрегаты посещаемости сайта за период + воронка по существующим данным."""
    days = max(1, min(days, 365))
    cutoff = datetime.utcnow() - timedelta(days=days)
    base = db.query(WebEvent).filter(
        WebEvent.created_at >= cutoff,
        WebEvent.event_type == "pageview",
    )

    pageviews = base.count()
    unique_visitors = (
        db.query(func.count(func.distinct(WebEvent.visitor_id)))
        .filter(WebEvent.created_at >= cutoff, WebEvent.event_type == "pageview")
        .scalar()
    ) or 0
    sessions = (
        db.query(func.count(func.distinct(WebEvent.session_id)))
        .filter(WebEvent.created_at >= cutoff, WebEvent.event_type == "pageview")
        .scalar()
    ) or 0

    def _top(column, limit=10):
        rows = (
            db.query(column, func.count(WebEvent.id).label("c"))
            .filter(WebEvent.created_at >= cutoff, WebEvent.event_type == "pageview", column.isnot(None))
            .group_by(column)
            .order_by(func.count(WebEvent.id).desc())
            .limit(limit)
            .all()
        )
        return [{"key": r[0], "count": int(r[1])} for r in rows]

    # Таймсерия по дням (через date())
    ts_rows = (
        db.query(
            func.date(WebEvent.created_at).label("d"),
            func.count(WebEvent.id).label("views"),
            func.count(func.distinct(WebEvent.visitor_id)).label("visitors"),
        )
        .filter(WebEvent.created_at >= cutoff, WebEvent.event_type == "pageview")
        .group_by(func.date(WebEvent.created_at))
        .order_by(func.date(WebEvent.created_at))
        .all()
    )
    timeseries = [
        {"date": str(r[0]), "views": int(r[1]), "visitors": int(r[2])} for r in ts_rows
    ]

    # Источники: utm_source, иначе домен реферера, иначе "direct"
    sources = _top(WebEvent.utm_source)

    # Воронка: визиты → запущенные ресёрчи → оценки (по тем же датам)
    researches = (
        db.query(func.count(ResearchReport.id))
        .filter(ResearchReport.created_at >= cutoff)
        .scalar()
    ) or 0
    ratings = (
        db.query(func.count(UserRating.id))
        .filter(UserRating.created_at >= cutoff)
        .scalar()
    ) or 0

    return {
        "period_days": days,
        "totals": {
            "pageviews": pageviews,
            "unique_visitors": int(unique_visitors),
            "sessions": int(sessions),
        },
        "timeseries": timeseries,
        "top_pages": _top(WebEvent.path),
        "top_sources": sources,
        "top_referrers": _top(WebEvent.referrer),
        "devices": _top(WebEvent.device_type, 5),
        "browsers": _top(WebEvent.browser, 6),
        "countries": _top(WebEvent.country, 10),
        "funnel": {
            "visitors": int(unique_visitors),
            "sessions": int(sessions),
            "researches": int(researches),
            "ratings": int(ratings),
        },
    }


@app.get("/api/monitoring/user-stats")
async def get_user_stats():
    """
    Прокси к user-service /api/stats/public (агрегаты регистраций).
    Токен хранится на сервере мониторинга и не попадает в браузер.
    """
    import httpx
    base = (config.USER_SERVICE_URL or "").rstrip("/")
    token = config.USER_SERVICE_STATS_TOKEN
    if not base or not token:
        return {"configured": False}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{base}/api/stats/public",
                headers={"X-Stats-Token": token},
            )
        if resp.status_code != 200:
            return {"configured": True, "error": f"HTTP {resp.status_code}"}
        return {"configured": True, "stats": resp.json()}
    except Exception as e:
        logger.error(f"Error fetching user-service stats: {e}")
        return {"configured": True, "error": str(e)}


# ============================================================
# GEO Visibility — AI bot crawl tracking
# ============================================================

# Known AI crawler patterns: (display_name, ua_substring_lowercase)
_AI_BOT_PATTERNS = [
    ("GPTBot",            "gptbot"),
    ("OAI-SearchBot",     "oai-searchbot"),
    ("ChatGPT-User",      "chatgpt-user"),
    ("PerplexityBot",     "perplexitybot"),
    ("Perplexity-User",   "perplexity-user"),
    ("ClaudeBot",         "claudebot"),
    ("Claude-User",       "claude-user"),
    ("Claude-SearchBot",  "claude-searchbot"),
    ("anthropic-ai",      "anthropic-ai"),
    ("Google-Extended",   "google-extended"),
    ("CCBot",             "ccbot"),
    ("Applebot-Extended", "applebot-extended"),
    ("Meta-ExternalAgent","meta-externalagent"),
    ("Gemini",            "google-inspectiontool"),
]

def _detect_bot(ua: str) -> Optional[str]:
    """Возвращает имя AI-бота или None если UA не совпадает."""
    if not ua:
        return None
    u = ua.lower()
    for name, pattern in _AI_BOT_PATTERNS:
        if pattern in u:
            return name
    return None


@app.post("/api/monitoring/bot-crawl")
async def ingest_bot_crawl(payload: dict, db: Session = Depends(get_db)):
    """
    Fire-and-forget ingest: фронт (Next.js middleware) сообщает о визите AI-краулера.
    Требует X-Ingest-Token. Не блокирует ответ пользователю.

    Тело: { bot_name, bot_raw_ua?, url_path, crawled_at? }
    """
    bot_name = (payload.get("bot_name") or "").strip()
    url_path  = (payload.get("url_path") or "").strip()
    if not bot_name or not url_path:
        raise HTTPException(status_code=400, detail="bot_name and url_path are required")

    crawled_at = _parse_iso(payload.get("crawled_at")) or datetime.utcnow()

    try:
        db.add(BotCrawlEvent(
            bot_name=bot_name,
            bot_raw_ua=payload.get("bot_raw_ua"),
            url_path=url_path,
            crawled_at=crawled_at,
        ))
        db.commit()
        return {"ok": True}
    except Exception as e:
        db.rollback()
        logger.error(f"bot-crawl ingest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Статьи блога с датами публикации (для расчёта time-to-first-crawl)
_BLOG_POSTS = {
    "/blog/milan-coffee-shop-market-2026":                          "2026-07-26",
    "/blog/financial-stress-test-5-metrics":                       "2026-07-26",
    "/blog/online-english-school-market-2026-competitor-analysis":  "2026-08-14",
}


@app.get("/api/monitoring/visibility/bot-crawls")
async def get_bot_crawls(
    days: int = 90,
    db: Session = Depends(get_db),
):
    """
    GEO Visibility — аналитика AI-краулеров:
    - recent_events: последние 100 событий
    - by_bot: сколько визитов от каждого бота
    - by_page: какие страницы, кто посещал, когда впервые
    - recommendations: что сделать чтобы улучшить охват
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    events = (
        db.query(BotCrawlEvent)
        .filter(BotCrawlEvent.crawled_at >= cutoff)
        .order_by(BotCrawlEvent.crawled_at.desc())
        .limit(200)
        .all()
    )

    # --- by_bot ---
    bot_counts: dict[str, int] = {}
    for e in events:
        bot_counts[e.bot_name] = bot_counts.get(e.bot_name, 0) + 1

    # --- by_page ---
    page_map: dict[str, dict] = {}
    for e in events:
        p = e.url_path
        if p not in page_map:
            page_map[p] = {"path": p, "bots": set(), "count": 0, "first_crawl": e.crawled_at, "last_crawl": e.crawled_at}
        page_map[p]["bots"].add(e.bot_name)
        page_map[p]["count"] += 1
        if e.crawled_at < page_map[p]["first_crawl"]:
            page_map[p]["first_crawl"] = e.crawled_at
        if e.crawled_at > page_map[p]["last_crawl"]:
            page_map[p]["last_crawl"] = e.crawled_at

    # Обогащаем страницы датой публикации и time_to_first_crawl_days
    for path, info in page_map.items():
        pub = _BLOG_POSTS.get(path)
        info["published_at"] = pub
        if pub:
            pub_dt = datetime.strptime(pub, "%Y-%m-%d")
            delta = (info["first_crawl"] - pub_dt).days
            info["days_to_first_crawl"] = max(0, delta)
        else:
            info["days_to_first_crawl"] = None
        info["bots"] = sorted(info["bots"])
        info["first_crawl"] = info["first_crawl"].isoformat()
        info["last_crawl"] = info["last_crawl"].isoformat()

    # --- recommendations ---
    recommendations = []
    crawled_paths = set(page_map.keys())
    for path, pub in _BLOG_POSTS.items():
        if path not in crawled_paths:
            pub_dt = datetime.strptime(pub, "%Y-%m-%d")
            age_days = (datetime.utcnow() - pub_dt).days
            if age_days >= 7:
                recommendations.append({
                    "type": "not_crawled",
                    "severity": "warning" if age_days < 30 else "critical",
                    "path": path,
                    "published_at": pub,
                    "age_days": age_days,
                    "action": "Submit to Bing IndexNow and share on LinkedIn to attract AI-bot discovery.",
                })
        else:
            info = page_map[path]
            if info["days_to_first_crawl"] is not None and info["days_to_first_crawl"] > 14:
                recommendations.append({
                    "type": "slow_discovery",
                    "severity": "info",
                    "path": path,
                    "days_to_first_crawl": info["days_to_first_crawl"],
                    "action": "Discovery took over 2 weeks — add IndexNow or increase inbound links.",
                })
            known_bots = {"GPTBot", "OAI-SearchBot", "PerplexityBot", "ClaudeBot"}
            missing = known_bots - set(info["bots"])
            if missing:
                recommendations.append({
                    "type": "missing_bots",
                    "severity": "info",
                    "path": path,
                    "missing_bots": sorted(missing),
                    "action": f"Not yet crawled by {', '.join(sorted(missing))}. Check robots.txt allows these bots.",
                })

    if not bot_counts:
        recommendations.insert(0, {
            "type": "no_data",
            "severity": "warning",
            "action": "No AI bot crawl events yet. Deploy the middleware bot-detection to start collecting data.",
        })

    return {
        "period_days": days,
        "total_events": len(events),
        "by_bot": bot_counts,
        "by_page": list(page_map.values()),
        "recommendations": recommendations,
        "recent_events": [
            {
                "bot_name": e.bot_name,
                "url_path": e.url_path,
                "crawled_at": e.crawled_at.isoformat(),
            }
            for e in events[:100]
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
