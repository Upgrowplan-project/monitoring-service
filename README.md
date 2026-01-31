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

## 📝 Лицензия

Proprietary - Upgrowplan

## 👥 Контакты

Denis Naletov - Business Consultant & Developer
Email: contact@upgrowplan.com

---

**Made with ❤️ for Upgrowplan**
