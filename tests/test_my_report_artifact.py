"""[09.11 · бета-тестер 2, прод res_8b35e517416a: 3 × 403 missing_snapshot у сервиса исследований] Страница исследования берёт
DOCX из Monitoring, когда сервис его уже не отдаёт (запись 4 ч, сон сервера). Маршрут /api/monitoring/my-reports/{id}/artifact:
владельцу — тот же документ, что сервис прислал по завершении; чужому — 404; без входа — 401. Офлайн, временная SQLite
(адрес базы задаёт tests/conftest.py до сбора тестов; 15.11 — здесь задавался поздно, и запись ушла в рабочую базу)."""
import os
import sys
import time
from pathlib import Path

os.environ["JWT_SECRET"] = "test-secret-my-report-artifact"
os.environ.setdefault("MONITORING_INGEST_TOKEN", "test-ingest")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _token(email, role="BETA_TESTER"):
    return jwt.encode({"sub": email, "role": role, "exp": int(time.time()) + 600}, os.environ["JWT_SECRET"], algorithm="HS512")


def test_owner_gets_saved_docx_others_do_not():
    import main
    from monitoring.database import Base, engine, SessionLocal
    from monitoring.models import ResearchReport
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.add(ResearchReport(research_id="res_test_artifact", service_name="market-research-service",
                          owner_email="tester@example.com", artifact_docx=b"PK\x03\x04docx-bytes",
                          artifact_filename="res_test_artifact_report.docx"))
    db.commit()
    db.close()
    c = TestClient(main.app)
    url = "/api/monitoring/my-reports/res_test_artifact/artifact"
    r = c.get(url, headers={"Authorization": f"Bearer {_token('tester@example.com')}"})
    assert r.status_code == 200 and r.content == b"PK\x03\x04docx-bytes"
    assert "wordprocessingml" in r.headers.get("content-type", "")
    assert c.get(url, headers={"Authorization": f"Bearer {_token('other@example.com')}"}).status_code == 404
    assert c.get(url).status_code == 401
    # регистр почты в токене не мешает владельцу
    assert c.get(url, headers={"Authorization": f"Bearer {_token('Tester@Example.com')}"}).status_code == 200
