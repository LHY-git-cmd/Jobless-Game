"""头像控制层：同源检查、提取 Cookie 和输出公开用户信息，业务事务交给 Service。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..common.config import get_settings
from ..common.database import get_db
from ..models.schemas.auth import UserResponse
from ..models.schemas.avatar import AvatarRequest
from ..services import avatar_service
from .auth_controller import enforce_same_origin

router = APIRouter(prefix="/api/auth", tags=["avatar"])


@router.put("/avatar", response_model=UserResponse)
async def update_avatar(payload: AvatarRequest, request: Request, db: Session = Depends(get_db)):
    """通过当前登录会话更换预设头像；重复选择相同编号具有相同结果。"""
    enforce_same_origin(request)
    return await avatar_service.update(request.cookies.get(get_settings().session_cookie_name), payload, db)
