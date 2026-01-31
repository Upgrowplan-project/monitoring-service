"""
API endpoints для работы с оценками пользователей
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Optional
import logging
import io
import csv

from monitoring import get_db
from monitoring.models import UserRating, RatingAnalytics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ratings"])


@router.post("/rating")
async def submit_rating(
    request: Request,
    rating_data: dict,
    db: Session = Depends(get_db)
):
    """
    Прием оценки от пользователя
    """
    try:
        # Получаем IP и User-Agent
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")
        
        # Создаем запись
        rating = UserRating(
            session_id=rating_data.get("session_id"),
            clarity=rating_data.get("clarity"),
            usefulness=rating_data.get("usefulness"),
            accuracy=rating_data.get("accuracy"),
            usability=rating_data.get("usability"),
            speed=rating_data.get("speed"),
            design=rating_data.get("design"),
            overall_rating=rating_data.get("overall"),
            recommend=rating_data.get("recommend"),
            price=rating_data.get("price"),
            feedback=rating_data.get("feedback"),
            user_ip=client_ip,
            user_agent=user_agent,
            page_url=rating_data.get("page_url"),
            service_name=rating_data.get("service_name", "general")
        )
        
        db.add(rating)
        db.commit()
        db.refresh(rating)
        
        logger.info(f"New rating received: {rating.id} from session {rating.session_id}")
        
        return {
            "success": True,
            "id": rating.id,
            "message": "Rating saved successfully"
        }
        
    except Exception as e:
        logger.error(f"Error saving rating: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ratings/stats")
async def get_ratings_stats(
    service_name: Optional[str] = None,
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Получение статистики оценок
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    query = db.query(UserRating).filter(UserRating.created_at >= cutoff)
    
    if service_name:
        query = query.filter(UserRating.service_name == service_name)
    
    ratings = query.all()
    
    if not ratings:
        return {
            "total_ratings": 0,
            "averages": {},
            "nps": 0,
            "distribution": {},
            "recent_feedback": []
        }
    
    # Вычисляем средние
    def safe_avg(values):
        filtered = [v for v in values if v is not None]
        return round(sum(filtered) / len(filtered), 2) if filtered else 0
    
    averages = {
        "clarity": safe_avg([r.clarity for r in ratings]),
        "usefulness": safe_avg([r.usefulness for r in ratings]),
        "accuracy": safe_avg([r.accuracy for r in ratings]),
        "usability": safe_avg([r.usability for r in ratings]),
        "speed": safe_avg([r.speed for r in ratings]),
        "design": safe_avg([r.design for r in ratings]),
        "overall": safe_avg([r.overall_rating for r in ratings]),
        "recommend": safe_avg([r.recommend for r in ratings]),
        "price": safe_avg([r.price for r in ratings])
    }
    
    # NPS (Net Promoter Score)
    recommend_scores = [r.recommend for r in ratings if r.recommend is not None]
    if recommend_scores:
        promoters = len([s for s in recommend_scores if s >= 4])
        detractors = len([s for s in recommend_scores if s <= 2])
        nps = ((promoters - detractors) / len(recommend_scores)) * 100
    else:
        nps = 0
    
    # Распределение оценок
    overall_scores = [r.overall_rating for r in ratings if r.overall_rating is not None]
    distribution = {i: overall_scores.count(i) for i in range(1, 6)}
    
    return {
        "period_days": days,
        "total_ratings": len(ratings),
        "averages": averages,
        "nps": round(nps, 2),
        "distribution": distribution,
        "recent_feedback": [
            {
                "id": r.id,
                "overall": r.overall_rating,
                "feedback": r.feedback,
                "service_name": r.service_name,
                "created_at": r.created_at.isoformat()
            }
            for r in sorted(ratings, key=lambda x: x.created_at, reverse=True)[:10]
            if r.feedback
        ]
    }


@router.get("/ratings/export")
async def export_ratings(
    format: str = "json",
    service_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Экспорт данных оценок для анализа
    """
    from fastapi.responses import StreamingResponse
    
    query = db.query(UserRating)
    
    if service_name:
        query = query.filter(UserRating.service_name == service_name)
    
    if start_date:
        query = query.filter(UserRating.created_at >= datetime.fromisoformat(start_date))
    
    if end_date:
        query = query.filter(UserRating.created_at <= datetime.fromisoformat(end_date))
    
    ratings = query.order_by(UserRating.created_at.desc()).all()
    
    data = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "clarity": r.clarity,
            "usefulness": r.usefulness,
            "accuracy": r.accuracy,
            "usability": r.usability,
            "speed": r.speed,
            "design": r.design,
            "overall_rating": r.overall_rating,
            "recommend": r.recommend,
            "price": r.price,
            "feedback": r.feedback,
            "service_name": r.service_name,
            "created_at": r.created_at.isoformat(),
            "user_ip": r.user_ip,
            "page_url": r.page_url
        }
        for r in ratings
    ]
    
    if format == "csv":
        # Конвертация в CSV
        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=ratings_export.csv"}
        )
    
    return {"ratings": data}


@router.get("/ratings/timeline")
async def get_ratings_timeline(
    service_name: Optional[str] = None,
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Получение временной шкалы оценок (для графиков)
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    query = db.query(
        func.date(UserRating.created_at).label('date'),
        func.avg(UserRating.overall_rating).label('avg_rating'),
        func.count(UserRating.id).label('count')
    ).filter(UserRating.created_at >= cutoff)
    
    if service_name:
        query = query.filter(UserRating.service_name == service_name)
    
    timeline = query.group_by(func.date(UserRating.created_at)).all()
    
    return {
        "period_days": days,
        "data_points": [
            {
                "date": str(t.date),
                "avg_rating": round(float(t.avg_rating), 2) if t.avg_rating else 0,
                "count": t.count
            }
            for t in timeline
        ]
    }


@router.get("/ratings/services")
async def get_services_ratings(
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Получение статистики по всем сервисам
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    services_stats = db.query(
        UserRating.service_name,
        func.count(UserRating.id).label('total'),
        func.avg(UserRating.overall_rating).label('avg_rating')
    ).filter(
        UserRating.created_at >= cutoff,
        UserRating.service_name.isnot(None)
    ).group_by(UserRating.service_name).all()
    
    return {
        "period_days": days,
        "services": [
            {
                "service_name": s.service_name,
                "total_ratings": s.total,
                "avg_rating": round(float(s.avg_rating), 2) if s.avg_rating else 0
            }
            for s in services_stats
        ]
    }
