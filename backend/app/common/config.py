"""集中读取登录服务配置，避免把生产凭据写入源码。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """登录 API 的环境变量配置与低资源默认值。"""

    database_url: str = Field(default="mysql+pymysql://app_user:change-me@127.0.0.1:3306/jobless_game?charset=utf8mb4", repr=False)
    session_cookie_name: str = "jobless_session"
    session_ttl_days: int = Field(default=7, ge=1, le=90)
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict"] = "lax"
    db_pool_size: int = Field(default=3, ge=1, le=10)
    db_max_overflow: int = Field(default=0, ge=0, le=2)
    db_pool_timeout: int = Field(default=3, ge=1, le=10)
    login_max_attempts: int = Field(default=5, ge=1, le=100)
    login_window_seconds: int = Field(default=60, ge=1, le=3600)
    login_hash_concurrency: int = Field(default=1, ge=1, le=1)
    max_request_body_bytes: int = Field(default=4096, ge=256, le=4096)
    # 一键通关默认关闭，仅在开发环境显式配置 DEV_QUICK_COMPLETE_ENABLED=true 时开启。
    dev_quick_complete_enabled: bool = False

    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env", env_prefix="", extra="ignore", hide_input_in_errors=True)


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每个请求重复解析环境变量。"""

    return Settings()

