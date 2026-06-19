# Upgrowplan Monitoring System

Система мониторинга здоровья всех сервисов Upgrowplan в реальном времени.

## 📋 Возможности

- ✅ **Мониторинг Vercel deployments** - отслеживание статуса фронтенда
- ✅ **Мониторинг Heroku apps** - проверка всех backend сервисов
- ✅ **Мониторинг API ключей** - OpenAI и другие API
- ✅ **Real-time обновления** - WebSocket для живых данных
- ✅ **Система алертов** - Email и Telegram уведомления
- ✅ **История метрик** - графики производительности
- ✅ **Активность пользователей** - статистика использования

## 🏗️ Архитектура

```
├── Backend (Python + FastAPI)
│   ├── Health Checkers (проверки сервисов)
│   ├── Celery Tasks (периодические задачи)
│   ├── WebSocket Server (real-time)
│   └── REST API
├── Frontend (React + TypeScript + Bootstrap)
│   └── Admin Dashboard
├── Database (PostgreSQL)
│   └── Метрики и алерты
└── Redis (Celery broker)
```

## 🚀 Быстрый старт

### 1. Клонирование и настройка

```bash
# Клонируйте проект
cd monitoring-system

# Создайте .env файл из примера
cp .env.example .env

# Заполните .env файл вашими реальными данными
nano .env
```

### 2. Настройка переменных окружения

Отредактируйте `.env` файл и укажите:

```env
# Vercel (получить на vercel.com/account/tokens)
VERCEL_TOKEN=your_actual_token
VERCEL_PROJECT_ID=your_project_id

# Heroku (получить на heroku.com/account)
HEROKU_API_KEY=your_actual_key
HEROKU_APP_NAMES=["upgrowplan-api", "upgrowplan-worker"]

# OpenAI
OPENAI_API_KEY=sk-...

# Email для алертов
ADMIN_EMAIL=your@email.com
SMTP_HOST=smtp.gmail.com
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your_app_password
```

### 3. Запуск с Docker Compose

```bash
# Запустить все сервисы
docker-compose up -d

# Проверить логи
docker-compose logs -f

# Остановить
docker-compose down
```

### 4. Инициализация базы данных

```bash
# Войти в контейнер backend
docker exec -it upgrowplan_monitoring_backend bash

# Создать таблицы
python -c "from monitoring.database import init_db; init_db()"

# Выйти
exit
```

### 5. Доступ к системе

- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Frontend**: Интегрировать в ваш основной фронтенд

## 📦 Локальная разработка (без Docker)

### Backend

```bash
cd backend

# Создать виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# Установить зависимости
pip install -r requirements.txt

# Запустить PostgreSQL и Redis локально
# или использовать docker-compose только для БД:
docker-compose up -d postgres redis

# Создать таблицы
python -c "from monitoring.database import init_db; init_db()"

# Запустить FastAPI server
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# В отдельном терминале: Celery Worker
celery -A monitoring.tasks worker --loglevel=info

# В отдельном терминале: Celery Beat
celery -A monitoring.tasks beat --loglevel=info
```

### Frontend

```bash
cd frontend

# Установить зависимости
npm install

# Запустить dev server
npm start

# Билд для продакшена
npm run build
```

## 🔧 Интеграция с вашим фронтендом

### 1. Добавление маршрута

В вашем React Router добавьте:

```tsx
import { MonitoringDashboard } from './pages/MonitoringDashboard';

// В роутере
<Route path="/account/monitor" element={<MonitoringDashboard />} />
```

### 2. Защита маршрута

Добавьте проверку admin прав:

```tsx
<Route 
  path="/account/monitor" 
  element={
    <ProtectedRoute requireAdmin>
      <MonitoringDashboard />
    </ProtectedRoute>
  } 
/>
```

## 📊 API Endpoints

### Получить overview

```bash
GET /api/monitoring/overview
```

### Получить историю сервиса

```bash
GET /api/monitoring/service/{service_name}/history?hours=24
```

### Trigger проверку вручную

```bash
POST /api/monitoring/check-now
```

### Resolve alert

```bash
POST /api/monitoring/alerts/{alert_id}/resolve
```

### Получить статистику

```bash
GET /api/monitoring/stats
```

### Оценки пользователей (ratings)

```bash
POST /api/rating                 # приём оценки от фронта (RuGrade/EnGrade)
GET  /api/ratings/stats?service_name=&days=30
GET  /api/ratings/export?format=csv|json
GET  /api/ratings/services
```

### Письма (контакт-форма + IMAP)

```bash
POST /api/monitoring/contact
GET  /api/monitoring/emails
GET  /api/monitoring/emails/{id}
POST /api/monitoring/emails/{id}/reply
```

### Этапные логи генерации (synthesis_logs)

```bash
GET  /api/monitoring/synthesis-logs/sessions?service_name=
GET  /api/monitoring/synthesis-logs/{session_id}?service_name=
POST /api/monitoring/synthesis-logs     # батч-приём логов от сервисов-источников
```

### Отчёты сервисов генерации (research_reports) — НОВОЕ

Долговременное хранение готовых отчётов тестеров (market-research-service и др.),
чтобы документы переживали TTL Redis (4ч) и эфемерную ФС Heroku.

```bash
POST /api/monitoring/reports            # идемпотентный upsert по research_id
GET  /api/monitoring/reports?service_name=market-research-service&limit=50
GET  /api/monitoring/reports/{research_id}   # полный отчёт + вход запроса + логи + оценка
```

## 🔔 Настройка уведомлений

### Email (SMTP)

1. Для Gmail используйте App Password:
   - Перейдите в Google Account Security
   - Включите 2FA
   - Создайте App Password
   - Используйте его в `SMTP_PASSWORD`

### Telegram (опционально)

1. Создайте бота через [@BotFather](https://t.me/botfather)
2. Получите `TELEGRAM_BOT_TOKEN`
3. Получите ваш `TELEGRAM_CHAT_ID` через [@userinfobot](https://t.me/userinfobot)
4. Добавьте в `.env`

## 🎨 Кастомизация

### Добавление нового сервиса для мониторинга

В `backend/monitoring/health_checkers.py`:

```python
@staticmethod
async def check_your_service(api_key: str) -> Dict[str, Any]:
    # Ваша логика проверки
    return {
        "status": "healthy",
        "response_time": 0.5,
        "metadata": {...}
    }
```

В `backend/monitoring/tasks.py` добавьте вызов:

```python
your_service_result = await checker.check_your_service(config.YOUR_API_KEY)
results.append({
    "service_name": "Your Service",
    "service_type": "api_key",
    **your_service_result
})
```

### Изменение частоты проверок

В `backend/celeryconfig.py`:

```python
beat_schedule = {
    'check-all-services-every-5-minutes': {
        'task': 'monitoring.check_all_services',
        'schedule': 300.0,  # Измените на нужное значение в секундах
    },
}
```

## 📈 Деплой в продакшен

### Backend на Heroku

```bash
cd backend

# Создать app
heroku create upgrowplan-monitoring-api

# Добавить PostgreSQL
heroku addons:create heroku-postgresql:mini

# Добавить Redis
heroku addons:create heroku-redis:mini

# Установить переменные окружения
heroku config:set VERCEL_TOKEN=...
heroku config:set HEROKU_API_KEY=...
# и т.д.

# Деплой
git push heroku main

# Создать таблицы
heroku run python -c "from monitoring.database import init_db; init_db()"
```

### Frontend на Vercel

```bash
cd frontend

# Установить Vercel CLI
npm i -g vercel

# Деплой
vercel

# Установить env переменные
vercel env add REACT_APP_API_URL
vercel env add REACT_APP_WS_URL
```

## 🐛 Troubleshooting

### Backend не стартует

```bash
# Проверьте логи
docker-compose logs backend

# Убедитесь что PostgreSQL запущен
docker-compose ps postgres

# Проверьте подключение к БД
docker exec -it upgrowplan_monitoring_backend bash
psql $DATABASE_URL
```

### WebSocket не подключается

1. Проверьте что CORS настроен правильно в `main.py`
2. Убедитесь что `REACT_APP_WS_URL` использует правильный протокол:
   - `ws://` для HTTP
   - `wss://` для HTTPS

### Celery задачи не выполняются

```bash
# Проверьте Celery worker
docker-compose logs celery_worker

# Проверьте Celery beat
docker-compose logs celery_beat

# Перезапустите Celery
docker-compose restart celery_worker celery_beat
```

## 📊 Web-аналитика (посещаемость)

Собственный beacon → таблица `web_events` (анонимно, без cookie/PII; ip только хэшем).

```bash
POST /api/monitoring/pageview     # beacon с фронта (sendBeacon), без авторизации
GET  /api/monitoring/analytics?days=30   # агрегаты + воронка
```
Агрегаты: просмотры, уник. посетители, сессии, динамика по дням, топ страниц/источников/рефереров,
устройства, браузеры, страны (если прокси отдаёт гео-заголовок), воронка
(посетители → сессии → запущенные ресёрчи → оценки). Фронт: компонент `AnalyticsBeacon`
в корневом layout + вкладка «📈 Analytics».

## 📌 Состояние сервиса и журнал обновлений

**Деплой:** Heroku, web-дайно (`Procfile`: `web: uvicorn main:app --host 0.0.0.0 --port $PORT`).
**URL (prod):** `https://monitoring-service-b37530bd3b04.herokuapp.com`
**БД:** Heroku PostgreSQL. Таблицы создаются автоматически на старте (`init_db()` в `startup_event`).
**CORS:** `https://www.upgrowplan.com`, `https://upgrowplan.com`, `http://localhost:3000`.
**Фронт:** интегрирован в Next.js (`upgrowplan_new/app/[locale]/monitoring`), env `NEXT_PUBLIC_MONITORING_API_URL`.

### Текущие подсистемы
- ✅ Health-мониторинг сервисов (Vercel/Heroku/API) + алерты + WebSocket real-time.
- ✅ Оценки пользователей (`user_ratings`) — вкладка «⭐ Ratings».
- ✅ Письма (контакт-форма + IMAP, `emails`) — вкладка «✉️ Emails».
- ✅ Этапные логи генерации (`synthesis_logs`) — пишет social-plan-master.
- ✅ Quality Lab — вкладка «🧪 Quality Lab».

### Обновление 2026-06-18 — захват отчётов/логов market-research-service
Цель: ловить и долговременно хранить все отчёты и логи тестеров MRS для анализа.

- **Новые таблицы:** `research_reports` (вход запроса + полный JSON отчёта + метаданные),
  `synthesis_logs` теперь объявлена явной моделью (раньше создавалась неявно из social-plan-master),
  поэтому `init_db()` гарантированно её создаёт.
- **Новые эндпоинты:** `POST /api/monitoring/reports`, `POST /api/monitoring/synthesis-logs`,
  `GET /api/monitoring/reports`, `GET /api/monitoring/reports/{research_id}`.
- **Источник (market-research-service):** на завершении ресёрча шлёт отчёт + вход + логи по HTTP
  (env `MONITORING_API_URL`). Реализация fire-and-forget — НЕ влияет на пайплайн MRS.
- **Фронт:** новая вкладка «📄 Reports» в дашборде (список прогонов → отчёт + логи + оценка, скачивание JSON).
- **Связь с оценками:** `research_reports.research_id == user_ratings.session_id` — отчёт и оценка тестера сшиваются.

### Что нужно для активации
- На Heroku-приложении **MRS** задать `MONITORING_API_URL=https://monitoring-service-b37530bd3b04.herokuapp.com`.
- Перезапустить мониторинг (или вызвать `init_db()`), чтобы создались новые таблицы.

### Обновление 2026-06-19 — встроенный планировщик (фоновый слой)
**Проблема:** в проде только `web`-дайно (нет Celery worker/beat) → периодические
задачи (health-проверки, авто-очистка Redis, **забор почты с Zoho по IMAP**) не
выполнялись. Письма не попадали в интерфейс именно поэтому.

**Решение:** `monitoring/scheduler.py` — асинхронный планировщик внутри web-процесса
(стартует в `startup_event`). Переиспользует существующие Celery-функции, выполняя их
в thread-executor (без вложенных event loop). Без отдельных дайно и доп. затрат.
- health-проверки: `HEALTH_CHECK_INTERVAL_SECONDS` (по умолч. 300с)
- Redis + авто-очистка: `REDIS_CHECK_INTERVAL_SECONDS` (120с)
- IMAP-почта: `IMAP_POLL_INTERVAL_SECONDS` (60с)
- очистка старых данных: `CLEANUP_INTERVAL_SECONDS` (раз в сутки)
- выключатель: `ENABLE_INPROCESS_SCHEDULER=false` (если поднимете реальные worker/beat).

**Примечания:** забираются только UNSEEN-письма (уже прочитанные ранее не подтянутся);
вложения пишутся в `monitoring_uploads/` (эфемерно на Heroku — тело письма в БД, файлы
вложений теряются при рестарте, durable-хранилище — отдельная задача).

### Текущее состояние health-проверок (что настроено в .env)
- ✅ PostgreSQL, ✅ Redis (market-research).
- ⚠️ НЕ настроены (ключи отсутствуют в .env, проверки не идут): `HEROKU_API_KEY`+`HEROKU_APP_NAMES`,
  `VERCEL_TOKEN`+`VERCEL_PROJECT_ID`, `OPENAI_API_KEY`, `OTHER_API_KEYS`. Заполнить для проверок Heroku/Vercel/OpenAI.

### Обновление 2026-06-19 — расширенные health-проверки
- **HTTP /health бэкенд-сервисов** (конфиг-driven): env `MONITORED_SERVICES` (JSON-список
  `{name,url,health_path}`). Пингует каждый сервис, точнее чем Heroku-dyno API. Новые сервисы
  появляются в сетке дашборда автоматически. `check_http_service` в health_checkers.py.
- **API-проверки:**
  - OpenAI — валидность (`/v1/models`, бесплатно).
  - **Apify** — валидность токена + **месячный расход $/лимит** (`/v2/users/me/limits`, бесплатно).
    Сумма выводится на карточке сервиса (прогресс-бар расхода). env `APIFY_API_TOKEN`.
  - Serper / Google CSE — только индикатор «настроен» (env `SERPER_API_KEY`, `GOOGLE_CSE_API_KEY`),
    БЕЗ активных вызовов, т.к. активная проверка тратит платную квоту (288 запросов/день).
    Реальный расход этих API — собирать через собственные счётчики `api_usage_metrics`.
- **Загрузка UI**: убран блокирующий пульсирующий спиннер — страница рендерится сразу,
  данные подгружаются в фоне с ненавязчивым индикатором (см. upgrowplan_new MonitoringDashboard).

## 📝 Лицензия

Proprietary - Upgrowplan

## 👥 Контакты

Denis Naletov - Business Consultant & Developer
Email: contact@upgrowplan.com

---

**Made with ❤️ for Upgrowplan**
