import smtplib
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import logging
from .config import get_config
from .models import SystemAlert

logger = logging.getLogger(__name__)


class AlertManager:
    """Менеджер для отправки алертов по различным каналам"""
    
    def __init__(self):
        self.config = get_config()
    
    async def send_alert(self, alert: SystemAlert):
        """
        Отправка алерта по всем доступным каналам
        
        Args:
            alert: SystemAlert объект
        """
        try:
            # Email - всегда отправляем
            await self._send_email(alert)
            
            # Telegram - только для critical алертов
            if alert.severity == "critical" and self.config.TELEGRAM_BOT_TOKEN:
                await self._send_telegram(alert)
                
            logger.info(f"Alert sent successfully: {alert.service_name} - {alert.message}")
        except Exception as e:
            logger.error(f"Error sending alert: {e}")
    
    async def _send_email(self, alert: SystemAlert):
        """
        Отправка email уведомления
        
        Args:
            alert: SystemAlert объект
        """
        if not all([self.config.SMTP_HOST, self.config.SMTP_USER, self.config.SMTP_PASSWORD]):
            logger.warning("SMTP not configured, skipping email")
            return
        
        try:
            # Создаем сообщение
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[{alert.severity.upper()}] Upgrowplan Monitor Alert: {alert.service_name}"
            msg['From'] = self.config.SMTP_USER
            msg['To'] = self.config.ADMIN_EMAIL
            
            # HTML версия письма
            html = f"""
            <html>
                <body style="font-family: Arial, sans-serif;">
                    <div style="background-color: {'#dc3545' if alert.severity == 'critical' else '#ffc107' if alert.severity == 'warning' else '#17a2b8'}; 
                                color: white; 
                                padding: 20px; 
                                border-radius: 5px;">
                        <h2>⚠️ System Alert</h2>
                    </div>
                    
                    <div style="padding: 20px; background-color: #f8f9fa; margin-top: 10px; border-radius: 5px;">
                        <h3>Service: {alert.service_name}</h3>
                        <p><strong>Severity:</strong> <span style="color: {'#dc3545' if alert.severity == 'critical' else '#ffc107' if alert.severity == 'warning' else '#17a2b8'};">
                            {alert.severity.upper()}
                        </span></p>
                        <p><strong>Message:</strong> {alert.message}</p>
                        <p><strong>Time:</strong> {alert.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                    </div>
                    
                    <div style="margin-top: 20px; padding: 15px; background-color: #e9ecef; border-radius: 5px;">
                        <p style="margin: 0; color: #6c757d; font-size: 12px;">
                            This is an automated alert from Upgrowplan Monitoring System.
                            Please check the admin dashboard for more details.
                        </p>
                    </div>
                </body>
            </html>
            """
            
            # Текстовая версия
            text = f"""
            SYSTEM ALERT
            
            Service: {alert.service_name}
            Severity: {alert.severity.upper()}
            Message: {alert.message}
            Time: {alert.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
            
            This is an automated alert from Upgrowplan Monitoring System.
            """
            
            part1 = MIMEText(text, 'plain')
            part2 = MIMEText(html, 'html')
            
            msg.attach(part1)
            msg.attach(part2)
            
            # Отправляем
            with smtplib.SMTP(self.config.SMTP_HOST, self.config.SMTP_PORT) as server:
                server.starttls()
                server.login(self.config.SMTP_USER, self.config.SMTP_PASSWORD)
                server.send_message(msg)
            
            logger.info(f"Email alert sent to {self.config.ADMIN_EMAIL}")
        except Exception as e:
            logger.error(f"Error sending email: {e}")
    
    async def _send_telegram(self, alert: SystemAlert):
        """
        Отправка Telegram уведомления
        
        Args:
            alert: SystemAlert объект
        """
        if not self.config.TELEGRAM_BOT_TOKEN or not self.config.TELEGRAM_CHAT_ID:
            logger.warning("Telegram not configured, skipping")
            return
        
        try:
            # Выбираем эмодзи в зависимости от severity
            emoji = "🔴" if alert.severity == "critical" else "⚠️" if alert.severity == "warning" else "ℹ️"
            
            message = (
                f"{emoji} <b>{alert.severity.upper()}</b>\n\n"
                f"<b>Service:</b> {alert.service_name}\n"
                f"<b>Message:</b> {alert.message}\n"
                f"<b>Time:</b> {alert.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                f"🔗 Check dashboard: https://upgrowplan.com/account/monitor"
            )
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{self.config.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": self.config.TELEGRAM_CHAT_ID,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True
                    }
                )
                
                if response.status_code == 200:
                    logger.info(f"Telegram alert sent successfully")
                else:
                    logger.error(f"Telegram API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
    
    def should_send_alert(self, service_name: str, status: str, previous_status: Optional[str]) -> bool:
        """
        Определяет, нужно ли отправлять алерт
        
        Args:
            service_name: Название сервиса
            status: Текущий статус
            previous_status: Предыдущий статус
            
        Returns:
            True если нужно отправить алерт
        """
        # Отправляем алерт если:
        # 1. Статус изменился с healthy на degraded или down
        # 2. Статус изменился с degraded на down
        # 3. Статус стал healthy после проблем (recovery alert)
        
        if previous_status is None:
            # Первая проверка - алерт только если не healthy
            return status != "healthy"
        
        if previous_status == "healthy" and status in ["degraded", "down"]:
            return True
        
        if previous_status == "degraded" and status == "down":
            return True
        
        if previous_status in ["degraded", "down"] and status == "healthy":
            return True  # Recovery alert
        
        return False
    
    def get_alert_severity(self, status: str) -> str:
        """
        Определяет severity алерта по статусу
        
        Args:
            status: Статус сервиса
            
        Returns:
            Severity level
        """
        if status == "down":
            return "critical"
        elif status == "degraded":
            return "warning"
        else:
            return "info"
