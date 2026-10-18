"""跨业务复用的 Argon2id 密码处理、随机 token 和 UTC 时间工具。"""

import hashlib
import secrets
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.low_level import Type
from argon2.exceptions import VerificationError, VerifyMismatchError


PASSWORD_HASHER = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=1, type=Type.ID)


def hash_password(password: str) -> str:
    """使用显式 Argon2id 参数生成带盐密码摘要。"""

    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """验证密码；所有不匹配和格式异常都统一返回 False。"""

    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def new_session_token() -> tuple[str, str]:
    """生成只返回给 Cookie 的随机 token 及其 SHA-256 摘要。"""

    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("ascii")).hexdigest()


def hash_session_token(raw: str) -> str:
    """将请求 Cookie 转为可查询的 token 摘要。"""

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    """统一生成无时区 UTC 时间，兼容 MySQL DATETIME。"""

    return datetime.now(timezone.utc).replace(tzinfo=None)

