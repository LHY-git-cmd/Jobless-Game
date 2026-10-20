"""文字论坛五张实体；生产结构由 V4 管理，SQLite 变体仅供隔离测试。"""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ...common.database import Base
from .ranking import RECORD_ID, USER_ID


class ForumPost(Base):
    """主题正文和事务内维护的互动计数。"""
    __tablename__ = 'forum_posts'
    __table_args__ = (UniqueConstraint('user_id', 'request_id', name='uq_forum_post_request'),
                      Index('ix_forum_post_author', 'user_id', 'created_at', 'id'))
    id: Mapped[int] = mapped_column(RECORD_ID, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(USER_ID, ForeignKey('users.id'), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ForumComment(Base):
    """根评论与回复共表，根编号保持界面两层，直接目标保留对话关系。"""
    __tablename__ = 'forum_comments'
    __table_args__ = (UniqueConstraint('user_id', 'request_id', name='uq_forum_comment_request'),
                      Index('ix_forum_comment_page', 'post_id', 'root_comment_id', 'id'),
                      Index('ix_forum_reply_page', 'root_comment_id', 'id'),
                      Index('ix_forum_comment_author', 'user_id', 'created_at', 'id'))
    id: Mapped[int] = mapped_column(RECORD_ID, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(RECORD_ID, ForeignKey('forum_posts.id'), nullable=False)
    user_id: Mapped[int] = mapped_column(USER_ID, ForeignKey('users.id'), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    root_comment_id: Mapped[int | None] = mapped_column(RECORD_ID, ForeignKey('forum_comments.id'))
    reply_to_comment_id: Mapped[int | None] = mapped_column(RECORD_ID, ForeignKey('forum_comments.id'))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ForumPostLike(Base):
    """联合主键限制同账号同帖子最多一条点赞记录。"""
    __tablename__ = 'forum_post_likes'
    post_id: Mapped[int] = mapped_column(RECORD_ID, ForeignKey('forum_posts.id'), primary_key=True)
    user_id: Mapped[int] = mapped_column(USER_ID, ForeignKey('users.id'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ForumCommentLike(Base):
    """顶层评论和回复各自拥有独立点赞状态。"""
    __tablename__ = 'forum_comment_likes'
    comment_id: Mapped[int] = mapped_column(RECORD_ID, ForeignKey('forum_comments.id'), primary_key=True)
    user_id: Mapped[int] = mapped_column(USER_ID, ForeignKey('users.id'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ForumNotification(Base):
    """永久保留首次互动提醒，已读状态归属于接收账号。"""
    __tablename__ = 'forum_notifications'
    __table_args__ = (UniqueConstraint('recipient_id', 'event_key', name='uq_forum_notification_event'),
                      Index('ix_forum_notification_page', 'recipient_id', 'id'),
                      Index('ix_forum_notification_unread', 'recipient_id', 'read_at', 'id'))
    id: Mapped[int] = mapped_column(RECORD_ID, primary_key=True, autoincrement=True)
    recipient_id: Mapped[int] = mapped_column(USER_ID, ForeignKey('users.id'), nullable=False)
    actor_id: Mapped[int] = mapped_column(USER_ID, ForeignKey('users.id'), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    post_id: Mapped[int] = mapped_column(RECORD_ID, ForeignKey('forum_posts.id'), nullable=False)
    comment_id: Mapped[int | None] = mapped_column(RECORD_ID, ForeignKey('forum_comments.id'))
    event_key: Mapped[str] = mapped_column(String(100), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
