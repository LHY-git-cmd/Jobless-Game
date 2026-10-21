"""v1 REST资源路由：HTTP条件、同源保护、严格DTO和有界同步事务。"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..common.config import get_settings
from ..common.database import get_db
from ..common.concurrency import bounded_db_call
from ..common.game_catalog import LEVELS, metadata
from ..common.security import utc_now
from ..models.schemas.progression import AttemptCreate, AttemptPatch, CompletionPut, AppearancePut, EmptyDTO
from ..services import progression_service as service
from .auth_controller import enforce_same_origin

router = APIRouter(prefix='/api/v1', tags=['progression'])


def enabled(feature='progression_enabled'):
    """独立开关默认关闭，未迁移数据库时也能安全返回状态。"""
    if not getattr(get_settings(), feature):
        service.fail(404, 'feature_disabled', '此功能暂未开放。')


def response(resource):
    """保留创建Location、强ETag和成功状态。"""
    return JSONResponse(resource.data, status_code=resource.status, headers=resource.headers)


async def run(request, db, action, **kwargs):
    """时间取自HTTP入口；鉴权和数据库访问均不阻塞事件循环。"""
    enabled()
    if action.startswith('appearance') or action == 'cosmetics':
        enabled('cosmetics_enabled')
    if request.method not in ('GET', 'HEAD'):
        enforce_same_origin(request)
    return response(await bounded_db_call(lambda: service.dispatch(
        request.cookies.get(get_settings().session_cookie_name), db, action, **kwargs)))


@router.get('/features')
async def features():
    """只公开产品能力，不暴露数据库等部署配置。"""
    settings = get_settings()
    return {key: getattr(settings, key + '_enabled') for key in ('progression', 'cosmetics', 'pk_rooms', 'matchmaking')}


@router.get('/games')
async def games():
    """有限的公共游戏目录。"""
    enabled()
    return {'items': [{'game_id': key, 'name': name} for key, name in (('mine', '扫雷'), ('akari', '照明'), ('sudoku', '数独'))]}


@router.get('/levels')
async def levels(game_id: str | None = Query(None, max_length=16)):
    """公开元数据，不创建计时凭据或发放题目。"""
    enabled()
    return {'items': [metadata(level) for level in LEVELS.values() if not game_id or level['game_id'] == game_id]}


@router.get('/levels/{level_id}')
async def level(level_id: str):
    """单关只读元数据。"""
    enabled()
    if level_id not in LEVELS:
        service.fail(404, 'level_not_found', '关卡不存在。')
    return metadata(LEVELS[level_id])


@router.get('/me/progression')
async def progression(request: Request, db: Session = Depends(get_db)):
    """本人统一账号进度，无客户端写入口。"""
    return await run(request, db, 'progression')


@router.get('/me/level-progress')
async def progress(request: Request, game_id: str | None = Query(None, max_length=16), cursor: str | None = Query(None, max_length=40),
                   limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
    """以稳定关卡ID游标读取有限进度。"""
    return await run(request, db, 'level_progress', game_id=game_id, cursor=cursor, limit=limit)


@router.get('/me/pk-eligibility')
async def eligibility(request: Request, db: Session = Depends(get_db)):
    """未解锁也返回正常资格资源表示。"""
    return await run(request, db, 'eligibility')


@router.post('/attempts', status_code=201)
async def create(payload: AttemptCreate, request: Request, db: Session = Depends(get_db)):
    """开始正式计时；创建重试必须重用原Idempotency-Key。"""
    return await run(request, db, 'attempt_create', data=payload.model_dump(), key=request.headers.get('Idempotency-Key'))


@router.get('/attempts/{attempt_id}')
async def attempt(attempt_id: str, request: Request, db: Session = Depends(get_db)):
    """账号核验通过后恢复权威尝试。"""
    return await run(request, db, 'attempt_get', rid=attempt_id)


@router.patch('/attempts/{attempt_id}')
async def abandon(attempt_id: str, payload: AttemptPatch, request: Request, db: Session = Depends(get_db)):
    """条件放弃，仅允许active进入abandoned。"""
    return await run(request, db, 'attempt_abandon', rid=attempt_id, match=request.headers.get('If-Match'))


@router.put('/attempts/{attempt_id}/reveals/{cell_index}', status_code=201)
async def reveal(attempt_id: str, cell_index: int, payload: EmptyDTO, request: Request, db: Session = Depends(get_db)):
    """扫雷逐格动作，只接受空体，索引重放幂等。"""
    return await run(request, db, 'reveal', rid=attempt_id, index=cell_index)


@router.put('/attempts/{attempt_id}/completion', status_code=201)
async def complete(attempt_id: str, payload: CompletionPut, request: Request, db: Session = Depends(get_db)):
    """终盘不可变单例，不接收客户端用时或奖励。"""
    return await run(request, db, 'completion_put', rid=attempt_id, data=payload.model_dump(exclude_unset=True),
                     received_at=getattr(request.state, 'received_at', utc_now()))


@router.get('/attempts/{attempt_id}/completion')
async def completion(attempt_id: str, request: Request, db: Session = Depends(get_db)):
    """响应丢失后的恢复入口。"""
    return await run(request, db, 'completion_get', rid=attempt_id)


@router.get('/cosmetics')
async def catalog():
    """主题元数据与版本化样式地址。"""
    enabled('cosmetics_enabled')
    return {'items': [{**item, 'asset_url': '/journey.css?v=1'} for item in service.COSMETICS]}


@router.get('/me/cosmetics')
async def cosmetics(request: Request, db: Session = Depends(get_db)):
    """本人永久外观权益。"""
    return await run(request, db, 'cosmetics')


@router.get('/me/appearance')
async def appearance(request: Request, db: Session = Depends(get_db)):
    """当前装配及强ETag。"""
    return await run(request, db, 'appearance_get')


@router.put('/me/appearance')
async def equip(payload: AppearancePut, request: Request, db: Session = Depends(get_db)):
    """完整配置替换必须满足所有权和If-Match。"""
    return await run(request, db, 'appearance_put', data=payload.model_dump(), match=request.headers.get('If-Match'))
