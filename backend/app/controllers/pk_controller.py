"""双人房间/匹配REST资源及独立SSE流：全部写操作走HTTP。"""
import asyncio
import json
from time import monotonic
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse
from ..common.config import get_settings
from ..common.database import get_db
from ..common.concurrency import bounded_db_call
from ..common.security import utc_now
from ..models.schemas.pk import PoolCreate, MembershipCreate, ReadinessPut, SubmissionPut
from ..services import pk_service as service, auth_service
from ..services.pk_runtime import runtime
from .progression_controller import enabled, response
from .auth_controller import enforce_same_origin

router = APIRouter(prefix='/api/v1', tags=['pk'])


class EventResponse(StreamingResponse):
    """即使慢客户端阻塞发送也在65秒内取消流并释放全局订阅槽。"""

    def __init__(self, request, sub):
        """响应只持有有限订阅，不保留数据库对象。"""
        self.subscription = sub
        super().__init__(event_stream(request, sub), media_type='text/event-stream',
                         headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-store'})

    async def __call__(self, scope, receive, send):
        """覆盖尚未启动生成器就断连及发送背压的清理路径。"""
        try:
            async with asyncio.timeout(65):
                await super().__call__(scope, receive, send)
        except TimeoutError:
            pass
        finally:
            runtime.unsubscribe(self.subscription)


async def run(request, db, action, **kwargs):
    """同步业务受现有4槽执行器保护，流式连接不进入此函数。"""
    enabled()
    enabled('pk_rooms_enabled')
    if action.startswith('ticket') or action == 'my_ticket':
        enabled('matchmaking_enabled')
    if request.method not in ('GET', 'HEAD'):
        enforce_same_origin(request)
    return response(await bounded_db_call(lambda: service.dispatch(
        request.cookies.get(get_settings().session_cookie_name), db, action, **kwargs)))


@router.post('/rooms', status_code=201)
async def create(payload: PoolCreate, request: Request, db=Depends(get_db)):
    """创建娱乐双人房间。"""
    return await run(request, db, 'room_create', data=payload.model_dump(), key=request.headers.get('Idempotency-Key'))


@router.post('/room-memberships', status_code=201)
async def join(payload: MembershipCreate, request: Request, db=Depends(get_db)):
    """房间码加入当前账号的成员关系。"""
    return await run(request, db, 'room_join', data=payload.model_dump(), key=request.headers.get('Idempotency-Key'))


@router.get('/rooms/{room_id}')
@router.get('/rooms/{room_id}/members/me')
async def room(room_id: str, request: Request, db=Depends(get_db)):
    """权威房间或本人成员关系快照。"""
    return await run(request, db, 'room_get', rid=room_id)


@router.delete('/rooms/{room_id}/members/me', status_code=204)
async def leave(room_id: str, request: Request, db=Depends(get_db)):
    """移除当前成员；比赛中执行退出判负。"""
    return await run(request, db, 'room_leave', rid=room_id)


@router.put('/rooms/{room_id}/members/me/readiness')
async def ready(room_id: str, payload: ReadinessPut, request: Request, db=Depends(get_db)):
    """准备状态用房间ETag防止旧页面覆盖。"""
    return await run(request, db, 'room_ready', rid=room_id, data=payload.model_dump(), match=request.headers.get('If-Match'))


@router.get('/rooms/{room_id}/members/me/readiness')
async def current_readiness(room_id: str, request: Request, db=Depends(get_db)):
    """新建准备状态的Location可直接读取当前权威表示。"""
    return await run(request, db, 'room_get', rid=room_id)


@router.put('/rooms/{room_id}/submissions/me', status_code=201)
async def submit(room_id: str, payload: SubmissionPut, request: Request, db=Depends(get_db)):
    """入口待处理登记由ASGI中间件管理，包含DTO验证和DB排队时间。"""
    return await run(request, db, 'room_submit', rid=room_id, data=payload.model_dump(),
                     received_at=getattr(request.state, 'received_at', utc_now()))


@router.get('/rooms/{room_id}/result')
async def result(room_id: str, request: Request, db=Depends(get_db)):
    """读取已经提交的不可变比赛结果。"""
    return await run(request, db, 'room_result', rid=room_id)


@router.get('/me/rooms')
async def my_rooms(request: Request, status: str = Query('active', pattern='^active$'), db=Depends(get_db)):
    """恢复当前唯一房间。"""
    return await run(request, db, 'my_rooms')


@router.post('/matchmaking-tickets', status_code=201)
async def match(payload: PoolCreate, request: Request, db=Depends(get_db)):
    """有界FIFO匹配，成功时直接返回已配对房间链接。"""
    return await run(request, db, 'ticket_create', data=payload.model_dump(), key=request.headers.get('Idempotency-Key'))


@router.get('/matchmaking-tickets/{ticket_id}')
async def ticket(ticket_id: str, request: Request, db=Depends(get_db)):
    """本人票据的权威终态可恢复。"""
    return await run(request, db, 'ticket_get', rid=ticket_id)


@router.delete('/matchmaking-tickets/{ticket_id}', status_code=204)
async def cancel(ticket_id: str, request: Request, db=Depends(get_db)):
    """重复取消等待票204；已配对票409引导退出房间。"""
    return await run(request, db, 'ticket_cancel', rid=ticket_id)


@router.get('/me/matchmaking-ticket')
async def current_ticket(request: Request, db=Depends(get_db)):
    """跨刷新恢复当前等待票。"""
    return await run(request, db, 'my_ticket')


async def event_stream(request, sub):
    """最多60秒的只读流；15秒心跳无DB查询，重连强制GET快照。"""
    deadline = monotonic() + 60
    try:
        yield 'event: resync\ndata: {}\n\n'
        while monotonic() < deadline and not sub.closed:
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(sub.queue.get(), timeout=min(15, max(.01, deadline-monotonic())))
            except asyncio.TimeoutError:
                yield ': heartbeat\n\n'
                continue
            if not sub.closed:
                yield f"id: {item['id']}\nevent: resource-updated\ndata: {json.dumps(item, separators=(',', ':'))}\n\n"
    finally:
        runtime.unsubscribe(sub)


@router.get('/me/events')
async def events(request: Request, db=Depends(get_db)):
    """短鉴权后显式close Session，流的生成器没有数据库依赖。"""
    enabled()
    enabled('pk_rooms_enabled')
    token = request.cookies.get(get_settings().session_cookie_name)
    try:
        user = await auth_service.get_current_user(token, db)
        uid = user.id
    finally:
        # FastAPI的yield依赖在不同版本可能直到流结束才清理，此处主动归还连接。
        db.close()
    sub = runtime.subscribe(uid, token, get_settings().pk_sse_limit)
    return EventResponse(request, sub)
