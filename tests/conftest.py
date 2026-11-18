"""[15.11 · владелец «1-3»: на проде запись res_test_artifact без отчёта и логов] Тесты Monitoring — только во временной базе.

Было: test_geo_scan.py собирается раньше и импортирует monitoring.tasks → monitoring.database создаёт подключение по адресу
из .env (рабочая база на проде); test_my_report_artifact.py подменял DATABASE_URL позже — подключение уже создано, тестовая
запись ушла в рабочую базу. conftest.py загружается до сбора любого теста: адрес базы подменяется здесь, а защита ниже
останавливает весь запуск, если подключение всё же смотрит не на временную базу (ничего не пишется)."""
import os
import tempfile
from pathlib import Path

import pytest

_TEST_DB = Path(tempfile.mkdtemp(prefix="mon_tests_")) / "t.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"


@pytest.fixture(scope="session", autouse=True)
def _only_temporary_database():
    from monitoring.database import engine
    if engine.url.get_backend_name() != "sqlite" or Path(engine.url.database or "") != _TEST_DB:
        pytest.exit(f"тесты Monitoring подключены не к временной базе ({engine.url.get_backend_name()}, "
                    f"{engine.url.host or engine.url.database}) — запуск остановлен, ничего не записано", returncode=3)
    yield
