"""头像业务：认证和单字段更新在同一个有界工作线程与事务中完成，不处理图片。"""

from sqlalchemy.orm import Session

from ..common import concurrency
from ..common.exceptions import AppError
from ..models.schemas.avatar import AvatarRequest
from ..repositories import user_repository
from . import auth_service


def update_transaction(raw_token: str | None, payload: AvatarRequest, db: Session) -> dict:
    """只修改当前会话账号的头像字段，失败回滚，不影响密码、成绩或棋局。"""
    try:
        current = auth_service.current_session(raw_token, db)
        if not current:
            raise AppError(401, "未登录。")
        user = current[1]
        user_repository.set_avatar(db, user.id, payload.avatar_id)
        result = {"id": user.id, "username": user.username, "avatar_id": payload.avatar_id}
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


async def update(raw_token: str | None, payload: AvatarRequest, db: Session) -> dict:
    """复用现有四个数据库执行槽，过载立即拒绝，不占用密码计算槽。"""
    return await concurrency.bounded_db_call(update_transaction, raw_token, payload, db)
