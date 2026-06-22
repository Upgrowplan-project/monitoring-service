import httpx
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class HealthChecker:
    """Базовый класс для проверки здоровья сервисов"""
    
    @staticmethod
    async def check_vercel_deployment(token: str, project_id: str) -> Dict[str, Any]:
        """
        Проверка статуса Vercel deployment
        
        Args:
            token: Vercel API token
            project_id: ID проекта на Vercel
            
        Returns:
            Dict с информацией о статусе
        """
        try:
            start_time = datetime.now()
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Authorization": f"Bearer {token}"}
                response = await client.get(
                    "https://api.vercel.com/v6/deployments",
                    headers=headers,
                    params={"projectId": project_id, "limit": 1}
                )
                response_time = (datetime.now() - start_time).total_seconds()
                
                if response.status_code == 200:
                    data = response.json()
                    deployments = data.get("deployments", [])
                    
                    if deployments:
                        latest = deployments[0]
                        state = latest.get("state")
                        
                        return {
                            "status": "healthy" if state == "READY" else "degraded",
                            "response_time": response_time,
                            "metadata": {
                                "deployment_url": latest.get("url"),
                                "state": state,
                                "created_at": latest.get("createdAt"),
                                "ready_at": latest.get("ready"),
                            }
                        }
                    else:
                        return {
                            "status": "down",
                            "error_message": "No deployments found",
                            "response_time": response_time
                        }
                elif response.status_code == 401:
                    return {
                        "status": "down",
                        "error_message": "Invalid Vercel token"
                    }
                else:
                    return {
                        "status": "down",
                        "error_message": f"Status code: {response.status_code}"
                    }
        except Exception as e:
            logger.error(f"Error checking Vercel: {e}")
            return {
                "status": "down",
                "error_message": str(e)
            }
    
    @staticmethod
    async def check_heroku_app(api_key: str, app_name: str) -> Dict[str, Any]:
        """
        Проверка статуса Heroku app
        
        Args:
            api_key: Heroku API key
            app_name: Название приложения
            
        Returns:
            Dict с информацией о статусе
        """
        try:
            start_time = datetime.now()
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/vnd.heroku+json; version=3"
                }
                
                # Проверяем статус приложения
                app_response = await client.get(
                    f"https://api.heroku.com/apps/{app_name}",
                    headers=headers
                )
                
                # Проверяем статус dynos
                dyno_response = await client.get(
                    f"https://api.heroku.com/apps/{app_name}/dynos",
                    headers=headers
                )
                
                response_time = (datetime.now() - start_time).total_seconds()
                
                if app_response.status_code == 200:
                    app_data = app_response.json()
                    dynos = dyno_response.json() if dyno_response.status_code == 200 else []
                    
                    # Считаем запущенные dynos
                    running_dynos = [d for d in dynos if d.get("state") == "up"]
                    total_dynos = len(dynos)
                    
                    # Определяем статус
                    if total_dynos == 0:
                        status = "degraded"  # нет dynos вообще
                    elif len(running_dynos) == total_dynos:
                        status = "healthy"
                    elif len(running_dynos) > 0:
                        status = "degraded"  # не все dynos работают
                    else:
                        status = "down"  # ни один dyno не работает
                    
                    return {
                        "status": status,
                        "response_time": response_time,
                        "metadata": {
                            "app_name": app_name,
                            "region": app_data.get("region", {}).get("name"),
                            "stack": app_data.get("stack", {}).get("name"),
                            "dynos_running": len(running_dynos),
                            "dynos_total": total_dynos,
                            "web_url": app_data.get("web_url")
                        }
                    }
                elif app_response.status_code == 401:
                    return {
                        "status": "down",
                        "error_message": "Invalid Heroku API key"
                    }
                elif app_response.status_code == 404:
                    return {
                        "status": "down",
                        "error_message": f"App '{app_name}' not found"
                    }
                else:
                    return {
                        "status": "down",
                        "error_message": f"Status code: {app_response.status_code}"
                    }
        except Exception as e:
            logger.error(f"Error checking Heroku app {app_name}: {e}")
            return {
                "status": "down",
                "error_message": str(e)
            }
    
    @staticmethod
    async def check_openai_api(api_key: str) -> Dict[str, Any]:
        """
        Проверка OpenAI API и доступности
        
        Args:
            api_key: OpenAI API key
            
        Returns:
            Dict с информацией о статусе
        """
        try:
            start_time = datetime.now()
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Authorization": f"Bearer {api_key}"}
                
                # Проверяем доступность API
                models_response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers=headers
                )
                response_time = (datetime.now() - start_time).total_seconds()
                
                if models_response.status_code == 200:
                    models_data = models_response.json()
                    models_count = len(models_data.get("data", []))
                    
                    return {
                        "status": "healthy",
                        "response_time": response_time,
                        "metadata": {
                            "models_available": models_count,
                            "api_version": "v1"
                        }
                    }
                elif models_response.status_code == 401:
                    return {
                        "status": "down",
                        "error_message": "Invalid OpenAI API key"
                    }
                elif models_response.status_code == 429:
                    return {
                        "status": "degraded",
                        "error_message": "Rate limit exceeded",
                        "response_time": response_time
                    }
                else:
                    return {
                        "status": "down",
                        "error_message": f"Status code: {models_response.status_code}"
                    }
        except Exception as e:
            logger.error(f"Error checking OpenAI API: {e}")
            return {
                "status": "down",
                "error_message": str(e)
            }
    
    @staticmethod
    async def check_generic_api(
        name: str, 
        url: str, 
        headers: Optional[Dict] = None,
        method: str = "GET",
        expected_status: int = 200
    ) -> Dict[str, Any]:
        """
        Универсальная проверка любого API endpoint
        
        Args:
            name: Название сервиса
            url: URL для проверки
            headers: Заголовки запроса
            method: HTTP метод
            expected_status: Ожидаемый статус код
            
        Returns:
            Dict с информацией о статусе
        """
        try:
            start_time = datetime.now()
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method.upper() == "GET":
                    response = await client.get(url, headers=headers or {})
                elif method.upper() == "POST":
                    response = await client.post(url, headers=headers or {})
                else:
                    return {
                        "status": "down",
                        "error_message": f"Unsupported method: {method}"
                    }
                
                response_time = (datetime.now() - start_time).total_seconds()
                
                if response.status_code == expected_status:
                    status = "healthy"
                elif 200 <= response.status_code < 300:
                    status = "healthy"
                elif 400 <= response.status_code < 500:
                    status = "degraded"
                else:
                    status = "down"
                
                return {
                    "status": status,
                    "response_time": response_time,
                    "metadata": {
                        "status_code": response.status_code,
                        "url": url
                    }
                }
        except Exception as e:
            logger.error(f"Error checking {name}: {e}")
            return {
                "status": "down",
                "error_message": str(e)
            }
    
    @staticmethod
    async def check_http_service(
        name: str,
        url: str,
        health_path: str = "/health",
        up_on_any_response: bool = False,
    ) -> Dict[str, Any]:
        """
        Проверка готовности бэкенд-сервиса через его HTTP /health эндпоинт.

        Точнее, чем Heroku-dyno API: подтверждает, что приложение реально отвечает.
        2xx → healthy, 4xx → degraded, 5xx/timeout/conn error → down.

        up_on_any_response=True — liveness-режим для сервисов БЕЗ /health (например
        Spring Boot user-service): любой ответ, кроме 5xx, считается healthy
        (приложение поднято и отвечает), только 5xx/таймаут/conn-error → down.
        """
        base = (url or "").rstrip("/")
        path = health_path or "/health"
        if not path.startswith("/"):
            path = "/" + path
        full_url = f"{base}{path}"
        try:
            start_time = datetime.now()
            # 30s tolerates Heroku eco-dyno cold starts (asleep dynos wake slowly).
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(full_url)
                response_time = (datetime.now() - start_time).total_seconds()

                code = response.status_code
                if up_on_any_response:
                    status = "healthy" if code < 500 else "down"
                elif 200 <= code < 300:
                    status = "healthy"
                elif 400 <= code < 500:
                    status = "degraded"
                else:
                    status = "down"

                # Пытаемся вытащить полезную информацию из тела /health, если JSON.
                info: Dict[str, Any] = {"status_code": code, "url": full_url}
                try:
                    body = response.json()
                    if isinstance(body, dict):
                        for k in ("status", "version", "all_ready", "uptime"):
                            if k in body:
                                info[k] = body[k]
                except Exception:
                    pass

                return {
                    "status": status,
                    "response_time": response_time,
                    "error_message": None if status == "healthy" else f"HTTP {code}",
                    "metadata": info,
                }
        except Exception as e:
            # Connection/timeout errors often stringify to "" — include the type.
            msg = str(e) or type(e).__name__
            logger.error(f"Error checking service {name} ({full_url}): {msg}")
            return {"status": "down", "error_message": msg, "metadata": {"url": full_url}}

    @staticmethod
    async def check_apify_balance(token: str) -> Dict[str, Any]:
        """
        Проверка Apify: валидность токена + месячный расход/лимит (бесплатный эндпоинт).

        GET /v2/users/me/limits → current.monthlyUsageUsd, limits.maxMonthlyUsageUsd.
        """
        try:
            start_time = datetime.now()
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    "https://api.apify.com/v2/users/me/limits",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response_time = (datetime.now() - start_time).total_seconds()

                if resp.status_code == 401:
                    return {"status": "down", "error_message": "Invalid Apify token"}
                if resp.status_code != 200:
                    return {
                        "status": "down",
                        "error_message": f"Status code: {resp.status_code}",
                        "response_time": response_time,
                    }

                data = (resp.json() or {}).get("data", {})
                current = data.get("current", {}) or {}
                limits = data.get("limits", {}) or {}
                used = current.get("monthlyUsageUsd")
                limit = limits.get("maxMonthlyUsageUsd")
                percent = None
                status = "healthy"
                if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
                    percent = round((used / limit) * 100, 1)
                    if percent >= 95:
                        status = "down"
                    elif percent >= 80:
                        status = "degraded"

                return {
                    "status": status,
                    "response_time": response_time,
                    "metadata": {
                        "monthly_usage_usd": used,
                        "monthly_limit_usd": limit,
                        "usage_percent": percent,
                    },
                }
        except Exception as e:
            logger.error(f"Error checking Apify balance: {e}")
            return {"status": "down", "error_message": str(e)}

    @staticmethod
    async def check_api_key_present(name: str, api_key: Optional[str]) -> Dict[str, Any]:
        """
        Лёгкий индикатор «ключ настроен» БЕЗ активного вызова.

        Для платных по запросу API (Serper, Google CSE) активная проверка сожгла бы
        квоту, поэтому показываем только наличие ключа. Реальный расход — через
        собственные счётчики api_usage_metrics.
        """
        if api_key and str(api_key).strip():
            return {
                "status": "healthy",
                "metadata": {"configured": True, "note": "presence-only (no active call)"},
            }
        return {
            "status": "down",
            "error_message": "API key not configured",
            "metadata": {"configured": False},
        }

    @staticmethod
    async def check_database_connection(database_url: str) -> Dict[str, Any]:
        """
        Проверка подключения к базе данных
        
        Args:
            database_url: URL подключения к БД
            
        Returns:
            Dict с информацией о статусе
        """
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool
        start_time = datetime.now()

        # NullPool + dispose() в finally: НЕ держим открытых коннектов между
        # проверками (иначе при периодическом запуске роль БД упирается в лимит
        # "too many connections" и приложение крашится при рестарте).
        engine = create_engine(database_url, poolclass=NullPool, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            response_time = (datetime.now() - start_time).total_seconds()
            return {
                "status": "healthy",
                "response_time": response_time,
                "metadata": {"database_type": "postgresql"},
            }
        except Exception as e:
            logger.error(f"Error checking database: {e}")
            return {"status": "down", "error_message": str(e)}
        finally:
            engine.dispose()


    @staticmethod
    async def check_redis_memory(
        redis_url: str,
        plan_limit_mb: float = 27.0,
        warning_threshold: float = 70.0,
        cleanup_threshold: float = 80.0,
    ) -> Dict[str, Any]:
        """
        Проверяет использование памяти Redis и автоматически очищает research:* ключи
        если использование превышает cleanup_threshold.
        """
        try:
            import redis.asyncio as aioredis
            start_time = datetime.now()

            r = aioredis.from_url(redis_url, decode_responses=True, socket_timeout=10)

            mem_info = await r.info("memory")
            used_mb = mem_info["used_memory"] / 1024 / 1024
            used_percent = (used_mb / plan_limit_mb) * 100

            keys_deleted = 0
            cleanup_triggered = False
            used_mb_after = used_mb

            if used_percent >= cleanup_threshold:
                cleanup_triggered = True
                research_keys = await r.keys("research:*")
                cache_keys = await r.keys("research_cache:*")
                all_keys = research_keys + cache_keys
                if all_keys:
                    keys_deleted = await r.delete(*all_keys)
                logger.warning(
                    f"[Redis Cleanup] Auto-cleanup at {used_percent:.1f}% "
                    f"({used_mb:.1f}MB/{plan_limit_mb}MB) — deleted {keys_deleted} keys"
                )
                mem_after = await r.info("memory")
                used_mb_after = mem_after["used_memory"] / 1024 / 1024

            response_time = (datetime.now() - start_time).total_seconds()
            await r.aclose()

            if used_percent >= 90:
                status = "down"
            elif used_percent >= warning_threshold:
                status = "degraded"
            else:
                status = "healthy"

            return {
                "status": status,
                "response_time": response_time,
                "metadata": {
                    "used_mb": round(used_mb, 2),
                    "plan_limit_mb": plan_limit_mb,
                    "used_percent": round(used_percent, 1),
                    "used_mb_after_cleanup": round(used_mb_after, 2) if cleanup_triggered else None,
                    "keys_deleted": keys_deleted,
                    "cleanup_triggered": cleanup_triggered,
                    "evicted_keys": mem_info.get("evicted_keys", 0),
                }
            }
        except Exception as e:
            logger.error(f"Error checking Redis memory: {e}")
            return {"status": "down", "error_message": str(e)}


async def check_all_services(config) -> list:
    """
    Проверяет все сервисы параллельно
    
    Args:
        config: MonitoringConfig instance
        
    Returns:
        Список результатов проверки всех сервисов
    """
    checker = HealthChecker()
    tasks = []
    
    # Vercel — только если токен задан
    if config.VERCEL_TOKEN and config.VERCEL_PROJECT_ID:
        tasks.append({
            "coro": checker.check_vercel_deployment(
                config.VERCEL_TOKEN,
                config.VERCEL_PROJECT_ID
            ),
            "service_name": "Vercel Frontend",
            "service_type": "vercel"
        })

    # Heroku apps
    for app_name in config.HEROKU_APP_NAMES:
        tasks.append({
            "coro": checker.check_heroku_app(
                config.HEROKU_API_KEY,
                app_name
            ),
            "service_name": f"Heroku: {app_name}",
            "service_type": "heroku"
        })

    # Бэкенд-сервисы (HTTP /health) — конфиг-driven список
    for svc in getattr(config, "MONITORED_SERVICES", []) or []:
        if not isinstance(svc, dict) or not svc.get("url"):
            continue
        svc_name = svc.get("name") or svc.get("url")
        _liveness = str(svc.get("liveness", "")).lower() == "any" or bool(svc.get("up_on_any_response"))
        tasks.append({
            "coro": checker.check_http_service(
                svc_name,
                svc["url"],
                svc.get("health_path", "/health"),
                up_on_any_response=_liveness,
            ),
            "service_name": svc_name,
            "service_type": "service",
        })

    # OpenAI — только если ключ задан (бесплатный /v1/models)
    if config.OPENAI_API_KEY:
        tasks.append({
            "coro": checker.check_openai_api(config.OPENAI_API_KEY),
            "service_name": "OpenAI API",
            "service_type": "api_key"
        })

    # Apify — валидность токена + баланс (бесплатный эндпоинт лимитов)
    if getattr(config, "APIFY_API_TOKEN", None):
        tasks.append({
            "coro": checker.check_apify_balance(config.APIFY_API_TOKEN),
            "service_name": "Apify API",
            "service_type": "api_key",
        })

    # Serper / Google CSE — только индикатор "настроен" (без активных вызовов,
    # чтобы не тратить платную квоту на health-проверки).
    if getattr(config, "SERPER_API_KEY", None) is not None:
        tasks.append({
            "coro": checker.check_api_key_present("Serper API", config.SERPER_API_KEY),
            "service_name": "Serper API",
            "service_type": "api_key",
        })
    if getattr(config, "GOOGLE_CSE_API_KEY", None) is not None:
        tasks.append({
            "coro": checker.check_api_key_present("Google Custom Search", config.GOOGLE_CSE_API_KEY),
            "service_name": "Google Custom Search",
            "service_type": "api_key",
        })

    # Другие API (legacy generic)
    for service_name, api_key in config.OTHER_API_KEYS.items():
        tasks.append({
            "coro": checker.check_generic_api(
                service_name,
                f"https://api.{service_name.lower()}.com/health",
                headers={"Authorization": f"Bearer {api_key}"}
            ),
            "service_name": service_name,
            "service_type": "api_key"
        })
    
    # Database
    tasks.append({
        "coro": checker.check_database_connection(config.DATABASE_URL),
        "service_name": "PostgreSQL Database",
        "service_type": "database"
    })

    # Redis Memory (market-research-service)
    if getattr(config, "MARKET_RESEARCH_REDIS_URL", None):
        tasks.append({
            "coro": checker.check_redis_memory(
                config.MARKET_RESEARCH_REDIS_URL,
                plan_limit_mb=getattr(config, "REDIS_PLAN_LIMIT_MB", 27.0),
                warning_threshold=getattr(config, "REDIS_MEMORY_WARNING_THRESHOLD", 70.0),
                cleanup_threshold=getattr(config, "REDIS_MEMORY_CLEANUP_THRESHOLD", 80.0),
            ),
            "service_name": "Redis: Market Research",
            "service_type": "redis"
        })
    
    # Выполняем все проверки параллельно
    results = []
    for task in tasks:
        try:
            result = await task["coro"]
            results.append({
                "service_name": task["service_name"],
                "service_type": task["service_type"],
                **result
            })
        except Exception as e:
            logger.error(f"Error checking {task['service_name']}: {e}")
            results.append({
                "service_name": task["service_name"],
                "service_type": task["service_type"],
                "status": "down",
                "error_message": str(e)
            })
    
    return results
