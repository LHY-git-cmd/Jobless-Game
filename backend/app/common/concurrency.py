"""公共有界同步执行器，防止阻塞事件循环或累积无界等待任务。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from .exceptions import ExecutionBusyError

db_slots = BoundedSemaphore(4)
db_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="auth-db")


async def bounded_db_call(function, *args):
    """过载立即拒绝，取消时仍等待工作线程结束后再清理数据库依赖。"""
    if not db_slots.acquire(blocking=False):
        raise ExecutionBusyError()

    def execute():
        """工作线程结束后释放执行槽，不受客户端取消影响。"""
        try:
            return function(*args)
        finally:
            db_slots.release()

    try:
        future = asyncio.get_running_loop().run_in_executor(db_executor, execute)
    except RuntimeError:
        db_slots.release()
        raise ExecutionBusyError()
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        # 数据库会话不能在线程仍使用它时由请求依赖关闭。
        await asyncio.shield(future)
        raise
