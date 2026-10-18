"""控制层：HTTP 同源校验、Cookie 和输入输出适配，不直接查询数据库。"""

from datetime import timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..common.config import Settings, get_settings
from ..common.database import get_db
from ..common.security import utc_now
from ..models.schemas.auth import LoginRequest, LoginResponse, UserResponse
from ..services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


def client_key(request: Request) -> str:
    """只信任直接连接的客户端地址；反向代理应在边界层完成限流。"""

    return request.client.host if request.client else "unknown"


def enforce_same_origin(request: Request) -> None:
    """状态修改请求必须给出同源 Origin/Referer；无头客户端也须显式声明来源。"""

    candidate = request.headers.get("origin") or request.headers.get("referer")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="请求来源无效。")
    if not candidate:
        raise HTTPException(status_code=403, detail="请求来源无效。")
    parsed = urlparse(candidate)
    expected = urlparse(str(request.base_url))
    def origin_tuple(url):
        return url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80)
    try:
        valid = bool(parsed.netloc) and origin_tuple(parsed) == origin_tuple(expected)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请求来源无效。")


def set_session_cookie(response: Response, raw_token: str, config: Settings, expires_at) -> None:
    """设置 HttpOnly、SameSite 会话 Cookie；HTTPS 部署打开 Secure。"""

    response.set_cookie(
        config.session_cookie_name,
        raw_token,
        max_age=max(0, int((expires_at - utc_now()).total_seconds())),
        expires=expires_at.replace(tzinfo=timezone.utc),
        httponly=True,
        secure=config.cookie_secure,
        samesite=config.cookie_samesite,
        path="/",
    )


def clear_session_cookie(response: Response, config: Settings) -> None:
    """注销后立即覆盖并删除浏览器 Cookie。"""

    response.delete_cookie(config.session_cookie_name, path="/")


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """适配登录请求；业务和事务交给 Service，Cookie 由控制层设置。"""
    enforce_same_origin(request)
    user, created, raw_token, expires_at = await auth_service.login(payload, client_key(request), db, settings)
    set_session_cookie(response, raw_token, settings, expires_at)
    return LoginResponse(user=UserResponse(id=user.id, username=user.username), created=created)


@router.get("/me", response_model=UserResponse)
async def me(request: Request, db: Session = Depends(get_db)):
    """提取 Cookie 后查询当前用户，仅输出公开字段。"""
    user = await auth_service.get_current_user(request.cookies.get(settings.session_cookie_name), db)
    return UserResponse(id=user.id, username=user.username)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """校验来源并使当前会话失效，成功后清除浏览器 Cookie。"""
    enforce_same_origin(request)
    await auth_service.logout(request.cookies.get(settings.session_cookie_name), db)
    clear_session_cookie(response, settings)
