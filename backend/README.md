# 登录后端运行与部署

采用 FastAPI、SQLAlchemy/PyMySQL 和 Argon2id。数据库结构只由 Flyway 管理，应用启动不自动建表。游戏仍在浏览器中运行；提供逐关挑战、通关记录与四个排行榜，论坛仍为占位页面。

需要在本机把 MySQL 一并容器化验证时，使用项目根目录 `compose.yaml`，参见 [Docker 部署与验收](./deploy/docker/README.md)。该方案使用独立数据库与数据卷，不读取下面的 `backend/.env`；服务器宝塔复用方案仍按本文执行。

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

确认目标库名、备份和维护窗口。新库依次执行 `V1__create_auth_tables.sql`、`V2__create_ranking_tables.sql` 和 `V3__add_user_avatar.sql`；已有库只执行尚未应用的版本，已有 V2 的库新增 V3。再次 migrate 不应有待执行迁移。配置禁止 `clean` 和自动 baseline；禁止直接修改已执行 SQL，后续变更新增 V4 等新版本。

2 核/2GB 与宝塔共存时先检查 `MemAvailable` 和现有服务占用；必要时停止本项目 Python，再单次执行迁移，完成后退出并启动 Python。`JAVA_ARGS=-Xms32m -Xmx256m` 仅为评估起点，不能视为 Flyway 全进程内存上限。

## API 与边界

| 接口 | 成功行为 | 主要失败 |
| --- | --- | --- |
| `POST /api/auth/login` | 首次自动注册或验证已有密码；返回 `{user:{id,username},created}` 并设置 Cookie | 401 密码错误、403 来源错误、413 请求体过大、422 输入错误、429 频率/哈希繁忙、503 数据库/执行槽繁忙 |
| `GET /api/auth/me` | 返回 `{id,username,avatar_id}` | 401 会话无效、503 数据库/执行槽繁忙 |
| `PUT /api/auth/avatar` | 提交 `{avatar_id}`，更新当前账号并返回 `{id,username,avatar_id}` | 401 未登录、403 来源错误、413 超过4KiB、422 非严格整数/清单未知编号/多余字段、503 数据库/执行槽繁忙 |
| `POST /api/auth/logout` | 当前会话失效并清除 Cookie，返回 204 | 403 来源错误、503 暂时不可用 |

状态修改接口要求同源 `Origin` 或 `Referer`，命令行客户端也须提供正确 `Origin`。服务不开放跨源 CORS。API 响应为 `no-store`，错误不回显密码、密码摘要或数据库内部消息。

登录返回的 user 同样增加 `avatar_id`。头像原图为 `source/imge/avatar/001.png` 至 `025.png`，在开发机安装 Pillow 后执行 `python source/imge/prepare_avatars.py --preview`，生成 `frontend/assets/avatars/v1/` 的25张128px WebP及共用清单。服务器硬盘保存成品，Nginx分发；数据库只存 `TINYINT UNSIGNED NOT NULL DEFAULT 1` 编号，不存图片、Base64或路径。生产 Python 不依赖 Pillow，不在请求中处理图片。图片内容更新时使用新版本资源路径，并同步生成器、清单读取路径和前端资源路径。

头像业务使用独立 Controller/Service、现有用户 Repository和有界数据库执行器，认证和单字段写入在一个工作线程内提交。MySQL 5.7 不依赖 CHECK，严格输入校验按共用清单执行。四榜现有用户关联查询直接带出当前头像，不改变历史成绩快照。清单只缓存编号，不缓存图片内容。

上线前备份并执行 V3，再更新后端与前端；用户表 ALTER 的锁表时间需在目标版本和数据量下评估，必要时安排维护窗口。回退旧应用可保留新增列。当前资源打包已递归包含 frontend/assets 和 migrations，无需新增卷或常驻服务。头像完整实现及验收状态见 [实施报告](../docs/avatar-implementation-report.md)。

用户名按 Unicode 字符计数：ASCII 字母/数字计 2，汉字计 3，上限 24。前后端固定采用 Unicode 15.1 已分配汉字范围，包含常见、兼容及补充平面汉字，排除未分配码位；更新范围时须同步两端。仅折叠 ASCII 大小写，数据库 `utf8mb4_bin` 唯一键保留其他字符差异。密码至少六个 Unicode 字符，原样保留空格与大小写；总请求体仍受 4KiB 限制。

会话为 32 随机字节生成的 URL 安全 token；Cookie 使用 HttpOnly、SameSite=Lax（可改 strict）、Path=/，HTTPS 开启 Secure。数据库只保存 SHA-256 摘要与 UTC 到期时间，默认七天。密码使用显式 Argon2id `memory_cost=65536 KiB, time_cost=3, parallelism=1`，校验、创建和重哈希共用一个计算槽，忙时立即返回 429。

同步数据库流程最多四个执行槽、四个工作线程，无等待任务队列。数据库池默认 `3+0`、等待三秒，连接超时三秒、读写各五秒。工作线程完成前不会因客户端取消而提前释放槽或关闭正在使用的会话。应用按客户端地址限流，默认每 60 秒五次，最多保留 2048 个限流键。该保护用于计划中的单进程；大量不同地址可淘汰旧键，生产必须保留 Nginx 边界限流，不能绕过代理公开 API 端口或随意扩多进程。

## 宝塔与 Nginx

采用“Docker 后端 + 宝塔已有 Nginx/MySQL”的离线镜像部署时，参见 [服务器快速部署](./deploy/server/README.md)。该包沿用下面的代理和限流模板，提供 Linux 宿主机网络 Compose 与隐藏读取密码的配置脚本，无需在服务器安装 Python 项目依赖。

排行榜新增 API 同样通过下述 `/api/` 通用代理，不需要增加常驻服务。

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

## 排行榜与挑战

排行榜与挑战 API：

| 接口 | 行为 |
| --- | --- |
| `GET /api/challenges/config` | 仅返回开发通关按钮开关，默认关闭 |
| `POST /api/challenges/start` | 登录后使用 request_id 幂等创建本轮；旧轮次失效 |
| `POST /api/challenges/{run_id}/restart` | 校验已解锁、revision 和 request_id，重置本关与后续本轮状态 |
| `POST /api/challenges/{run_id}/complete` | 校验本轮前序关及 attempt_id，单次只保存当前关；三关齐全自动保存总成绩 |
| `GET /api/rankings/{category}?page=1&page_size=20` | 公开分页；category 为 total/mine/akari/sudoku；单页上限 50 |
| `GET /api/records/me?category=total` | 登录用户自己的最佳与最近三次，重合使用同一记录 ID |

新增 `challenge_progress`（每人最多一行）、`completion_records`（每人每类最多四条）和 `leaderboard_entries`（每人每类一行）。总成绩自带三项用时快照，不依赖单项历史记录长期存在；写入按用户行锁串行化，在同一事务维护最佳、最新记录和摘要。查询先用索引读取有限页，再统计更快人数得到跨页并列名次，不使用窗口函数或持久化名次。

`duration_seconds` 必须为 0～604800 的整数；未完成用 null，不能把 0 当作未完成。`revision`、尝试和轮次必须匹配；重复上传相同数据不会追加记录，修改已经接收的成绩返回 409。未登录返回 401、顺序或轮次冲突 409、开发标记未启用 403、校验错误 422；写请求要求同源，实际请求体不超过 4KiB，数据库繁忙沿用 503。

开发验收在专用开发库设置 `DEV_QUICK_COMPLETE_ENABLED=true` 并重启；前端读取开关后显示“开发验收：一键通关”，每次只完成当前关。默认及正式环境保持 false；关闭时专用开发标记写入被拒绝。后续移除配置、config 响应字段、`dev-quick-complete.js`、按钮和 main 中开发入口，再回归正常通关及结算。

棋盘、完成判断与秒数仍来自浏览器，此实现校验身份和流程，不构成完整防作弊。测试成绩只写开发/临时数据库，禁止导入正式库。

## 测试

在项目根目录执行，完整输出写入日志：

```powershell
New-Item -ItemType Directory -Force artifacts/backend | Out-Null
python -m unittest discover -s backend/tests -v *> artifacts/backend/auth-tests.log
cd frontend
npm test *> ../artifacts/frontend/auth-tests.log
```

`test_auth.py` 使用真实 Argon2id 与模拟数据库验证规则、安全与资源拒绝；`test_mysql_integration.py` 必须使用真实 MySQL/Flyway，未配置时跳过。后者要求设置 `TEST_DATABASE_URL`（库名以 `jobless_auth_test_` 开头）与 `TEST_FLYWAY_COMMAND`，测试库由管理员预先创建，不可填生产库。测试执行两次 Flyway、检查无 Pending，并验证唯一键竞争、持久化会话及真实连接池耗尽；只删除本用例创建的随机账号。

`artifacts/frontend/verify_login.py` 保留为早期登录验收材料，其数据库替身与自由选关步骤不支持当前挑战接口；当前登录与逐关回归使用下述 `verify_ranking.py`。需要 Chrome、`websocket-client`，可选依赖见 `requirements-browser.txt`。

`python artifacts/frontend/verify_ranking.py` 使用临时 SQLite 与独立 Chrome 验证真实登录、逐关通关、保存失败重试、完整结算、四榜分页与手机布局，输出摘要并保存截图。临时数据在结束后清理；该验证不替代 MySQL JSON、行锁、外键与 Flyway 验收。`test_mysql_integration.py` 增加真实并发重复通关与总成绩快照验证；没有专用库和 Flyway 时明确跳过。

## 目标服务器资源验收

未提供目标机器访问凭据，不能将开发机运行成功视为服务器验收。记录启动前后 `free -m`、`/proc/meminfo` 的 `MemAvailable`、`ps -eo pid,comm,rss,%cpu`、MySQL 连接数，以及迁移全进程峰值。系统/宝塔和其他服务、MySQL、Python、Nginx 分别计入，尽量保留至少 350MiB 可用内存。

从开发机对专用测试账号逐级探测，密码通过交互读取，不写入参数或输出：

```text
python -m backend.probe_login https://your-domain.example TestPlayer --concurrency 1 --requests 20
```

分别以并发 1、2、5、10 记录成功请求和全部请求的 p50/p95、吞吐、错误率与 429/503 数量。边界限流继续有效，不能把快速拒绝的延迟当成成功登录延迟。探测会产生有效会话，须在专用测试账号范围内清理。过载同时从另一个已登录浏览器检查 `/api/auth/me` 延迟，观察哈希流程数不超过一、连接数有界、无 OOM/持续换页，长时运行内存无持续增长，并验证分批清理与日志轮转。完成实测后再调整参数，不承诺固定在线人数。

