# 本机 Docker 部署与验证

本方案用于当前电脑验证：Nginx 提供网页，单进程 FastAPI 处理 API，MySQL 8.4 使用独立命名卷保存数据。Flyway 完成 V1～V4 后退出，迁移失败时 API 不启动。不读取或修改已有 `backend/.env` 和宝塔数据库。V3 为用户头像编号，V4 新增文字论坛和站内消息五张表。论坛 `/api/forum/` 独立32KiB，其他 API 仍4KiB；修改模板后需重建 Web 镜像。下文历史验收仅覆盖当时 V1/V2；本次 V4 的真实 MySQL/Flyway 与 Nginx 运行验收待完成，见 [论坛实施报告](../../../docs/forum-implementation-report.md)。

## 启动

需要运行中的 Docker Engine / Docker Desktop（Linux 容器）及 Docker Compose v2 或更新版本。以下命令均在项目根目录执行。

1. 复制 `.env.docker.example` 为 `.env.docker`，填写两个不同的随机十六进制密码，每个至少 32 位。密码只保存在本机，被 Git 忽略；留空时 Compose 拒绝启动。不要将包含凭据的 `docker compose config` 完整输出贴到日志或聊天。
2. 启动：

```text
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d --build --wait --wait-timeout 180
docker compose --env-file .env.docker ps -a
```

打开 http://127.0.0.1:8080/。首次下载镜像与安装依赖需要联网；8080 被占用时修改 `.env.docker` 的 `WEB_PORT`。该地址只允许本机访问，MySQL 和 API 不映射宿主机端口。所有游戏测试账号只存在本地卷中，不应导入正式环境。

Compose 项目名称为 `jobless-game-local`，数据库名为 `jobless_game_local`，数据卷为 `jobless-game-local_mysql_data`。Nginx 使用 `172.30.28.10`，API 只信任这个代理地址；网段冲突时须同步修改 Compose 网段、Web 地址与 API Dockerfile 的 `--forwarded-allow-ips`，再重建镜像。

开发一键通关在容器中强制关闭，HTTP 验证使用 `COOKIE_SECURE=false`。登录同时只允许一个密码处理流程，忙时返回 429；同一出口每分钟 5 次登录的保护仍有效。

## 验证与数据持久化

在开发机运行以下脚本，验证 HTML、音频分段读取/缓存、同源限制、登录 Cookie、任意顺序独立通关、幂等和三个单项榜，并确认总榜接口停用。脚本会创建一个随机本地验收账号，使用临时 Cookie 文件；不输出凭据。

```text
python backend/deploy/docker/verify_docker.py
docker compose --env-file .env.docker down
docker compose --env-file .env.docker up -d --wait --wait-timeout 180
python backend/deploy/docker/verify_docker.py --phase persisted
```

`down` 保留数据卷，重建后的验证复用原会话检查成绩仍然存在。验收状态保存在被 Git 忽略的 `artifacts/docker/`；本脚本只允许回环地址。若修改端口，运行脚本时增加 `--base-url http://127.0.0.1:新端口`。

查看状态、资源与迁移：

```text
docker compose --env-file .env.docker ps -a
docker stats --no-stream
docker compose --env-file .env.docker run --rm migrate info
```

`migrate` 容器显示 `Exited (0)` 属正常现象，不应配置为常驻重启。日志每个容器最多 2 个文件、每个 5MiB。会话清理可通过宿主机现有计划任务单次执行，不增加常驻进程：

```text
docker compose --env-file .env.docker exec -T api python -m backend.cleanup_sessions --batch-size 500 --max-batches 10
```

## 停止、更新与资源边界

停止运行但保留容器和数据：

```text
docker compose --env-file .env.docker stop
```

更新本地代码后重新执行 `up -d --build --wait`。存在新迁移时先停止 API/Web 再迁移，避免应用运行期间变更结构及叠加内存峰值：

```text
docker compose --env-file .env.docker stop api web
docker compose --env-file .env.docker run --rm migrate migrate
docker compose --env-file .env.docker up -d --build --wait --wait-timeout 180
```

保留并备份 `.env.docker`；修改此文件中的数据库密码不会自动修改已有数据卷内的账号密码。不要添加 `down -v`，该参数会删除本地数据卷。

| 容器 | 内存硬上限 | CPU 上限 | 常驻 |
| --- | --- | --- | --- |
| MySQL | 640MiB（其中 InnoDB 缓存 256MiB） | 1 核 | 是 |
| API | 320MiB | 1 核 | 是 |
| Nginx | 64MiB，1 个 worker | 0.25 核 | 是 |
| Flyway | 512MiB，JVM 最大堆 192MiB | 0.75 核 | 否 |

常驻容器上限合计 1024MiB；这些是限制值，不是实际占用。Docker 引擎、系统、宝塔和迁移峰值须另算，限制过低可能导致 OOM，需要按实测调整。CPU 限制是各容器的独立上限，不代表已预留对应核心。

本机验收不能替代目标 2 核/2GB Linux 服务器验收。服务器部署时优先复用宝塔已有 Nginx/MySQL，避免重复常驻服务；还需核对域名、HTTPS、Secure Cookie、代理链路和数据库备份。当前 Compose 的 HTTP 配置不应直接作为公网 HTTPS 配置使用。

## 本次实际验证（2026-10-18）

- 本机 Docker Desktop 的 Linux 容器完成构建与启动，MySQL、API、Nginx 均为健康状态；Flyway 成功执行 V1/V2 后退出。
- 首轮真实 HTTP 验证 49 项通过、0 失败，包含真实 Argon2id 登录、MySQL 保存、逐关顺序、重复提交、个人记录、四榜与音频缓存/分段读取。
- 执行 `down` 保留卷，再 `up` 重建所有容器后，原 Cookie 与四类成绩持久化验证 24 项通过、0 失败。第二次 Flyway 检查数据库已处于 V2，没有重复建表。
- 验证后的常驻容器内存快照约 330MiB（MySQL 约 261MiB、API 约 63MiB、Nginx 约 5MiB）。该快照不是峰值或 10 人压测结果，不包括 Docker Desktop 虚拟机、Docker 引擎与宿主系统。
- `docker compose config --quiet` 与容器内 `nginx -t` 均通过；Nginx 实际使用 1 个 worker。真实 `.env.docker`、测试 Cookie 和日志确认被 Git 忽略。
- 日志保存在 `artifacts/docker/deploy.log`、`http-initial.log`、`recreate.log` 与 `http-persisted.log`，不提交。验收后保持本机服务运行。
- 本次覆盖真实 MySQL/Flyway 的容器 HTTP 链路与持久化，不等同于既有四项专用数据库单元/并发联调，也未进行目标服务器部署、容量压测或迁移峰值测量。

Compose 服务依赖与内存限制参考 [Docker 官方说明](https://docs.docker.com/reference/compose-file/services/)，迁移镜像用法参考 [Flyway 官方说明](https://documentation.red-gate.com/fd/flyway-docker-321585710.html)。

## 前端模块与缓存更新

HTML、`/src/` 下 JavaScript 和根目录样式使用 `Cache-Control: no-cache`，浏览器复用前验证 ETag/Last-Modified，未修改时可返回 304；`/assets/` 保留七天缓存，API 继续 no-store。本地 FastAPI 采用同一策略。代码和样式不再手工维护 `?v=`。

更新时成套替换网页与全部模块，在既有维护窗口完成，避免新旧文件混用；宝塔站点须合并最新 Nginx 模板并通过 `nginx -t` 后重载。核验首页、论坛、`/src/main.js`、`/styles.css` 的实际响应头及条件请求，不能仅凭模板宣称生效。旧强缓存可能要到期或一次性清理后才会取得新策略，已打开页面需重新加载。回退时恢复同一版本整套前端及对应配置，保留玩家存档。
