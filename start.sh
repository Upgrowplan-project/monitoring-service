#!/bin/bash

# Upgrowplan Monitoring System - Quick Start Script

set -e

echo "🚀 Upgrowplan Monitoring System - Quick Start"
echo "=============================================="
echo ""

# Проверка Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker не установлен. Установите Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose не установлен. Установите Docker Compose"
    exit 1
fi

echo "✅ Docker и Docker Compose установлены"
echo ""

# Проверка .env файла
if [ ! -f .env ]; then
    echo "📝 Создаю .env файл из примера..."
    cp .env.example .env
    echo "⚠️  ВАЖНО: Отредактируйте .env файл и укажите ваши API ключи!"
    echo ""
    read -p "Нажмите Enter когда отредактируете .env файл..."
fi

echo "✅ .env файл найден"
echo ""

# Остановка существующих контейнеров
echo "🛑 Останавливаю существующие контейнеры..."
docker-compose down 2>/dev/null || true
echo ""

# Запуск сервисов
echo "🐳 Запускаю сервисы..."
docker-compose up -d

echo ""
echo "⏳ Ожидание запуска сервисов (30 секунд)..."
sleep 30

# Инициализация БД
echo ""
echo "💾 Инициализация базы данных..."
docker exec upgrowplan_monitoring_backend python -c "from monitoring.database import init_db; init_db()" 2>/dev/null || true

echo ""
echo "✅ Система успешно запущена!"
echo ""
echo "📊 Доступ к сервисам:"
echo "  - Backend API: http://localhost:8000"
echo "  - API Docs: http://localhost:8000/docs"
echo "  - PostgreSQL: localhost:5432"
echo "  - Redis: localhost:6379"
echo ""
echo "📋 Полезные команды:"
echo "  - Просмотр логов: docker-compose logs -f"
echo "  - Остановка: docker-compose down"
echo "  - Перезапуск: docker-compose restart"
echo "  - Статус: docker-compose ps"
echo ""
echo "🎉 Готово! Интегрируйте компонент MonitoringDashboard в ваш фронтенд."
echo ""
