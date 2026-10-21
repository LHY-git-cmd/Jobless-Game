"""v1资源SQL基础操作；用户锁为每账号新增行提供固定串行入口。"""

from sqlalchemy import select
from ..models.entities import User


def get(db, model, identity, lock=True):
    """写事务用当前锁定读，规避MySQL RR旧快照和ORM缓存。"""
    return db.get(model, identity, with_for_update=lock, populate_existing=True)


def rows(db, model, *conditions, lock=True, limit=50, order=None):
    """有界读取；写路径使用当前读，所有列表有固定上限。"""
    query = select(model).where(*conditions)
    if order is not None:
        query = query.order_by(*(order if isinstance(order, tuple) else (order,)))
    query = query.limit(limit).execution_options(populate_existing=True)
    return list(db.scalars(query.with_for_update() if lock else query))


def lock_users(db, user_ids):
    """跨用户事务按升序加锁，防止匹配与取消锁顺序倒置。"""
    for uid in sorted(set(user_ids)):
        db.scalar(select(User.id).where(User.id == uid).with_for_update())
