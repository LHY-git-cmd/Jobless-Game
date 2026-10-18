"""会话查询、保存和删除；不处理 HTTP，也不提交事务。"""

from sqlalchemy import delete, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from ..models.entities import AuthSession


def find_by_token_hash(db: Session, token_hash: str) -> AuthSession | None:
    """查询 token 摘要对应记录，由业务层判断是否到期。"""
    return db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))


def add(db: Session, session: AuthSession) -> None:
    """暂存新会话，保留登录事务的原子性。"""
    db.add(session)


def remove(db: Session, session: AuthSession) -> None:
    """标记删除单个过期会话。"""
    db.delete(session)


def remove_by_token_hash(db: Session, token_hash: str) -> None:
    """注销仅删除当前 token 对应的会话。"""
    db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))


def remove_expired_batch(connection: Connection, batch_size: int) -> int:
    """利用到期索引执行 MySQL 有界删除，由调用方管理每批事务。"""
    result = connection.execute(
        text("DELETE FROM auth_sessions WHERE expires_at < UTC_TIMESTAMP() ORDER BY expires_at LIMIT :batch_size"),
        {"batch_size": batch_size},
    )
    return result.rowcount
