"""论坛输入 DTO：禁止伪造作者和根归属，文字以 Unicode 码点限长。"""

from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class PostRequest(BaseModel):
    """直接发布正文，只接受严格字符串并移除首尾空白。"""
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    body: StrictStr = Field(min_length=1, max_length=2000)

    @field_validator('body', mode='before')
    @classmethod
    def trim(cls, value):
        """先去空白再校验长度，不把数字等值转换为字符串。"""
        return value.strip() if isinstance(value, str) else value


class CommentRequest(BaseModel):
    """直接回复对象由服务验证，根评论不能由客户端指定。"""
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    body: StrictStr = Field(min_length=1, max_length=500)
    reply_to_comment_id: int | None = Field(default=None, gt=0, le=9007199254740991, strict=True)

    @field_validator('body', mode='before')
    @classmethod
    def trim(cls, value):
        """评论与正文使用相同的空白规范。"""
        return value.strip() if isinstance(value, str) else value


class ReadAllRequest(BaseModel):
    """全部已读只能更新用户此次看到的通知范围。"""
    model_config = ConfigDict(extra='forbid')
    through_id: int = Field(ge=0, le=9007199254740991, strict=True)
