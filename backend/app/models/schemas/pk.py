"""房间与匹配只允许一个照明普通池；不接收胜者或对手数据。"""
from typing import Literal
from pydantic import Field, StrictBool, StrictInt
from .progression import StrictDTO


class PoolCreate(StrictDTO):
    """首版仅照明普通难度，保持容量和匹配边界清晰。"""
    game_id: Literal['akari']
    difficulty: Literal['normal']


class MembershipCreate(StrictDTO):
    """房间码只是定位信息，仍需Cookie身份及资格。"""
    room_code: str = Field(min_length=6, max_length=6, pattern='^[A-Za-z2-9]{6}$')


class ReadinessPut(StrictDTO):
    """准备状态必须为真正布尔值。"""
    ready: StrictBool


class SubmissionPut(StrictDTO):
    """有界终盘布局，非法布局允许修正后再提交。"""
    bulbs: list[StrictInt] = Field(max_length=400)
