"""有界自动匹配票，等待索引按状态/到达顺序读取。"""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from .progression import UID
from ...common.database import Base


class MatchmakingTicket(Base):
    """终态保留24小时支持重试，配对后不可用取消票退出房间。"""
    __tablename__ = 'matchmaking_tickets'
    __table_args__ = (Index('ix_ticket_waiting', 'status', 'created_at', 'ticket_id'), Index('ix_ticket_expiry', 'expires_at'))
    ticket_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(UID, ForeignKey('users.id', ondelete='CASCADE'))
    pool: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    room_id: Mapped[str | None] = mapped_column(String(36))
