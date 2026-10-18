"""公共 HTTP 中间件：登录请求体上限与 API 安全响应头。"""

from fastapi.responses import JSONResponse


class LoginBodyLimit:
    """在 JSON 解析前按实际接收字节数限流，覆盖 chunked 和伪造 Content-Length。"""

    def __init__(self, app, max_body_bytes: int = 4096):
        """由应用装配注入体积上限，不依赖登录业务或应用全局对象。"""
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        original_send = send
        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
            await original_send(message)
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            send = secure_send
        if scope["type"] != "http" or not (scope["path"] == "/api/auth/login" or
                (scope["path"].startswith("/api/challenges/") and scope.get("method") == "POST")):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_body_bytes:
                return await JSONResponse(status_code=413, content={"detail": "请求体过大。"})(scope, receive, send)
            if not message.get("more_body", False):
                break
        consumed = False
        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        return await self.app(scope, replay, send)


