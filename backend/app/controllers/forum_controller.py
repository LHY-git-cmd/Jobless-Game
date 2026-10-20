"""论坛 HTTP 适配：同源、Cookie、有限游标；同步数据库全交给业务层。"""

from typing import Annotated
from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session
from ..common.config import get_settings
from ..common.database import get_db
from ..models.schemas.forum import PostRequest, CommentRequest, ReadAllRequest
from ..services import forum_service as service
from .auth_controller import enforce_same_origin

router = APIRouter(prefix='/api/forum', tags=['forum'])
Id = Annotated[int, Path(gt=0, le=9007199254740991)]
Cursor = Annotated[int | None, Query(gt=0, le=9007199254740991)]
Limit = Annotated[int, Query(ge=1, le=50)]


def token(request):
    """仅提取 HttpOnly Cookie，拒绝请求体指定身份。"""
    return request.cookies.get(get_settings().session_cookie_name)


async def read(request, operation, db, **params):
    """统一公开或私有读取的执行边界。"""
    return await service.execute(service.read_transaction, token(request), operation, params, db)


async def write(request, operation, payload, object_id, db):
    """任何状态修改均需现有同源校验。"""
    enforce_same_origin(request)
    return await service.execute(service.write_transaction, token(request), operation, payload, object_id, db)


@router.get('/posts')
async def posts(request: Request, cursor: Cursor = None, limit: Limit = 20, db: Session = Depends(get_db)):
    """倒序读取有限帖子摘要。"""
    return await read(request, 'posts', db, cursor=cursor, limit=limit)


@router.post('/posts')
async def create_post(payload: PostRequest, request: Request, db: Session = Depends(get_db)):
    """幂等发布文字主题。"""
    return await write(request, 'create_post', payload, None, db)


@router.get('/posts/{post_id}')
async def post(post_id: Id, request: Request, db: Session = Depends(get_db)):
    """读取可直接访问的完整帖子。"""
    return await read(request, 'post', db, post_id=post_id)


@router.get('/posts/{post_id}/comments')
async def comments(post_id: Id, request: Request, cursor: Cursor = None, limit: Limit = 20, db: Session = Depends(get_db)):
    """正序读取顶层评论。"""
    return await read(request, 'comments', db, post_id=post_id, cursor=cursor, limit=limit)


@router.post('/posts/{post_id}/comments')
async def create_comment(post_id: Id, payload: CommentRequest, request: Request, db: Session = Depends(get_db)):
    """发表评论或回复直接目标。"""
    return await write(request, 'create_comment', payload, post_id, db)


@router.get('/comments/{comment_id}/replies')
async def replies(comment_id: Id, request: Request, cursor: Cursor = None, limit: Limit = 10, db: Session = Depends(get_db)):
    """按需展开一条根评论下的有限回复。"""
    return await read(request, 'replies', db, comment_id=comment_id, cursor=cursor, limit=limit)


@router.get('/posts/{post_id}/comments/{comment_id}')
async def context(post_id: Id, comment_id: Id, request: Request, db: Session = Depends(get_db)):
    """通知直接定位目标和根上下文，无需翻过前面的页。"""
    return await read(request, 'context', db, post_id=post_id, comment_id=comment_id)


@router.put('/posts/{post_id}/like')
async def like_post(post_id: Id, request: Request, db: Session = Depends(get_db)):
    """明确设置帖子已点赞。"""
    return await write(request, 'posts', True, post_id, db)


@router.delete('/posts/{post_id}/like')
async def unlike_post(post_id: Id, request: Request, db: Session = Depends(get_db)):
    """明确取消帖子点赞。"""
    return await write(request, 'posts', False, post_id, db)


@router.put('/comments/{comment_id}/like')
async def like_comment(comment_id: Id, request: Request, db: Session = Depends(get_db)):
    """为评论或回复幂等点赞。"""
    return await write(request, 'comments', True, comment_id, db)


@router.delete('/comments/{comment_id}/like')
async def unlike_comment(comment_id: Id, request: Request, db: Session = Depends(get_db)):
    """取消评论或回复点赞。"""
    return await write(request, 'comments', False, comment_id, db)


@router.get('/notifications/unread-count')
async def unread(request: Request, db: Session = Depends(get_db)):
    """读取自己的未读数，最多100。"""
    return await read(request, 'unread', db)


@router.get('/notifications')
async def notifications(request: Request, cursor: Cursor = None, limit: Limit = 20, db: Session = Depends(get_db)):
    """消息按接收账号隔离并返回已读边界。"""
    return await read(request, 'notifications', db, cursor=cursor, limit=limit)


@router.put('/notifications/{notification_id}/read')
async def read_one(notification_id: Id, request: Request, db: Session = Depends(get_db)):
    """只标记自己拥有的一条消息。"""
    return await write(request, 'read', None, notification_id, db)


@router.post('/notifications/read-all')
async def read_all(payload: ReadAllRequest, request: Request, db: Session = Depends(get_db)):
    """保留查询边界之后到达的新通知。"""
    return await write(request, 'read_all', payload, None, db)
