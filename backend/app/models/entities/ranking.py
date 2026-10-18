"""挑战进度、不可变通关快照与每人每榜最佳摘要；生产由 Flyway 建表。"""

from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, INTEGER
from sqlalchemy.orm import Mapped, mapped_column
from ...common.database import Base

USER_ID = INTEGER(unsigned=True)
RECORD_ID = BigInteger().with_variant(BIGINT(unsigned=True), "mysql").with_variant(Integer(), "sqlite")


class ChallengeProgress(Base):
    """每个账号只有一个当前轮次，JSON 仅保存固定三关的有限状态。"""
    __tablename__ = "challenge_progress"
    user_id: Mapped[int] = mapped_column(USER_ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    game_state: Mapped[dict] = mapped_column(JSON, nullable=False)
    total_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CompletionRecord(Base):
    """四类成绩分别保留最佳与最近三次；总榜自带三项快照。"""
    __tablename__ = "completion_records"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "attempt_id", name="uq_completion_attempt"),
        Index("ix_completion_recent", "user_id", "category", "completed_at", "id"),
    )
    id: Mapped[int] = mapped_column(RECORD_ID, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(USER_ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    mine_seconds: Mapped[int | None] = mapped_column(Integer)
    akari_seconds: Mapped[int | None] = mapped_column(Integer)
    sudoku_seconds: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LeaderboardEntry(Base):
    """每位玩家每个榜单只占一行，索引负责稳定分页排序。"""
    __tablename__ = "leaderboard_entries"
    __table_args__ = (Index("ix_leaderboard_order", "category", "best_duration_seconds", "achieved_at", "user_id"),)
    user_id: Mapped[int] = mapped_column(USER_ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    category: Mapped[str] = mapped_column(String(16), primary_key=True)
    best_record_id: Mapped[int] = mapped_column(RECORD_ID, ForeignKey("completion_records.id", ondelete="CASCADE"), nullable=False)
    best_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    achieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
