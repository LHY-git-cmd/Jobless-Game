"""头像写入请求：只允许清单中的严格整数编号，不接收文件、路径或用户 ID。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...common.avatar_catalog import avatar_ids


class AvatarRequest(BaseModel):
    """用户归属只由会话确定，拒绝多余字段和隐式类型转换。"""

    model_config = ConfigDict(extra="forbid")
    avatar_id: int = Field(strict=True, ge=1, le=255)

    @field_validator("avatar_id")
    @classmethod
    def require_available_avatar(cls, value: int) -> int:
        """按发布清单而非连续范围验证，未来停用头像时仍能拒绝未知编号。"""
        if value not in avatar_ids():
            raise ValueError("请选择可用的头像。")
        return value
