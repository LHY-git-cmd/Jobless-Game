"""容量观测工具的本地HTTP/SSE烟测，不将客户端观测误报为目标机容量通过。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from unittest import TestCase
from backend.probe_pk_capacity import probe


class ProbeTests(TestCase):
    """短流桩验证并存连接、查询统计和结束回收，不访问真实站点。"""

    def test_streams_and_regular_requests_are_bounded_and_report_no_secrets(self):
        """两条短流与普通GET并存，报告不包含私密Cookie或虚假容量结论。"""
        class Handler(BaseHTTPRequestHandler):
            """仅供本测试的有界响应。"""
            def do_GET(self):
                """事件流短暂保持，确保能观测到并存连接。"""
                self.send_response(200)
                if self.path.endswith('/events'):
                    self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                    self.wfile.write(b'event: resync\ndata: {}\n\n'); self.wfile.flush(); time.sleep(.3)
                else:
                    self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', '2'); self.end_headers()
                    self.wfile.write(b'{}')

            def log_message(self, *_):
                """不输出包含会话的请求信息。"""
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            value = probe(f'http://127.0.0.1:{server.server_port}', ['private-one', 'private-two'], 'test_session', .2)
            self.assertEqual(value['counts']['stream_peak'], 2)
            self.assertEqual(value['counts']['http_200'], 3)
            self.assertFalse(value['target_machine_capacity_accepted'])
            self.assertNotIn('private-one', str(value))
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=2)
