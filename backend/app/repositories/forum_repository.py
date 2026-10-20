"""论坛 SQL：有限页、批量作者/点赞关联和当前锁定读；不管理事务。"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import aliased
from ..models.entities import User
from ..models.entities.forum import ForumPost, ForumComment, ForumPostLike, ForumCommentLike, ForumNotification


def add(db, entity):
    """暂存内容或点赞，flush 和提交由 Service 处理。"""
    db.add(entity)


def lock_user(db, user_id):
    """写事务首锁用户，跨模块维持相同锁顺序。"""
    return db.scalar(select(User.id).where(User.id == user_id).with_for_update())


def object_by_id(db, model, object_id, lock=False):
    """锁定读刷新已缓存对象，防止 MySQL RR 旧快照覆盖并发计数。"""
    query = select(model).where(model.id == object_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def by_request(db, model, user_id, request_id):
    """用户锁后使用当前读，幂等重试能看到等待期间提交的内容。"""
    return db.scalar(select(model).where(model.user_id == user_id, model.request_id == request_id).with_for_update())


def latest_created(db, model, user_id):
    """利用作者索引读取最近一条发布，不扫描整个论坛。"""
    return db.scalar(select(model.created_at).where(model.user_id == user_id)
                     .order_by(model.created_at.desc(), model.id.desc()).limit(1).with_for_update())


def content_query(model, user_id, summary=False):
    """一次 SQL 关联当前作者和我的点赞，摘要在数据库截断。"""
    is_post = model is ForumPost
    like = ForumPostLike if is_post else ForumCommentLike
    key = like.post_id if is_post else like.comment_id
    columns = [model.id, model.user_id, model.created_at, model.like_count,
               User.username, User.avatar_id, (like.user_id.is_not(None)).label('liked_by_me')]
    if is_post:
        columns += [model.comment_count]
    else:
        target = aliased(ForumComment)
        target_user = aliased(User)
        columns += [model.post_id, model.root_comment_id, model.reply_to_comment_id, model.reply_count,
                    target_user.username.label('reply_to_username')]
    columns += [func.substr(model.body, 1, 160).label('excerpt')] if summary else [model.body]
    query = select(*columns).join(User, User.id == model.user_id).outerjoin(like, (key == model.id) & (like.user_id == (user_id or 0)))
    if not is_post:
        query = query.outerjoin(target, target.id == model.reply_to_comment_id).outerjoin(target_user, target_user.id == target.user_id)
    return query


def content(db, model, object_id, user_id):
    """读取单个公开对象，无密码及幂等凭据字段。"""
    row = db.execute(content_query(model, user_id).where(model.id == object_id)).mappings().first()
    return dict(row) if row else None


def page(db, model, user_id, cursor, limit, post_id=None, root_id=None):
    """ID 游标与服务端时间顺序一致，多取一行判断后续页。"""
    query = content_query(model, user_id, summary=model is ForumPost)
    descending = model is ForumPost
    if model is ForumComment:
        query = query.where(model.post_id == post_id, model.root_comment_id == root_id)
    if cursor:
        query = query.where(model.id < cursor if descending else model.id > cursor)
    rows = db.execute(query.order_by(model.id.desc() if descending else model.id).limit(limit+1)).mappings().all()
    return {'items': [dict(row) for row in rows[:limit]], 'next_cursor': rows[limit-1]['id'] if len(rows)>limit else None}


def like_record(db, model, key, user_id):
    """内容锁后读取实际点赞状态，重复 PUT/DELETE 无副作用。"""
    field = model.post_id if model is ForumPostLike else model.comment_id
    return db.scalar(select(model).where(field == key, model.user_id == user_id).with_for_update())


def remove_like(db, record):
    """只删除存在的赞，防止计数递减到负数。"""
    db.delete(record)


def add_notification(db, recipient_id, actor_id, kind, post_id, comment_id, event_key, now):
    """锁内按固定事件键去重，取消再点赞不重置历史已读状态。"""
    exists = db.scalar(select(ForumNotification.id).where(ForumNotification.recipient_id == recipient_id,
                       ForumNotification.event_key == event_key).with_for_update())
    if not exists:
        db.add(ForumNotification(recipient_id=recipient_id, actor_id=actor_id, kind=kind, post_id=post_id,
                                 comment_id=comment_id, event_key=event_key, created_at=now))


def unread(db, user_id):
    """最多读取100个未读编号，避免无限计数扫描。"""
    ids = db.scalars(select(ForumNotification.id).where(ForumNotification.recipient_id == user_id,
                     ForumNotification.read_at.is_(None)).limit(100)).all()
    latest = db.scalar(select(ForumNotification.id).where(ForumNotification.recipient_id == user_id)
                       .order_by(ForumNotification.id.desc()).limit(1))
    return {'count':len(ids), 'latest_id':latest or 0}


def notifications(db, user_id, cursor, limit):
    """消息列表一次关联互动者、帖子及可选评论，只返回有限摘要。"""
    query = select(ForumNotification.id, ForumNotification.kind, ForumNotification.post_id,
                   ForumNotification.comment_id, ForumNotification.read_at, ForumNotification.created_at,
                   User.username, User.avatar_id,
                   func.substr(func.coalesce(ForumComment.body, ForumPost.body), 1, 100).label('excerpt'))\
        .join(User, User.id == ForumNotification.actor_id).join(ForumPost, ForumPost.id == ForumNotification.post_id)\
        .outerjoin(ForumComment, ForumComment.id == ForumNotification.comment_id)\
        .where(ForumNotification.recipient_id == user_id)
    boundary = db.scalar(select(ForumNotification.id).where(ForumNotification.recipient_id == user_id)
                         .order_by(ForumNotification.id.desc()).limit(1)) or 0
    query = query.where(ForumNotification.id <= boundary)
    if cursor:
        query = query.where(ForumNotification.id < cursor)
    rows = db.execute(query.order_by(ForumNotification.id.desc()).limit(limit+1)).mappings().all()
    return {'items':[dict(row) for row in rows[:limit]], 'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None, 'through_id':boundary}


def mark_read(db, user_id, now, notification_id=None, through_id=None):
    """更新始终附接收人条件；重复已读保持第一次时间。"""
    conditions = [ForumNotification.recipient_id == user_id]
    if notification_id is not None:
        exists = db.scalar(select(ForumNotification.id).where(*conditions, ForumNotification.id == notification_id))
        if not exists:
            return False
        conditions.append(ForumNotification.id == notification_id)
    else:
        conditions.append(ForumNotification.id <= through_id)
    db.execute(update(ForumNotification).where(*conditions, ForumNotification.read_at.is_(None)).values(read_at=now))
    return True
