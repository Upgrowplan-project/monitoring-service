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
    async def check_database_connection(database_url: str) -> Dict[str, Any]:
        """
        Проверка подключения к базе данных
        
        Args:
            database_url: URL подключения к БД
            
        Returns:
            Dict с информацией о статусе
        """
        try:
            from sqlalchemy import create_engine, text
            start_time = datetime.now()
            
            # Создаем временный engine
            engine = create_engine(database_url, pool_pre_ping=True)
            
            # Пробуем выполнить простой запрос
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            response_time = (datetime.now() - start_time).total_seconds()
            
            return {
                "status": "healthy",
                "response_time": response_time,
                "metadata": {
                    "database_type": "postgresql"
                }
            }
        except Exception as e:
            logger.error(f"Error checking database: {e}")
            return {
                "status": "down",
                "error_message": str(e)
            }


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
    
    # Vercel
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
    
    # OpenAI
    tasks.append({
        "coro": checker.check_openai_api(config.OPENAI_API_KEY),
        "service_name": "OpenAI API",
        "service_type": "api_key"
    })
    
    # Другие API
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
