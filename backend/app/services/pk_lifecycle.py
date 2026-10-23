"""唯一PK生命周期调度任务；复用DB执行槽，不引入常驻新服务。"""
import asyncio
from contextlib import asynccontextmanager, suppress
import logging
from ..common.config import get_settings
from ..common.database import SessionLocal
from ..common.concurrency import bounded_db_call
from .pk_service import maintenance
from .pk_runtime import runtime

logger = logging.getLogger(__name__)


async def scheduler():
    """只推进有界活跃集合；异常日志不打印凭据/终盘/SQL。"""
    while True:
        await asyncio.sleep(.25)
        try:
            await bounded_db_call(maintenance, SessionLocal)
        except Exception:
            logger.warning('PK状态维护暂未完成，将重试。')
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app):
    """启动先作废旧房/等待票；停机释放唯一调度任务及事件连接。"""
    task = None
    if get_settings().pk_rooms_enabled:
        await bounded_db_call(lambda: maintenance(SessionLocal, restart=True))
        task = asyncio.create_task(scheduler(), name='bounded-pk-lifecycle')
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        runtime.reset()
