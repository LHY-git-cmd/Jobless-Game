# 作用：由 Nginx 提供游戏静态资源，只把 /api/ 转发给 API 容器。
FROM nginx:1.28-alpine
RUN sed -i 's/worker_processes  auto;/worker_processes  1;/' /etc/nginx/nginx.conf
COPY frontend /usr/share/nginx/html
COPY backend/deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY backend/deploy/docker/proxy.inc /etc/nginx/conf.d/proxy.inc
