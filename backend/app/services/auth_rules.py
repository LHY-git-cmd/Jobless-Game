"""登录专属用户名和密码规则；与前端保持相同 Unicode 15.1 汉字集合。"""

import re

# 汉字计 3、ASCII 字母数字计 2，上限 24；排除扩展块内未分配码位。
HAN_RANGES = (
    "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufa6d\ufa70-\ufad9"
    "\U00020000-\U0002a6df\U0002a700-\U0002b739\U0002b740-\U0002b81d"
    "\U0002b820-\U0002cea1\U0002ceb0-\U0002ebe0\U0002ebf0-\U0002ee5d"
    "\U0002f800-\U0002fa1d\U00030000-\U0003134a\U00031350-\U000323af"
)
HAN_RE = re.compile(f"[{HAN_RANGES}]")
ALLOWED_USERNAME_RE = re.compile(f"[A-Za-z0-9{HAN_RANGES}]+")


def username_units(username: str) -> int:
    """返回前后端统一的两倍长度单位。"""
    return sum(3 if HAN_RE.fullmatch(char) else 2 for char in username)


def validate_username(username: str) -> str | None:
    """校验字符集合和用户名长度，不自动去除空格。"""
    if not isinstance(username, str) or not username or not ALLOWED_USERNAME_RE.fullmatch(username):
        return "用户名只能包含汉字、英文字母和数字。"
    if username_units(username) > 24:
        return "用户名长度不能超过 12 个字符。"
    return None


def username_key(username: str) -> str:
    """仅折叠 ASCII 英文大小写，保留其他字符差异。"""
    return "".join(char.lower() if "A" <= char <= "Z" else char for char in username)


def validate_password(password: str) -> str | None:
    """密码至少六个 Unicode 字符，保留空格和大小写。"""
    if not isinstance(password, str) or len(password) < 6:
        return "密码至少需要 6 个字符。"
    return None
