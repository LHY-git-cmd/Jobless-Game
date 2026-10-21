"""双人房间、成员、提交和占用；JSON只保存一题和最终结果。"""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from .progression import UID
from ...common.database import Base


class PKRoom(Base):
    """最多两名玩家，未开始前不对外返回puzzle。"""
    __tablename__ = 'pk_rooms'
    __table_args__ = (Index('ix_pk_room_status_expiry', 'status', 'expires_at'), Index('ix_pk_room_retention', 'status', 'finished_at'))
    room_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_code: Mapped[str] = mapped_column(String(8), unique=True)
    game_id: Mapped[str] = mapped_column(String(16))
    difficulty: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    puzzle: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(32))


class PKParticipant(Base):
    """成员独立准备与断线时间，退出后保留终态可读性。"""
    __tablename__ = 'pk_participants'
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey('pk_rooms.room_id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    readiness_created: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime)
    left_at: Mapped[datetime | None] = mapped_column(DateTime)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime)


class PKSubmission(Base):
    """每人一条不可变有效终盘摘要，非法终盘不占提交身份。"""
    __tablename__ = 'pk_submissions'
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey('pk_rooms.room_id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime)


class PlayerPKOccupancy(Base):
    """用户唯一PK身份，排队或房间占用的跨入口约束。"""
    __tablename__ = 'player_pk_occupancy'
    __table_args__ = (Index('ix_pk_occupancy_room', 'room_id'), Index('ix_pk_occupancy_ticket', 'ticket_id'))
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    room_id: Mapped[str | None] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    # V8才添加票据关联；同一行只能占用房间或排队票之一。
    ticket_id: Mapped[str | None] = mapped_column(String(36))
