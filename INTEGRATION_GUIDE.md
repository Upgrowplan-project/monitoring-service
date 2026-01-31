# 🔗 Интеграция с существующим Upgrowplan проектом

## Шаг 1: Backend интеграция

### Вариант A: Отдельный микросервис (рекомендуется)

Деплоим monitoring backend как отдельный Heroku app:

```bash
cd backend

# Создать новый Heroku app
heroku create upgrowplan-monitoring

# Добавить PostgreSQL
heroku addons:create heroku-postgresql:mini

# Добавить Redis
heroku addons:create heroku-redis:mini

# Установить env переменные
heroku config:set VERCEL_TOKEN=your_token
heroku config:set HEROKU_API_KEY=your_key
heroku config:set OPENAI_API_KEY=your_key
# ... и остальные

# Деплой
git init
git add .
git commit -m "Initial monitoring system"
git push heroku main

# Инициализировать БД
heroku run python -c "from monitoring.database import init_db; init_db()"
```

### Вариант B: Интеграция в существующий backend

Скопируйте папку `backend/monitoring/` в ваш существующий backend проект:

```bash
# Скопировать модуль
cp -r backend/monitoring /path/to/your/backend/

# Добавить зависимости в ваш requirements.txt
cat backend/requirements.txt >> /path/to/your/backend/requirements.txt

# Установить
pip install -r requirements.txt
```

В вашем main FastAPI файле:

```python
from monitoring import get_db, init_db
from monitoring.models import ServiceHealth, SystemAlert
from fastapi import Depends

# При старте
@app.on_event("startup")
async def startup():
    init_db()

# Добавить endpoints
@app.get("/api/monitoring/overview")
async def monitoring_overview(db: Session = Depends(get_db)):
    # ... ваш код из main.py
```

## Шаг 2: Frontend интеграция

### В вашем React проекте:

```bash
cd /path/to/your/frontend

# Установить зависимости
npm install react-use-websocket chart.js react-chartjs-2 react-bootstrap bootstrap
```

### Скопировать компоненты:

```bash
# Создать структуру
mkdir -p src/pages/monitoring
mkdir -p src/components/monitoring
mkdir -p src/hooks/monitoring
mkdir -p src/types

# Скопировать файлы
cp frontend/src/pages/MonitoringDashboard.tsx src/pages/monitoring/
cp frontend/src/components/* src/components/monitoring/
cp frontend/src/hooks/useMonitoring.ts src/hooks/monitoring/
cp frontend/src/types/monitoring.ts src/types/
```

### Добавить маршрут:

В вашем `App.tsx` или основном файле с роутами:

```tsx
import { MonitoringDashboard } from './pages/monitoring/MonitoringDashboard';

function App() {
  return (
    <Routes>
      {/* Ваши существующие маршруты */}
      
      {/* Добавить маршрут мониторинга */}
      <Route 
        path="/account/monitor" 
        element={
          <ProtectedRoute requireAdmin>
            <MonitoringDashboard />
          </ProtectedRoute>
        } 
      />
    </Routes>
  );
}
```

### Настроить env переменные:

В `.env.local`:

```env
REACT_APP_API_URL=https://upgrowplan-monitoring.herokuapp.com
REACT_APP_WS_URL=wss://upgrowplan-monitoring.herokuapp.com
```

Или если встроили в существующий backend:

```env
REACT_APP_API_URL=https://api.upgrowplan.com
REACT_APP_WS_URL=wss://api.upgrowplan.com
```

## Шаг 3: Защита маршрута (только для админов)

### Создать ProtectedRoute компонент:

```tsx
// src/components/ProtectedRoute.tsx
import { Navigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth'; // ваш auth hook

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ 
  children, 
  requireAdmin = false 
}) => {
  const { user, isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return <Navigate to="/login" />;
  }

  if (requireAdmin && !user?.isAdmin) {
    return <Navigate to="/account" />;
  }

  return <>{children}</>;
};
```

## Шаг 4: Добавить ссылку в навигацию

В вашем Dashboard или Admin Panel:

```tsx
// Где-то в вашей навигации
{user?.isAdmin && (
  <Nav.Link href="/account/monitor">
    <i className="bi bi-activity"></i> System Monitor
  </Nav.Link>
)}
```

## Шаг 5: Настройка Celery для периодических задач

### Если у вас уже есть Celery:

Добавьте tasks из `backend/monitoring/tasks.py` в ваш существующий Celery app.

### Если Celery нет:

Нужен отдельный worker процесс на Heroku:

```bash
# В Procfile добавить:
web: uvicorn main:app --host 0.0.0.0 --port $PORT
worker: celery -A monitoring.tasks worker --loglevel=info
beat: celery -A monitoring.tasks beat --loglevel=info

# Запустить worker dyno
heroku ps:scale worker=1 beat=1
```

## Шаг 6: Проверка работы

1. Откройте https://upgrowplan.com/account/monitor
2. Вы должны увидеть:
   - ✅ Overall System Status
   - 📊 Список всех сервисов
   - 🚨 Активные алерты (если есть)
   - 📈 Статистику

3. Проверьте WebSocket подключение - должен быть зеленый badge "● Live"

## Шаг 7: Настройка уведомлений

### Email алерты:

В Heroku config vars:

```bash
heroku config:set ADMIN_EMAIL=your@email.com
heroku config:set SMTP_HOST=smtp.gmail.com
heroku config:set SMTP_USER=your@gmail.com
heroku config:set SMTP_PASSWORD=your_app_password
```

### Telegram алерты (опционально):

```bash
heroku config:set TELEGRAM_BOT_TOKEN=your_bot_token
heroku config:set TELEGRAM_CHAT_ID=your_chat_id
```

## 🎨 Кастомизация под ваш стиль

### Изменить цвета Bootstrap:

В вашем `index.css`:

```css
/* Переопределить цвета для мониторинга */
.service-card {
  transition: transform 0.2s;
}

.service-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.alert-item {
  animation: slideIn 0.3s ease-in;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(-20px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}
```

## 🔥 Важные замечания

1. **Безопасность**: Убедитесь что `/account/monitor` доступен только админам
2. **API Keys**: Никогда не коммитьте .env файл в git
3. **Rate Limits**: API проверки идут каждые 5 минут - это безопасно для большинства API
4. **Database**: Старые данные автоматически удаляются через 30 дней

## 🐛 Troubleshooting

### Frontend не может подключиться к API:

Проверьте CORS настройки в `backend/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://upgrowplan.com", "https://www.upgrowplan.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### WebSocket не работает:

1. Убедитесь что используете `wss://` для HTTPS
2. Проверьте что WebSocket не блокируется прокси/firewall

### Celery задачи не выполняются:

```bash
# Проверить логи worker
heroku logs --tail --dyno worker

# Рестарт worker
heroku ps:restart worker
```

---

**Готово!** Теперь у вас есть полноценная система мониторинга, интегрированная с Upgrowplan! 🎉
