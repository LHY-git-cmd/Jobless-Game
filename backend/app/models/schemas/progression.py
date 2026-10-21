"""v1严格DTO：禁止客户端指定奖励、用时、用户和胜者。"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class StrictDTO(BaseModel):
    """所有新资源均拒绝额外字段。"""
    model_config = ConfigDict(extra='forbid')


class AttemptCreate(StrictDTO):
    """只有显式开始动作才创建计时凭据。"""
    level_id: str = Field(min_length=1, max_length=40)
    level_version: int = Field(ge=1, strict=True)
    mode: Literal['campaign', 'qualification']


class AttemptPatch(StrictDTO):
    """客户端唯一允许的尝试状态迁移。"""
    status: Literal['abandoned']


class CompletionPut(StrictDTO):
    """实际允许字段进一步由绑定游戏校验。"""
    bulbs: list[StrictInt] | None = Field(default=None, max_length=400)
    values: list[StrictInt] | None = Field(default=None, min_length=81, max_length=81)


class EmptyDTO(StrictDTO):
    """正式揭格不接受客户端棋盘。"""


class AppearancePut(StrictDTO):
    """四个槽必须完整提交，锁定权益由服务端检查。"""
    theme_id: Literal['default', 'starlight']
    mine_skin_id: Literal['default']
    akari_skin_id: Literal['default']
    sudoku_skin_id: Literal['default']
