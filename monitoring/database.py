from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
from .config import get_config
from .models import Base

# Получаем конфигурацию
config = get_config()

# Создаем engine.
# Маленький пул: Heroku essential-0 Postgres держит ~20 коннектов, а при деплое
# старый и новый дайно на секунды пересекаются. Ограничиваем приложение ~5
# коннектами (pool_size 3 + overflow 2), чтобы два инстанса (=10) не упирались в
# лимит "too many connections". pool_recycle закрывает простаивающие соединения.
engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=5,
    pool_recycle=280,
    echo=False,  # Установить True для отладки SQL запросов
)

# Создаем SessionLocal
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Инициализация базы данных - создание всех таблиц"""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Dependency для FastAPI"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session():
    """Context manager для работы с БД"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
