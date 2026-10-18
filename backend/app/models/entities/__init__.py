"""注册两个 ORM 实体，确保关系映射可解析；不执行建表。"""

from .user import User
from .auth_session import AuthSession

__all__ = ["User", "AuthSession"]
