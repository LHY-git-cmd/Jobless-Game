"""竞技积分摘要、唯一结算流水与有期限邀请；生产表由Flyway增量创建。"""
from datetime import datetime
from sqlalchemy import DateTime,ForeignKey,Index,Integer,JSON,String
from sqlalchemy.orm import Mapped,mapped_column
from ...common.database import Base
from .progression import UID


class ArenaAccount(Base):
    """账号仅初始化一次100积分，使用有符号整数允许负分。"""
    __tablename__='arena_accounts'
    __table_args__=(Index('ix_arena_points','points','user_id'),)
    user_id:Mapped[int]=mapped_column(UID,ForeignKey('users.id',ondelete='CASCADE'),primary_key=True)
    points:Mapped[int]=mapped_column(Integer,default=100)
    revision:Mapped[int]=mapped_column(Integer,default=0)


class ArenaLedger(Base):
    """每局每人只能结算一次；不关联可清理房间外键以保留积分凭据。"""
    __tablename__='arena_ledger'
    __table_args__=(Index('ix_arena_ledger_user','user_id','created_at'),)
    room_id:Mapped[str]=mapped_column(String(36),primary_key=True)
    user_id:Mapped[int]=mapped_column(UID,ForeignKey('users.id',ondelete='CASCADE'),primary_key=True)
    delta:Mapped[int]=mapped_column(Integer)
    balance:Mapped[int]=mapped_column(Integer)
    created_at:Mapped[datetime]=mapped_column(DateTime)


class ArenaInvitation(Base):
    """定向邀请必须对方明确接受；每次接受绑定唯一房间，过期不强拉玩家。"""
    __tablename__='arena_invitations'
    __table_args__=(Index('ix_arena_invite_target','target_id','status','expires_at'),
                    Index('ix_arena_invite_sender','sender_id','status','expires_at'),
                    Index('ix_arena_invite_expiry','expires_at','status'))
    invitation_id:Mapped[str]=mapped_column(String(36),primary_key=True)
    sender_id:Mapped[int]=mapped_column(UID,ForeignKey('users.id',ondelete='CASCADE'))
    target_id:Mapped[int]=mapped_column(UID,ForeignKey('users.id',ondelete='CASCADE'))
    game_id:Mapped[str]=mapped_column(String(16))
    status:Mapped[str]=mapped_column(String(16),default='pending')
    created_at:Mapped[datetime]=mapped_column(DateTime)
    expires_at:Mapped[datetime]=mapped_column(DateTime)
    room_id:Mapped[str|None]=mapped_column(String(36))


class ArenaPuzzleHistory(Base):
    """每账号/每游戏一行，最多保存最近4个已开局原题，不依赖房间历史保留期。"""
    __tablename__='arena_puzzle_history'
    user_id:Mapped[int]=mapped_column(UID,ForeignKey('users.id',ondelete='CASCADE'),primary_key=True)
    game_id:Mapped[str]=mapped_column(String(16),primary_key=True)
    recent:Mapped[list]=mapped_column(JSON,default=list)
    revision:Mapped[int]=mapped_column(Integer,default=0)
