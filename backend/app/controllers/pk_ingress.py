"""PK提交ASGI入口：在请求体解析及DB槽位前登记接收时间，所有退出路径释放。"""
from starlette.requests import Request
from ..common.exceptions import AppError, application_error
from ..common.security import utc_now
from ..services.pk_runtime import runtime


class PKSubmissionIngress:
    """仅追踪PUT对局终盘，最多32个待处理请求。"""

    def __init__(self, app):
        """作为最外层中间件装配，不需要额外线程或数据库。"""
        self.app = app

    async def __call__(self, scope, receive, send):
        """finally覆盖超大请求、DTO失败、断连及正常返回。"""
        parts = scope.get('path', '').strip('/').split('/')
        tracked = scope['type'] == 'http' and scope.get('method') == 'PUT' and len(parts) == 6 and parts[:3] == ['api', 'v1', 'rooms'] and parts[4:] == ['submissions', 'me']
        if not tracked:
            return await self.app(scope, receive, send)
        received_at = utc_now()
        scope.setdefault('state', {})['received_at'] = received_at
        try:
            key = runtime.receive(parts[3], received_at)
        except AppError as exc:
            return await (await application_error(Request(scope), exc))(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            runtime.processed(key)
