"""公共 HTTP 中间件：论坛独立32KiB、既有写接口4KiB和 API 安全响应头。"""

from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


class RevalidatingStaticFiles(StaticFiles):
    """本地静态服务与 Nginx 对齐：代码验证更新，素材缓存七天。"""

    async def get_response(self, path, scope):
        """保留 StaticFiles 的 ETag/304 行为，仅补充静态资源缓存策略。"""
        response = await super().get_response(path, scope)
        if scope["path"].startswith("/api/"):
            return response
        if path.replace("\\", "/").startswith("assets/"):
            # 七天与生产素材缓存一致；版本化头像路径继续保持原样。
            response.headers["Cache-Control"] = "public, max-age=604800"
        elif path in ("", ".") or path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache"
        return response


class LoginBodyLimit:
    """在 JSON 解析前按实际接收字节数限流，覆盖 chunked 和伪造 Content-Length。"""

    def __init__(self, app, max_body_bytes: int = 4096):
        """由应用装配注入体积上限，不依赖登录业务或应用全局对象。"""
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        """先接收至有界缓冲，再交给 JSON 解析；分块请求也不能绕过上限。"""
        original_send = send
        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
            await original_send(message)
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            send = secure_send
        forum_write = scope["type"] == "http" and scope["path"].startswith("/api/forum/") and scope.get("method") in ("POST", "PUT", "DELETE")
        if scope["type"] != "http" or not (forum_write or scope["path"] == "/api/auth/login" or
                (scope["path"] == "/api/auth/avatar" and scope.get("method") == "PUT") or
                (scope["path"].startswith("/api/challenges/") and scope.get("method") == "POST")):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            # 拒绝前不复制超大分块，使中间件自身缓冲始终受所选上限约束。
            if len(body) + len(chunk) > (32768 if forum_write else self.max_body_bytes):
                return await JSONResponse(status_code=413, content={"detail": "请求体过大。"})(scope, receive, send)
            body.extend(chunk)
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


