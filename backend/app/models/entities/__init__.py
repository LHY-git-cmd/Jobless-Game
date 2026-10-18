"""注册账号与排行榜 ORM 实体，确保关系映射可解析；不执行建表。"""

from .user import User
from .auth_session import AuthSession
from .ranking import ChallengeProgress, CompletionRecord, LeaderboardEntry

__all__ = ["User", "AuthSession", "ChallengeProgress", "CompletionRecord", "LeaderboardEntry"]
