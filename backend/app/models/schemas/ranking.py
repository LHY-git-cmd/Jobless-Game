"""挑战写入 DTO；严格校验类别、整数、标识和开发标记，避免隐式转换。"""

from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

Game = Literal["mine", "akari", "sudoku"]
Category = Literal["mine", "akari", "sudoku", "total"]


class StartRequest(BaseModel):
    """创建轮次的幂等请求标识，不由客户端指定用户或通关状态。"""
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class RestartRequest(StartRequest):
    """重开已解锁关卡，版本阻止旧请求清空新进度。"""
    category: Game
    revision: int = Field(ge=0, strict=True)


class CompleteRequest(BaseModel):
    """仅接收当前关用时，总用时由服务端汇总。"""
    model_config = ConfigDict(extra="forbid")
    category: Game
    revision: int = Field(ge=0, strict=True)
    attempt_id: UUID
    duration_seconds: int = Field(ge=0, le=604800, strict=True)
    development: bool = Field(default=False, strict=True)


class LevelResponse(BaseModel):
    """本轮单关的公开尝试与保存状态。"""
    attempt_id: str
    seconds: int | None
    development: bool


class ProgressResponse(BaseModel):
    """写操作只返回有限的当前轮次，不泄露账号或会话字段。"""
    run_id: str
    revision: int
    levels: list[LevelResponse]
    total_recorded: bool


class RecordResponse(BaseModel):
    """个人通关快照，总榜带三个原轮次用时。"""
    id: int
    duration_seconds: int
    completed_at: datetime
    times: list[int] | None


class PersonalRecordsResponse(BaseModel):
    """最佳与最近记录可能引用相同 ID，不重复存储。"""
    category: Category
    best: RecordResponse | None
    recent: list[RecordResponse]


class RankingEntryResponse(BaseModel):
    """公开榜单行只包含用户名、名次和用时等展示字段。"""
    rank: int
    user_id: int
    username: str
    avatar_id: int = 1
    duration_seconds: int
    achieved_at: datetime
    times: list[int] | None


class RankingsResponse(BaseModel):
    """有限分页的榜单响应。"""
    category: Category
    page: int
    page_size: int
    total: int
    entries: list[RankingEntryResponse]
