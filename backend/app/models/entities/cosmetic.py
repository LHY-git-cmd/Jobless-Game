"""有限外观目录、永久权益与可版本化装备配置。"""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from .progression import UID
from ...common.database import Base


class CosmeticDefinition(Base):
    """静态主题定义，不包括货币和商店。"""
    __tablename__ = 'cosmetic_definitions'
    cosmetic_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    required_stars: Mapped[int] = mapped_column(Integer)
    asset_version: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean)


class PlayerCosmetic(Base):
    """已授予外观不因后续提高门槛而回收。"""
    __tablename__ = 'player_cosmetics'
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    cosmetic_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(24))


class PlayerAppearance(Base):
    """完整装备配置和乐观锁版本。"""
    __tablename__ = 'player_appearance'
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    configuration: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=0)
