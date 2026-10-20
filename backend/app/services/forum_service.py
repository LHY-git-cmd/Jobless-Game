"""论坛事务编排：认证、用户→帖子→评论锁、幂等与通知原子提交。"""

from math import ceil
from ..common.concurrency import bounded_db_call
from ..common.config import get_settings
from ..common.exceptions import AppError
from ..common.security import utc_now
from ..models.entities.forum import ForumPost, ForumComment, ForumPostLike, ForumCommentLike
from ..repositories import forum_repository as repo
from .auth_service import current_session


def identity(db, token, required=False):
    """公开读将失效会话视为游客，写操作必须由 Cookie 决定账号。"""
    session = current_session(token, db)
    user_id = session[1].id if session else None
    if required and not user_id:
        raise AppError(401, '未登录。')
    return user_id


def require_object(db, model, object_id, lock=False):
    """缺失内容统一返回可理解的404。"""
    obj = repo.object_by_id(db, model, object_id, lock)
    if obj is None:
        raise AppError(404, '讨论内容不存在，请返回论坛。')
    return obj


def notify(db, recipient, actor, kind, post_id, comment_id, key, now):
    """自己的互动不产生消息，通知与互动处于同一事务。"""
    if recipient != actor:
        repo.add_notification(db, recipient, actor, kind, post_id, comment_id, key, now)


def check_frequency(db, model, user_id, now, interval):
    """在账号锁和幂等确认后检查可配置发布间隔。"""
    previous = repo.latest_created(db, model, user_id)
    if previous:
        wait = ceil(interval - (now - previous).total_seconds())
        if wait > 0:
            raise AppError(429, f'发布过于频繁，请在 {wait} 秒后重试。', {'Retry-After':str(wait)})


def read_transaction(token, operation, params, db):
    """一次有界工作线程内认证并读取，不跨线程触发 ORM 查询。"""
    user_id = identity(db, token, operation in ('unread','notifications'))
    if operation == 'posts':
        return repo.page(db, ForumPost, user_id, **params)
    if operation == 'post':
        require_object(db, ForumPost, params['post_id'])
        return repo.content(db, ForumPost, params['post_id'], user_id)
    if operation in ('comments','context'):
        require_object(db, ForumPost, params['post_id'])
        if operation == 'comments':
            return repo.page(db, ForumComment, user_id, **params)
        target = require_object(db, ForumComment, params['comment_id'])
        if target.post_id != params['post_id']:
            raise AppError(404, '此帖子没有该评论。')
        root_id = target.root_comment_id or target.id
        return {'target':repo.content(db, ForumComment, target.id, user_id), 'root':repo.content(db, ForumComment, root_id, user_id)}
    if operation == 'replies':
        root = require_object(db, ForumComment, params['comment_id'])
        if root.root_comment_id is not None:
            raise AppError(409, '请从顶层评论展开回复。')
        return repo.page(db, ForumComment, user_id, params['cursor'], params['limit'], root.post_id, root.id)
    if operation == 'unread':
        return repo.unread(db, user_id)
    return repo.notifications(db, user_id, **params)


def create_content(db, user_id, operation, payload, object_id, now):
    """先确认幂等，再限频，最后在固定锁顺序下创建内容和提醒。"""
    is_post = operation == 'create_post'
    model = ForumPost if is_post else ForumComment
    old = repo.by_request(db, model, user_id, str(payload.request_id))
    if old:
        same = old.body == payload.body
        if not is_post:
            same = same and old.post_id == object_id and old.reply_to_comment_id == payload.reply_to_comment_id
        if not same:
            raise AppError(409, '请求编号已用于其他内容，请勿修改重试负载。')
        return model, old.id
    # 帖子锁先于所有评论锁；跨帖检查在限频前返回确定的关联冲突。
    post = target = root = None
    if not is_post:
        post = require_object(db, ForumPost, object_id, True)
        if payload.reply_to_comment_id:
            target = require_object(db, ForumComment, payload.reply_to_comment_id, True)
            if target.post_id != post.id:
                raise AppError(409, '不能回复其他帖子中的评论。')
            root = require_object(db, ForumComment, target.root_comment_id or target.id, True)
            if root.post_id != post.id or root.root_comment_id is not None:
                raise AppError(409, '回复必须属于同一条顶层评论。')
    config = get_settings()
    check_frequency(db, model, user_id, now, config.forum_post_interval_seconds if is_post else config.forum_comment_interval_seconds)
    common = dict(user_id=user_id, request_id=str(payload.request_id), body=payload.body, created_at=now, like_count=0)
    # 兼容已执行的 V4：旧 title 列写空字符串，不生成标题、不参与正文幂等或展示。
    obj = ForumPost(**common,title='',comment_count=0) if is_post else ForumComment(**common,post_id=post.id,
             root_comment_id=root.id if root else None, reply_to_comment_id=target.id if target else None, reply_count=0)
    repo.add(db, obj)
    db.flush()
    if not is_post:
        post.comment_count += 1
        if root:
            root.reply_count += 1
        notify(db, target.user_id if target else post.user_id, user_id, 'reply' if target else 'comment', post.id, obj.id, f'comment:{obj.id}', now)
    return model, obj.id


def change_like(db, user_id, kind, object_id, enabled, now):
    """内容行锁保护计数，联合主键和通知键保证重试安全。"""
    is_post = kind == 'posts'
    if is_post:
        obj = require_object(db, ForumPost, object_id, True)
        post_id = obj.id
    else:
        # 先只读确定帖子，再按帖子→评论顺序锁定；内容不支持删除或移动。
        snapshot = require_object(db, ForumComment, object_id)
        post_id = snapshot.post_id
        require_object(db, ForumPost, post_id, True)
        obj = require_object(db, ForumComment, object_id, True)
    model = ForumPostLike if is_post else ForumCommentLike
    old = repo.like_record(db, model, object_id, user_id)
    if enabled and old is None:
        fields = {'post_id' if is_post else 'comment_id':object_id, 'user_id':user_id, 'created_at':now}
        repo.add(db, model(**fields))
        obj.like_count += 1
        notify(db, obj.user_id, user_id, 'post_like' if is_post else 'comment_like', post_id,
               None if is_post else object_id, f'like:{kind}:{object_id}:{user_id}', now)
    elif not enabled and old is not None:
        repo.remove_like(db, old)
        obj.like_count -= 1
    return {'like_count':obj.like_count, 'liked_by_me':enabled}


def write_transaction(token, operation, payload, object_id, db):
    """所有写入失败整体回滚，服务只返回已确认的公开字段。"""
    try:
        user_id = identity(db, token, True)
        repo.lock_user(db, user_id)
        now = utc_now()
        if operation in ('create_post','create_comment'):
            model, new_id = create_content(db, user_id, operation, payload, object_id, now)
            db.flush()
            result = repo.content(db, model, new_id, user_id)
        elif operation in ('posts','comments'):
            result = change_like(db, user_id, operation, object_id, payload, now)
        else:
            found = repo.mark_read(db, user_id, now, notification_id=object_id if operation == 'read' else None,
                                   through_id=payload.through_id if operation == 'read_all' else None)
            if not found:
                raise AppError(404, '消息不存在。')
            db.flush()
            result = repo.unread(db, user_id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


async def execute(function, *args):
    """复用四槽数据库执行器，不引入新线程池或常驻服务。"""
    return await bounded_db_call(function, *args)
