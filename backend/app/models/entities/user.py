"""数据库模型：用户账号及密码摘要映射。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import INTEGER, TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...common.database import Base

if TYPE_CHECKING:
    from .auth_session import AuthSession


class User(Base):
    """保存首次显示名、唯一账号键和带参数的 Argon2id 摘要。"""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username_key", name="uq_users_username_key"),)

    id: Mapped[int] = mapped_column(INTEGER(unsigned=True), primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    username_key: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # 数据库只保存编号；SQLite 类型变体仅用于隔离测试，生产字段由 Flyway 管理。
    avatar_id: Mapped[int] = mapped_column(Integer().with_variant(TINYINT(unsigned=True), "mysql"), nullable=False, default=1, server_default="1")
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
