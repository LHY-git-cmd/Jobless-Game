"""正式关卡、尝试和永久成长凭据；生产只由增量Flyway迁移建表。"""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.dialects.mysql import INTEGER
from sqlalchemy.orm import Mapped, mapped_column
from ...common.database import Base

UID = INTEGER(unsigned=True)


class GameLevel(Base):
    """稳定关卡身份，题目修订不改变权益身份。"""
    __tablename__ = 'game_levels'
    __table_args__ = (Index('ix_game_level_order', 'game_id', 'order_index'),)
    level_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    game_id: Mapped[str] = mapped_column(String(16))
    order_index: Mapped[int] = mapped_column(Integer)


class GameLevelVersion(Base):
    """版本化不可变题目和评分策略，JSON只保存单题有界数据。"""
    __tablename__ = 'game_level_versions'
    level_id: Mapped[str] = mapped_column(String(40), ForeignKey('game_levels.level_id'), primary_key=True)
    level_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition: Mapped[dict] = mapped_column(JSON)


class PlayerProgression(Base):
    """每账号一行摘要，等级由版本阈值计算。"""
    __tablename__ = 'player_progression'
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    total_stars: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class PlayerLevelProgress(Base):
    """稳定关卡最高星永久保留，速度只比较相同题目版本。"""
    __tablename__ = 'player_level_progress'
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    level_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    best_stars: Mapped[int] = mapped_column(Integer, default=0)
    best_duration_ms: Mapped[int] = mapped_column(Integer)
    best_level_version: Mapped[int] = mapped_column(Integer)
    first_completed_at: Mapped[datetime] = mapped_column(DateTime)
    first_three_star_at: Mapped[datetime | None] = mapped_column(DateTime)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class GameAttempt(Base):
    """绑定账号与不可变题目版本；扫雷隐藏棋盘不进入公开表示。"""
    __tablename__ = 'game_attempts'
    __table_args__ = (Index('ix_attempt_owner_active', 'user_id', 'status', 'level_id'), Index('ix_attempt_expiry', 'expires_at'))
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'))
    level_id: Mapped[str] = mapped_column(String(40))
    level_version: Mapped[int] = mapped_column(Integer)
    game_id: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    board: Mapped[dict] = mapped_column(JSON, default=dict)


class GameCompletion(Base):
    """不可变终盘摘要和原始结算快照，与尝试同窗口保留。"""
    __tablename__ = 'game_completions'
    attempt_id: Mapped[str] = mapped_column(String(36), ForeignKey('game_attempts.attempt_id', ondelete='CASCADE'), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer)
    stars: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)


class ProgressionGrant(Base):
    """永久奖励唯一键不包含题目版本或可清理的尝试外键。"""
    __tablename__ = 'progression_grants'
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    level_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    milestone: Mapped[str] = mapped_column(String(24), primary_key=True)
    xp_delta: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(Integer)
    attempt_id: Mapped[str] = mapped_column(String(36))
    granted_at: Mapped[datetime] = mapped_column(DateTime)


class PlayerQualification(Base):
    """三个长期资格成果；清理尝试不会删除资格。"""
    __tablename__ = 'player_qualifications'
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    level_version: Mapped[int] = mapped_column(Integer)
    attempt_id: Mapped[str] = mapped_column(String(36))
    completed_at: Mapped[datetime] = mapped_column(DateTime)


class ApiIdempotency(Base):
    """创建请求原始表示，先识别重试，再判断当前可变条件。"""
    __tablename__ = 'api_idempotency'
    __table_args__ = (Index('ix_api_idempotency_expiry', 'expires_at'),)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    resource_kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    key: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(36))
    original_status: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
