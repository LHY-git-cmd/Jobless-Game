# 作用：构建低资源单进程 API 镜像；不复制本机 .env、数据库或开发工具。
FROM python:3.11.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && useradd --uid 10001 --create-home app
COPY --chown=10001:10001 backend/app /app/backend/app
COPY --chown=10001:10001 backend/content /app/backend/content
COPY --chown=10001:10001 backend/cleanup_sessions.py /app/backend/cleanup_sessions.py
COPY --chown=10001:10001 backend/cleanup_game_history.py /app/backend/cleanup_game_history.py
# 当前应用入口同时挂载前端目录，保留目录以兼容；对外静态请求由 Nginx 提供。
COPY --chown=10001:10001 frontend /app/frontend
USER 10001:10001
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1", "--limit-concurrency", "32", "--backlog", "32", "--timeout-keep-alive", "5", "--proxy-headers", "--forwarded-allow-ips", "172.30.28.10"]
