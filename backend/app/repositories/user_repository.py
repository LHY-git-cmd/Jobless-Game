"""用户数据访问；事务提交与回滚由业务层决定。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import User


def find_by_username_key(db: Session, key: str) -> User | None:
    """按已折叠 ASCII 大小写的唯一账号键查询。"""
    return db.scalar(select(User).where(User.username_key == key))


def add(db: Session, user: User) -> None:
    """暂存新账号，不提交事务；唯一键冲突在业务层 flush 时处理。"""
    db.add(user)
