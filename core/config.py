"""Configuration module using Pydantic Settings."""
import os
from typing import List, Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Telegram Bot
    BOT_TOKEN: str
    ADMIN_TG_ID: int
    
    # 3x-ui API
    XUI_BASE_URL: str  # Example: https://your-server.com
    XUI_USERNAME: str
    XUI_PASSWORD: str
    XUI_VERIFY_SSL: bool = False  # Проверка SSL сертификатов (False для самоподписанных)
    XUI_EXTERNAL_ADDRESS: str = ""  # Внешний адрес сервера для клиентских подключений (например: example.com)
    XUI_EXTERNAL_PORT: int = 443  # Внешний порт для клиентских подключений (по умолчанию 443)
    
    # VLESS Connection (fallback settings, optional)
    # Эти настройки используются только если не удается получить ссылку из API
    VLESS_SERVER: str = ""  # Server IP or domain
    VLESS_PORT: int = 443  # Server port
    VLESS_SNI: str = ""  # Server Name Indication (domain)
    VLESS_SECURITY: str = "tls"  # Security type
    VLESS_TYPE: str = "tcp"  # Connection type
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/vpn_bot.db"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/bot.log"
    LOG_ROTATION: str = "00:00"  # Rotate at midnight
    LOG_RETENTION: str = "30 days"

    # Список ID каналов (напр. -100123456789)
    REQUIRED_CHANNELS: List[int] = []
    # Список ссылок на эти каналы для кнопок
    CHANNEL_URLS: List[str] = []
    # Список ID администраторов (для доступа в админ-панель и обхода проверок)
    ADMIN_IDS: List[int] = []

    # Валидатор для превращения строки из .env в список чисел
    @field_validator("REQUIRED_CHANNELS", "ADMIN_IDS", mode="before")
    @classmethod
    def parse_comma_separated_ints(cls, v: Any) -> List[int]:
        if isinstance(v, str):
            return [int(i.strip()) for i in v.split(",") if i.strip()]
        return v

    # Валидатор для превращения строки из .env в список ссылок
    @field_validator("CHANNEL_URLS", mode="before")
    @classmethod
    def parse_comma_separated_str(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


# Global settings instance
settings = Settings()
