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


class SynthesisLog(Base):
    """
    Этапные логи генерации (пайплайн-логи) от сервисов.

    Исторически таблица создавалась неявно через INSERT из social-plan-master.
    Объявляем модель явно, чтобы init_db() гарантированно создавал таблицу и
    её могли наполнять любые сервисы (social-plan-master, market-research-service).
    """
    __tablename__ = "synthesis_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(255), nullable=False, index=True)
    service_name = Column(String(100), nullable=True, index=True)
    environment = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    level = Column(String(20), nullable=True)          # INFO|WARNING|ERROR
    source = Column(String(100), nullable=True)        # backend|deep-research-agent|...
    stage = Column(String(255), nullable=True)
    progress = Column(Float, nullable=True)
    message = Column(Text, nullable=True)
    payload_json = Column(JSON, nullable=True)

    def __repr__(self):
        return f"<SynthesisLog(session={self.session_id}, level={self.level})>"


class ResearchReport(Base):
    """
    Готовые отчёты сервисов генерации (market-research-service и др.) для анализа.

    Хранит вход запроса тестера + полный JSON отчёта, чтобы документы переживали
    эфемерную ФС/TTL Redis сервиса-источника. session_id == research_id связывает
    запись с UserRating (оценкой тестера).
    """
    __tablename__ = "research_reports"

    id = Column(Integer, primary_key=True, index=True)
    research_id = Column(String(255), unique=True, nullable=False, index=True)
    service_name = Column(String(100), nullable=True, index=True, default="market-research-service")

    # Краткие поля запроса (для списка/фильтра без парсинга JSON)
    product_name = Column(String(512), nullable=True)
    country = Column(String(255), nullable=True)
    region = Column(String(255), nullable=True)
    business_type = Column(String(100), nullable=True)
    product_type = Column(String(100), nullable=True)
    industry = Column(String(255), nullable=True)
    localization = Column(String(50), nullable=True)
    report_language = Column(String(10), nullable=True)

    status = Column(String(50), nullable=True, default="completed", index=True)
    duration_seconds = Column(Float, nullable=True)

    # Полные данные
    request_json = Column(JSON, nullable=True)   # вход запроса тестера
    report_json = Column(JSON, nullable=True)    # полный enhanced-отчёт

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<ResearchReport(research_id={self.research_id}, product={self.product_name})>"


class WebEvent(Base):
    """
    Событие посещаемости сайта (pageview / кастомное событие) от beacon фронта.

    Анонимно: visitor_id/session_id — случайные id из localStorage/sessionStorage,
    ip хранится только как хэш. Используется для агрегатов посещаемости и воронки.
    """
    __tablename__ = "web_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50), nullable=False, default="pageview", index=True)  # pageview|event
    event_name = Column(String(120), nullable=True)  # для кастомных событий

    path = Column(String(1024), nullable=True, index=True)
    referrer = Column(String(1024), nullable=True)
    utm_source = Column(String(255), nullable=True, index=True)
    utm_medium = Column(String(255), nullable=True)
    utm_campaign = Column(String(255), nullable=True)

    visitor_id = Column(String(64), nullable=True, index=True)   # анонимный, localStorage
    session_id = Column(String(64), nullable=True, index=True)   # анонимный, sessionStorage

    device_type = Column(String(20), nullable=True)   # mobile|tablet|desktop
    browser = Column(String(50), nullable=True)
    os = Column(String(50), nullable=True)
    locale = Column(String(20), nullable=True)
    timezone = Column(String(64), nullable=True)
    country = Column(String(8), nullable=True, index=True)  # если придёт из заголовков прокси

    ip_hash = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    locale_url = Column(String(1024), nullable=True)  # полный URL (для отладки)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<WebEvent(type={self.event_type}, path={self.path})>"


class SearchMetric(Base):
    """
    Visibility Monitor V1 — реальные метрики поиска (Google Search Console + Bing).

    Идемпотентно: при каждом скане строки для источника ПОЛНОСТЬЮ заменяются
    свежим окном (историю по дням отдают сами API GSC/Bing, мы не накапливаем).
    dimension:
      - "total" → дневной ряд (key=NULL, date=день метрики)
      - "query" → топ-запросы за окно (key=текст запроса, date=конец окна)
      - "page"  → топ-страницы за окно (key=URL страницы)
    """
    __tablename__ = "search_metrics"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(20), nullable=False, index=True)      # google | bing
    date = Column(DateTime, nullable=False, index=True)          # день метрики / конец окна (UTC)
    dimension = Column(String(20), nullable=False, index=True)   # total | query | page
    key = Column(String(1024), nullable=True)                    # запрос/URL; NULL для total

    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)
    position = Column(Float, nullable=True)

    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<SearchMetric(source={self.source}, dim={self.dimension}, date={self.date})>"


class GeoCheck(Base):
    """Результат проверки видимости бренда в ответах нейросетей (GEO Visibility)."""
    __tablename__ = "geo_checks"

    id = Column(Integer, primary_key=True, index=True)
    llm = Column(String(50), nullable=False, index=True)   # gemini|chatgpt|perplexity|manual
    query = Column(Text, nullable=False)
    response_text = Column(Text, nullable=True)
    mentioned = Column(Boolean, nullable=False, default=False)
    position = Column(String(20), nullable=True)           # early|middle|late
    excerpt = Column(Text, nullable=True)
    auto = Column(Boolean, default=True, nullable=False)   # True=автоматически, False=вручную
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<GeoCheck(llm={self.llm}, mentioned={self.mentioned}, created_at={self.created_at})>"


class BotCrawlEvent(Base):
    """
    Событие сканирования AI-ботом (GPTBot, PerplexityBot, ClaudeBot и др.).
    Пишется fire-and-forget из Next.js middleware при каждом визите AI-краулера.
    Используется для GEO Visibility: какие страницы индексируют AI, как быстро,
    кто именно — основа для рекомендаций growth agent.
    """
    __tablename__ = "bot_crawl_events"

    id = Column(Integer, primary_key=True, index=True)
    bot_name = Column(String(100), nullable=False, index=True)   # GPTBot | PerplexityBot | ClaudeBot | ...
    bot_raw_ua = Column(Text, nullable=True)                     # полный User-Agent
    url_path = Column(String(1024), nullable=False, index=True)  # /blog/xxx
    crawled_at = Column(DateTime, nullable=False, index=True)    # время визита (UTC)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<BotCrawlEvent(bot={self.bot_name}, path={self.url_path}, at={self.crawled_at})>"


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
