"""公共异常和 HTTP 错误适配；业务层不依赖 FastAPI。"""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError


class AppError(Exception):
    """携带公开错误信息，由统一处理器映射到原有 API 错误格式。"""

    def __init__(self, status_code: int, detail: str | dict, headers: dict | None = None):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


class ExecutionBusyError(AppError):
    """任务尚未进入执行器时的拒绝，调用方可以安全释放预留资源。"""

    def __init__(self):
        super().__init__(503, "服务暂时繁忙，请稍后重试。", {"Retry-After": "3"})


async def application_error(request, exc: AppError):
    """保持接口 detail 结构与可重试响应头，不输出内部异常。"""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


async def validation_error(request, exc: RequestValidationError):
    """移除默认验证错误中的原始输入，避免回显密码。"""
    field = next((str(error["loc"][-1]) for error in exc.errors() if error.get("loc")), "form")
    message = "密码至少需要 6 个字符。" if field == "password" else "请检查输入内容。"
    return JSONResponse(status_code=422, content={"detail": {"field": field, "message": message}})


async def database_error(request, exc: SQLAlchemyError):
    """数据库异常统一脱敏，不改变原有 503 响应语义。"""
    return JSONResponse(status_code=503, content={"detail": "服务暂时繁忙，请稍后重试。"}, headers={"Retry-After": "3"})


def register_exception_handlers(app: FastAPI) -> None:
    """应用装配阶段注册公共错误处理，不由业务模块绑定应用实例。"""
    app.add_exception_handler(AppError, application_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(SQLAlchemyError, database_error)
