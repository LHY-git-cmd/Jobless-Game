"""公共数据库基础设施：有界连接池和会话生命周期；生产表由 Flyway 创建。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import Settings, get_settings


class Base(DeclarativeBase):
    """所有持久化模型的声明式基类。"""


def build_engine(settings: Settings):
    """按 2 核/2GB 初始约束创建有限连接池。"""

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=1800,
        connect_args={"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5},
    )


engine = build_engine(get_settings())
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """为请求提供会自动归还连接的数据库会话。"""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

