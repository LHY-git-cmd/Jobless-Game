"""挑战和排行榜 HTTP 路由；事务与数据库访问交给业务层。"""

from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from ..common.config import get_settings
from ..common.database import get_db
from ..models.schemas.ranking import Category, CompleteRequest, RestartRequest, StartRequest, ProgressResponse, RankingsResponse, PersonalRecordsResponse
from ..models.schemas.ranking import GrowthCategory, GrowthRankingsResponse
from ..common.exceptions import AppError
from ..services import ranking_service as service
from .auth_controller import enforce_same_origin

router = APIRouter(prefix="/api", tags=["rankings"])


def token(request):
    """凭据只从 HttpOnly Cookie 提取，用户归属由业务认证。"""
    return request.cookies.get(get_settings().session_cookie_name)


@router.get("/challenges/config")
async def configuration():
    """仅公开开发按钮开关，不公开其他环境配置。"""
    return {"quick_complete_enabled": get_settings().dev_quick_complete_enabled}


@router.post("/challenges/start", response_model=ProgressResponse)
async def start(payload: StartRequest, request: Request, db: Session = Depends(get_db)):
    """同源登录用户可以幂等地创建一轮。"""
    enforce_same_origin(request)
    return await service.execute(service.start_transaction, token(request), payload, db)


@router.get("/challenges/{run_id}", response_model=ProgressResponse)
async def progress(run_id: UUID, request: Request, db: Session = Depends(get_db)):
    """登录后读取本人当前轮次，供本地棋局恢复时核对。"""
    return await service.execute(service.progress_transaction, token(request), str(run_id), db)


@router.post("/challenges/{run_id}/restart", response_model=ProgressResponse)
async def restart(run_id: UUID, payload: RestartRequest, request: Request, db: Session = Depends(get_db)):
    """重开操作只重置指定关卡的尝试。"""
    enforce_same_origin(request)
    return await service.execute(service.restart_transaction, token(request), str(run_id), payload, db)


@router.post("/challenges/{run_id}/complete", response_model=ProgressResponse)
async def complete(run_id: UUID, payload: CompleteRequest, request: Request, db: Session = Depends(get_db)):
    """单次只接收一个游戏的结果，不接收客户端总成绩。"""
    enforce_same_origin(request)
    return await service.execute(service.complete_transaction, token(request), str(run_id), payload, db, get_settings())


@router.get("/rankings/{category}", response_model=RankingsResponse)
async def rankings(category: Category, page: int = Query(default=1, ge=1, le=100000),
                   page_size: int = Query(default=20, ge=1, le=50), db: Session = Depends(get_db)):
    """公共榜单按有限页大小读取，避免无限返回全部玩家。"""
    return await service.execute(service.rankings_transaction, category, page, page_size, db)


@router.get('/rankings/growth/{category}', response_model=GrowthRankingsResponse)
async def growth_rankings(category: GrowthCategory, page: int = Query(default=1, ge=1, le=100000),
                          page_size: int = Query(default=20, ge=1, le=50), db: Session = Depends(get_db)):
    """公开星数和等级榜；成长未开启时不访问尚未迁移的成长表。"""
    if not get_settings().progression_enabled:
        raise AppError(404, '成长排行榜暂未开放。')
    return await service.execute(service.growth_rankings_transaction, category, page, page_size, db)


@router.get("/records/me", response_model=PersonalRecordsResponse)
async def records(request: Request, category: Category = "mine", db: Session = Depends(get_db)):
    """个人记录只返回当前 Cookie 账号的数据。"""
    return await service.execute(service.records_transaction, token(request), category, db)
