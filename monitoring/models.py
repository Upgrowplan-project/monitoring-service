from sqlalchemy import Column, String, Integer, DateTime, Float, Boolean, JSON, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class ServiceHealth(Base):
    """Метрики здоровья сервисов"""
    __tablename__ = "service_health"
    
    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String(255), index=True, nullable=False)
    service_type = Column(String(50), nullable=False)  # vercel, heroku, api_key, database
    status = Column(String(20), nullable=False)  # healthy, degraded, down
    response_time = Column(Float, nullable=True)  # в секундах
    last_checked = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    additional_info = Column(JSON, nullable=True)
    
    def __repr__(self):
        return f"<ServiceHealth(service={self.service_name}, status={self.status})>"


class UserActivity(Base):
    """Активность пользователей"""
    __tablename__ = "user_activity"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    active_users = Column(Integer, default=0)
    total_requests = Column(Integer, default=0)
    avg_response_time = Column(Float, default=0.0)
    endpoint = Column(String(255), nullable=True)
    
    def __repr__(self):
        return f"<UserActivity(timestamp={self.timestamp}, users={self.active_users})>"


class SystemAlert(Base):
    """Системные алерты"""
    __tablename__ = "system_alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    severity = Column(String(20), nullable=False)  # info, warning, critical
    service_name = Column(String(255), nullable=False, index=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    resolved = Column(Boolean, default=False, nullable=False, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(255), nullable=True)
    
    def __repr__(self):
        return f"<SystemAlert(service={self.service_name}, severity={self.severity}, resolved={self.resolved})>"


class APIUsageMetrics(Base):
    """Метрики использования API"""
    __tablename__ = "api_usage_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    api_name = Column(String(100), nullable=False, index=True)  # openai, anthropic, etc.
    requests_count = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    errors_count = Column(Integer, default=0)
    
    def __repr__(self):
        return f"<APIUsageMetrics(api={self.api_name}, requests={self.requests_count})>"


class UserRating(Base):
    """Оценки пользователей сервиса"""
    __tablename__ = "user_ratings"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(255), nullable=False, index=True)
    
    # Оценки по критериям (1-5)
    clarity = Column(Integer, nullable=True)
    usefulness = Column(Integer, nullable=True)
    accuracy = Column(Integer, nullable=True)
    usability = Column(Integer, nullable=True)
    speed = Column(Integer, nullable=True)
    design = Column(Integer, nullable=True)
    overall_rating = Column(Integer, nullable=True)
    recommend = Column(Integer, nullable=True)
    
    # Дополнительные данные
    price = Column(Integer, nullable=True)  # Готовность платить
    feedback = Column(Text, nullable=True)  # Текстовый отзыв
    
    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_ip = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    page_url = Column(String(500), nullable=True)  # Откуда оставлен отзыв
    
    # Дополнительная информация
    service_name = Column(String(100), nullable=True, index=True)  # Какой сервис оценивали
    
    def __repr__(self):
        return f"<UserRating(session={self.session_id}, overall={self.overall_rating})>"


class RatingAnalytics(Base):
    """Агрегированная аналитика оценок"""
    __tablename__ = "rating_analytics"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, index=True)
    service_name = Column(String(100), nullable=True, index=True)
    
    # Средние оценки
    avg_clarity = Column(Float, default=0.0)
    avg_usefulness = Column(Float, default=0.0)
    avg_accuracy = Column(Float, default=0.0)
    avg_usability = Column(Float, default=0.0)
    avg_speed = Column(Float, default=0.0)
    avg_design = Column(Float, default=0.0)
    avg_overall = Column(Float, default=0.0)
    avg_recommend = Column(Float, default=0.0)
    
    # Статистика
    total_ratings = Column(Integer, default=0)
    nps_score = Column(Float, default=0.0)  # Net Promoter Score
    avg_price = Column(Float, default=0.0)
    
    # Распределение оценок
    rating_distribution = Column(JSON, nullable=True)  # {1: 5, 2: 10, 3: 20, ...}
    
    def __repr__(self):
        return f"<RatingAnalytics(date={self.date}, avg={self.avg_overall})>"


class Email(Base):
    """Модель для хранения входящих и исходящих писем"""
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String(255), unique=True, nullable=True, index=True)
    thread_id = Column(String(255), nullable=True, index=True)
    direction = Column(String(20), nullable=False, index=True)  # inbound|outbound
    source = Column(String(50), nullable=True)  # imap|contact_form|api

    subject = Column(String(512), nullable=True)
    from_addr = Column(String(512), nullable=True)
    to_addr = Column(String(1024), nullable=True)
    cc = Column(String(1024), nullable=True)
    bcc = Column(String(1024), nullable=True)

    body_text = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)

    received_at = Column(DateTime, nullable=True, index=True)
    sent_at = Column(DateTime, nullable=True)

    status = Column(String(20), default="new", nullable=False, index=True)  # new|read|archived
    metadata_json = Column(JSON, nullable=True)
    raw_headers = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<Email(id={self.id}, subject={self.subject}, from={self.from_addr})>"


class EmailAttachment(Base):
    """Метаданные вложений"""
    __tablename__ = "email_attachments"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, nullable=False, index=True)
    filename = Column(String(512), nullable=True)
    content_type = Column(String(255), nullable=True)
    size = Column(Integer, nullable=True)
    path = Column(String(1024), nullable=True)  # путь к файлу на диске или URL
    metadata_json = Column(JSON, nullable=True)

    def __repr__(self):
        return f"<EmailAttachment(email_id={self.email_id}, filename={self.filename})>"
