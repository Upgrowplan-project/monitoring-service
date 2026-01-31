from celery.schedules import crontab

# Broker и backend
broker_url = 'redis://localhost:6379/0'
result_backend = 'redis://localhost:6379/0'

# Сериализация
task_serializer = 'json'
accept_content = ['json']
result_serializer = 'json'
timezone = 'UTC'
enable_utc = True

# Расписание periodic tasks
beat_schedule = {
    # Проверка всех сервисов каждые 5 минут
    'check-all-services-every-5-minutes': {
        'task': 'monitoring.check_all_services',
        'schedule': 300.0,  # 5 минут в секундах
    },
    
    # Сбор активности пользователей каждую минуту
    'collect-user-activity-every-minute': {
        'task': 'monitoring.collect_user_activity',
        'schedule': 60.0,  # 1 минута в секундах
    },
    
    # Очистка старых данных каждый день в 3:00 AM
    'cleanup-old-data-daily': {
        'task': 'monitoring.cleanup_old_data',
        'schedule': crontab(hour=3, minute=0),
    },
}

# Worker настройки
worker_prefetch_multiplier = 1
worker_max_tasks_per_child = 1000

# Логирование
worker_log_format = '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s'
worker_task_log_format = '[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s'
