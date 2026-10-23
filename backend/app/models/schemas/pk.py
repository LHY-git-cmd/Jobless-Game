"""房间与匹配只允许一个照明普通池；不接收胜者或对手数据。"""
from typing import Literal
from pydantic import Field, StrictBool, StrictInt
from .progression import StrictDTO


class PoolCreate(StrictDTO):
    """首版仅照明普通难度，保持容量和匹配边界清晰。"""
    game_id: Literal['mine','akari','sudoku']
    difficulty: Literal['normal']


class MembershipCreate(StrictDTO):
    """房间码只是定位信息，仍需Cookie身份及资格。"""
    room_code: str = Field(min_length=6, max_length=6, pattern='^[A-Za-z2-9]{6}$')


class ReadinessPut(StrictDTO):
    """准备状态必须为真正布尔值。"""
    ready: StrictBool


class SubmissionPut(StrictDTO):
    """有界终盘布局，非法布局允许修正后再提交。"""
    bulbs: list[StrictInt]|None = Field(default=None,max_length=400)
    values: list[StrictInt]|None = Field(default=None,max_length=81)


class InvitationCreate(PoolCreate):
    """仅接收公开目标账号编号，不能代替对方接受。"""
    user_id:StrictInt=Field(gt=0,le=4294967295)


class PresencePut(StrictDTO):
    """只声明当前已认证页面是否可见，不接收他人在线状态。"""
    visible:StrictBool
