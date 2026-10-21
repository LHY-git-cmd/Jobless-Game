"""SSE资源界限和鉴权连接释放验证；心跳不访问数据库。"""
import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch
from starlette.requests import Request
from backend.app.services.pk_runtime import PKRuntime
from backend.app.common.exceptions import AppError
from backend.app.common.config import get_settings
from backend.app.controllers import pk_controller


class EventTests(IsolatedAsyncioTestCase):
    """不启动无限流，直接检查有界订阅与生成器清理。"""

    async def test_capacity_one_account_slow_client_and_revoke(self):
        """账号单连接、全局上限和慢客户端关闭，队列不会无限增长。"""
        hub = PKRuntime()
        one = hub.subscribe(1, 'test-token', 2)
        with self.assertRaises(AppError):
            hub.subscribe(1, 'test-token', 2)
        two = hub.subscribe(2, 'test-token-2', 2)
        with self.assertRaises(AppError):
            hub.subscribe(3, 'test-token-3', 2)
        for revision in range(20):
            hub.publish(1, '/api/v1/rooms/test', revision)
        await asyncio.sleep(0)
        self.assertEqual(one.queue.qsize(), 16)
        self.assertTrue(one.closed)
        hub.unsubscribe(one)
        hub.revoke('test-token-2')
        self.assertFalse(hub.online(2))
        hub.unsubscribe(two)
        self.assertEqual(len(hub.streams), 0)

    async def test_session_closed_before_stream_starts(self):
        """StreamingResponse创建前主动归还Session，流生成器只持订阅。"""
        db = Mock()
        user = Mock(id=1)
        request = Request({'type': 'http', 'method': 'GET', 'path': '/api/v1/me/events',
                           'headers': [(b'cookie', (get_settings().session_cookie_name + '=test-token').encode())]})
        with patch.object(pk_controller, 'enabled'), patch.object(pk_controller.auth_service, 'get_current_user', return_value=user), patch.object(pk_controller, 'runtime', PKRuntime()) as hub:
            response = await pk_controller.events(request, db)
            db.close.assert_called_once()
            self.assertEqual(response.media_type, 'text/event-stream')
            first = await response.body_iterator.__anext__()
            self.assertIn('resync', first)
            await response.body_iterator.aclose()
            self.assertEqual(len(hub.streams), 0)
