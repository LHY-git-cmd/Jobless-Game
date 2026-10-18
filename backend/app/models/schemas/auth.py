"""模型层：登录 API 请求 DTO 和脱敏响应模型，不包含数据库内部字段。"""

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """保留密码原始内容，仅限制请求体中的合理字段长度。"""

    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6)


class UserResponse(BaseModel):
    """当前登录用户的公开显示名。"""

    id: int
    username: str


class LoginResponse(BaseModel):
    """登录成功时返回用户信息，不回显密码或 token。"""

    user: UserResponse
    created: bool

