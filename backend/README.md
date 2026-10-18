# 登录后端运行与部署

采用 FastAPI、SQLAlchemy/PyMySQL 和 Argon2id。数据库结构只由 Flyway 管理，应用启动不自动建表。游戏仍在浏览器中运行，排行榜和论坛继续为占位页面。

## 五层架构

请求调用方向为 `Controller → Service → Repository → MySQL`；模型层提供数据结构，公共层提供跨业务基础能力。`app/main.py` 只装配应用、路由、异常、中间件和本地静态页面。

| 层 | 目录 | 职责与边界 |
| --- | --- | --- |
| 控制层 | `app/controllers/` | 使用 APIRouter，负责同源检查、提取 Cookie、调用业务和映射响应；不执行 SQL |
| 业务层 | `app/services/` | 登录/注册/会话流程、账号规则、登录限流和计算槽；管理 commit、rollback、flush，不接收 Request/Response |
| 数据访问层 | `app/repositories/` | 相当于 Mapper/DAO，封装用户、会话查询及写入；不提交事务、不操作 HTTP |
| 模型层 | `app/models/entities/`、`app/models/schemas/` | 前者为数据库实体，后者为请求 DTO 和响应模型；接口不直接输出包含密码摘要的实体 |
| 公共层 | `app/common/` | 配置、连接池、密码/凭据工具、公共异常、HTTP 中间件和有界执行器；不反向调用登录业务 |

关键设计：使用 APIRouter 保持现有接口路径；业务抛 `AppError`，统一处理器保持原 `detail` 响应结构；事务提交集中在 Service，Repository 操作属于调用方同一个数据库会话。采用函数模块即可，不额外引入通用 BaseService/BaseMapper 或运行服务。

新增业务应建立对应 controller、service、repository 和模型，跨业务复用能力才进入 `common/`。用户名校验和登录限流属于登录业务，保留在 `services/`。过期会话清理脚本调用会话 Repository；Flyway 迁移、HTTP 接口、`.env` 位置和原启动命令保持兼容。

## 本地启动

在项目根目录创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements-test.txt
Copy-Item backend/.env.example backend/.env
```

在 `backend/.env` 配置 `DATABASE_URL`；配置文件固定从 `backend/.env` 读取，环境变量优先。应使用项目专用数据库账号；URL 密码中的 `@`、`:`、`/` 等字符需要 URL 编码。数据库由管理员预先创建为 `utf8mb4`。不要提交真实 `.env` 或 Flyway 配置。

先执行下节迁移，再在项目根目录启动：

```powershell
.venv/Scripts/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --workers 1 --limit-concurrency 32 --backlog 32 --timeout-keep-alive 5
```

打开 `http://127.0.0.1:8001/`。本地由 FastAPI 同时提供页面和 `/api/`；原有静态服务器只能预览页面，真实登录需连接后端。HTTPS 正式环境配置 `COOKIE_SECURE=true`，本地 HTTP 使用 `false`。

## Flyway

安装支持 MySQL 的 Flyway CLI 与相应 JDBC 驱动，按所用版本官方说明配置。项目不自动下载或常驻运行 Flyway。

复制 `backend/flyway.conf.example` 为被 Git 忽略的 `backend/flyway.conf`，在项目根目录执行：

```text
flyway -configFiles=backend/flyway.conf info
flyway -configFiles=backend/flyway.conf migrate
flyway -configFiles=backend/flyway.conf migrate
flyway -configFiles=backend/flyway.conf info
```

确认目标库名、备份和维护窗口。首次应执行 `V1__create_auth_tables.sql`，第二次不应有待执行迁移。配置禁止 `clean` 和自动 baseline；禁止直接修改已执行 SQL，后续变更新增 `V2__...sql`。

2 核/2GB 与宝塔共存时先检查 `MemAvailable` 和现有服务占用；必要时停止本项目 Python，再单次执行迁移，完成后退出并启动 Python。`JAVA_ARGS=-Xms32m -Xmx256m` 仅为评估起点，不能视为 Flyway 全进程内存上限。

## API 与边界

| 接口 | 成功行为 | 主要失败 |
| --- | --- | --- |
| `POST /api/auth/login` | 首次自动注册或验证已有密码；返回 `{user:{id,username},created}` 并设置 Cookie | 401 密码错误、403 来源错误、413 请求体过大、422 输入错误、429 频率/哈希繁忙、503 数据库/执行槽繁忙 |
| `GET /api/auth/me` | 返回 `{id,username}` | 401 会话无效、503 数据库/执行槽繁忙 |
| `POST /api/auth/logout` | 当前会话失效并清除 Cookie，返回 204 | 403 来源错误、503 暂时不可用 |

状态修改接口要求同源 `Origin` 或 `Referer`，命令行客户端也须提供正确 `Origin`。服务不开放跨源 CORS。API 响应为 `no-store`，错误不回显密码、密码摘要或数据库内部消息。

用户名按 Unicode 字符计数：ASCII 字母/数字计 2，汉字计 3，上限 24。前后端固定采用 Unicode 15.1 已分配汉字范围，包含常见、兼容及补充平面汉字，排除未分配码位；更新范围时须同步两端。仅折叠 ASCII 大小写，数据库 `utf8mb4_bin` 唯一键保留其他字符差异。密码至少六个 Unicode 字符，原样保留空格与大小写；总请求体仍受 4KiB 限制。

会话为 32 随机字节生成的 URL 安全 token；Cookie 使用 HttpOnly、SameSite=Lax（可改 strict）、Path=/，HTTPS 开启 Secure。数据库只保存 SHA-256 摘要与 UTC 到期时间，默认七天。密码使用显式 Argon2id `memory_cost=65536 KiB, time_cost=3, parallelism=1`，校验、创建和重哈希共用一个计算槽，忙时立即返回 429。

同步数据库流程最多四个执行槽、四个工作线程，无等待任务队列。数据库池默认 `3+0`、等待三秒，连接超时三秒、读写各五秒。工作线程完成前不会因客户端取消而提前释放槽或关闭正在使用的会话。应用按客户端地址限流，默认每 60 秒五次，最多保留 2048 个限流键。该保护用于计划中的单进程；大量不同地址可淘汰旧键，生产必须保留 Nginx 边界限流，不能绕过代理公开 API 端口或随意扩多进程。

## 宝塔与 Nginx

1. 复用现有 Nginx/MySQL，站点根目录指向 `frontend/`，后端和配置不得放入 Web 根目录。准备虚拟环境、`backend/.env` 并完成迁移。
2. 将 `deploy/nginx-http.conf.example` 的速率区加到 **http 级别**；将 `nginx-site.conf.example` 合并到项目域名现有的 HTTPS server，保留宝塔证书配置并替换路径。代理模板复制为 `backend/deploy/nginx-proxy.conf`。先备份配置，执行 `nginx -t`，通过后再重载。
3. 宝塔进程管理器或 `deploy/jobless-auth.service.example` 二选一。核对用户、目录与虚拟环境路径；一个 Uvicorn worker，绑定 `127.0.0.1:8001`，并发保护 32、backlog 32，仅信任本机代理头。公网防火墙不开放 8001。
4. 项目连接池保持有界；共享 MySQL 不改全局连接上限或覆盖其他业务配置。256MiB InnoDB 缓存只作评估起点，不是 MySQL 全进程内存上限。
5. 优先使用宝塔已有日志轮转；或采用 `deploy/logrotate.conf.example`。systemd 标准输出由 journald 管理，按实际磁盘预算设置上限，不叠加重复轮转。

过期会话清理由现有计划任务定期运行（例如每小时）：

```text
cd /www/wwwroot/jobless-game
.venv/bin/python -m backend.cleanup_sessions --batch-size 500 --max-batches 10
```

每批独立事务，利用到期时间索引，每次最多十批，完成退出。若持续积压，先核实频率及负载再调整。

## 测试

在项目根目录执行，完整输出写入日志：

```powershell
New-Item -ItemType Directory -Force artifacts/backend | Out-Null
python -m unittest discover -s backend/tests -v *> artifacts/backend/auth-tests.log
cd frontend
npm test *> ../artifacts/frontend/auth-tests.log
```

`test_auth.py` 使用真实 Argon2id 与模拟数据库验证规则、安全与资源拒绝；`test_mysql_integration.py` 必须使用真实 MySQL/Flyway，未配置时跳过。后者要求设置 `TEST_DATABASE_URL`（库名以 `jobless_auth_test_` 开头）与 `TEST_FLYWAY_COMMAND`，测试库由管理员预先创建，不可填生产库。测试执行两次 Flyway、检查无 Pending，并验证唯一键竞争、持久化会话及真实连接池耗尽；只删除本用例创建的随机账号。

`python artifacts/frontend/verify_login.py` 使用独立 Chrome 和内存数据库替身验证 UI，不连接本机或远程 MySQL，不替代真实迁移验收。需要 Chrome、`websocket-client`，可选依赖见 `requirements-browser.txt`。

## 目标服务器资源验收

未提供目标机器访问凭据，不能将开发机运行成功视为服务器验收。记录启动前后 `free -m`、`/proc/meminfo` 的 `MemAvailable`、`ps -eo pid,comm,rss,%cpu`、MySQL 连接数，以及迁移全进程峰值。系统/宝塔和其他服务、MySQL、Python、Nginx 分别计入，尽量保留至少 350MiB 可用内存。

从开发机对专用测试账号逐级探测，密码通过交互读取，不写入参数或输出：

```text
python -m backend.probe_login https://your-domain.example TestPlayer --concurrency 1 --requests 20
```

分别以并发 1、2、5、10 记录成功请求和全部请求的 p50/p95、吞吐、错误率与 429/503 数量。边界限流继续有效，不能把快速拒绝的延迟当成成功登录延迟。探测会产生有效会话，须在专用测试账号范围内清理。过载同时从另一个已登录浏览器检查 `/api/auth/me` 延迟，观察哈希流程数不超过一、连接数有界、无 OOM/持续换页，长时运行内存无持续增长，并验证分批清理与日志轮转。完成实测后再调整参数，不承诺固定在线人数。

