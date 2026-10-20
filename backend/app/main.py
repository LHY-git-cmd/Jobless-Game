"""应用装配入口：注册路由、公共异常、中间件及本地静态页面。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .common.config import get_settings
from .common.exceptions import register_exception_handlers
from .common.middleware import LoginBodyLimit
from .controllers.auth_controller import router as auth_router
from .controllers.avatar_controller import router as avatar_router
from .controllers.ranking_controller import router as ranking_router
from .controllers.forum_controller import router as forum_router

app = FastAPI(title="无职游戏 API", docs_url=None, redoc_url=None)
register_exception_handlers(app)
app.add_middleware(LoginBodyLimit, max_body_bytes=get_settings().max_request_body_bytes)
app.include_router(auth_router)
app.include_router(avatar_router)
app.include_router(ranking_router)
app.include_router(forum_router)

# API 必须先注册，根路径静态挂载继续兼容本地同源预览与现有启动命令。
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend", html=True), name="frontend")
