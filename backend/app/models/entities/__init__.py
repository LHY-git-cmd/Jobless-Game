"""注册账号、排行榜和论坛 ORM 实体，确保关系映射可解析；不执行建表。"""

from .user import User
from .auth_session import AuthSession
from .ranking import ChallengeProgress, CompletionRecord, LeaderboardEntry
from .forum import ForumPost, ForumComment, ForumPostLike, ForumCommentLike, ForumNotification
from . import progression, cosmetic, pk, matchmaking

__all__ = ["User", "AuthSession", "ChallengeProgress", "CompletionRecord", "LeaderboardEntry",
           "ForumPost", "ForumComment", "ForumPostLike", "ForumCommentLike", "ForumNotification"]
