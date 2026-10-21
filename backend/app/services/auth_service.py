"""登录业务编排和事务控制；只通过 Repository 访问数据库，不操作 HTTP/Cookie。"""

from datetime import datetime, timedelta
from threading import BoundedSemaphore

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..common import concurrency
from ..common.config import Settings, get_settings
from ..common.exceptions import AppError, ExecutionBusyError
from ..common.security import PASSWORD_HASHER, hash_password, hash_session_token, new_session_token, utc_now, verify_password
from ..models.entities import AuthSession, User
from ..models.schemas.auth import LoginRequest
from ..repositories import session_repository, user_repository
from .auth_rules import username_key, validate_password, validate_username
from .login_limiter import LoginRateLimiter

settings = get_settings()
rate_limiter = LoginRateLimiter(settings.login_max_attempts, settings.login_window_seconds)
hash_semaphore = BoundedSemaphore(settings.login_hash_concurrency)


def current_session(raw_token: str | None, db: Session) -> tuple[AuthSession, User] | None:
    """验证凭据及有效期，过期记录失效并在独立事务中删除。"""
    if not raw_token:
        return None
    session = session_repository.find_by_token_hash(db, hash_session_token(raw_token))
    if not session:
        return None
    if session.expires_at <= utc_now():
        session_repository.remove(db, session)
        db.commit()
        return None
    return session, session.user


def login_transaction(payload: LoginRequest, db: Session, config: Settings) -> tuple[User, bool, str, datetime]:
    """注册/校验和创建会话共用事务，唯一键竞争后仍验证胜出账号的原密码。"""
    for field, error in [("username", validate_username(payload.username)), ("password", validate_password(payload.password))]:
        if error:
            raise AppError(422, {"field": field, "message": error})
    key = username_key(payload.username)
    user = user_repository.find_by_username_key(db, key)
    created = False
    if user:
        if not verify_password(user.password_hash, payload.password):
            raise AppError(401, "用户名或密码错误。")
        if PASSWORD_HASHER.check_needs_rehash(user.password_hash):
            user.password_hash = hash_password(payload.password)
    else:
        user = User(username=payload.username, username_key=key, password_hash=hash_password(payload.password), created_at=utc_now())
        user_repository.add(db, user)
        try:
            db.flush()
            created = True
        except IntegrityError:
            db.rollback()
            user = user_repository.find_by_username_key(db, key)
            if not user or not verify_password(user.password_hash, payload.password):
                raise AppError(401, "用户名或密码错误。")
    now = utc_now()
    raw_token, token_hash = new_session_token()
    expires_at = now + timedelta(days=config.session_ttl_days)
    session_repository.add(db, AuthSession(user_id=user.id, token_hash=token_hash, created_at=now, expires_at=expires_at))
    db.commit()
    return user, created, raw_token, expires_at


async def login(payload: LoginRequest, client_key: str, db: Session, config: Settings):
    """先限频并获取唯一计算槽，再在线程中执行密码/数据库事务。"""
    if not rate_limiter.allow(client_key):
        raise AppError(429, "登录请求过于频繁，请稍后重试。", {"Retry-After": str(config.login_window_seconds)})
    if not hash_semaphore.acquire(blocking=False):
        raise AppError(429, "登录服务繁忙，请稍后重试。", {"Retry-After": "3"})

    def execute_login():
        """计算槽随工作线程释放，避免断连后并行计算增加。"""
        try:
            return login_transaction(payload, db, config)
        finally:
            hash_semaphore.release()

    try:
        return await concurrency.bounded_db_call(execute_login)
    except ExecutionBusyError:
        # 执行器明确拒绝时没有启动工作线程，需要归还预留的计算槽。
        hash_semaphore.release()
        raise


async def get_current_user(raw_token: str | None, db: Session) -> User:
    """普通会话查询使用公共执行槽，不占用密码计算槽。"""
    current = await concurrency.bounded_db_call(current_session, raw_token, db)
    if not current:
        raise AppError(401, "未登录。")
    return current[1]


def logout_transaction(raw_token: str | None, db: Session) -> None:
    """注销仅使当前会话失效，提交边界由业务层管理。"""
    if raw_token:
        session_repository.remove_by_token_hash(db, hash_session_token(raw_token))
        db.commit()
        from .pk_runtime import runtime
        runtime.revoke(raw_token)


async def logout(raw_token: str | None, db: Session) -> None:
    """通过公共有界执行器运行注销事务。"""
    await concurrency.bounded_db_call(logout_transaction, raw_token, db)
