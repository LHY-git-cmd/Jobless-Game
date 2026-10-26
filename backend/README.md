# 登录后端运行与部署

采用 FastAPI、SQLAlchemy/PyMySQL 和 Argon2id。数据库结构只由 Flyway 管理，应用启动不自动建表。游戏仍在浏览器中运行；提供独立关卡、通关记录、星数和等级排行榜以及文字论坛和站内消息。竞技积分榜已接入有符号积分余额。

2026-10-26新增V20：体力上限及新记录初始值提高到10，旧余额与恢复节点保留，每30分钟恢复1点。修复生产Session关闭autoflush时，通关返还余额被后续快照读取覆盖的问题；返还余额和凭证在原事务中先flush再读取，异常仍整体回滚。上线需执行V20并同步更新API及前端体力显示。历史漏返不在迁移中自动补发，当前规则与验收见 [10点体力与返还修复](../docs/energy-ten-refund-fix.md)。

新增正式成长与双人照明竞速使用 `/api/v1`，与旧成绩和本地练习分开。先在专用库执行 Flyway V1～V9，再按阶段配置 `PROGRESSION_ENABLED`、`COSMETICS_ENABLED`、`PK_ROOMS_ENABLED`、`MATCHMAKING_ENABLED`；全部默认 `false`。页面入口是 `/journey.html` 和 `/pk.html`。HTTP部署仍遵循原Cookie配置，正式HTTPS必须开启Secure。

后续页面调整：三个游戏入口分别进入 `journey.html?game_id=mine|akari|sudoku` 的新版选关框架。按用户要求，原单关、照明十关目录与练习九关先从页面下线，等待重新设计；不删除数据库成果或改写已执行迁移。当前页面回归改用 `artifacts/frontend/verify_game_catalog.py`；下文原完整关卡浏览器命令属于历史验收，当前空目录不再运行该流程。

现账号5级（72经验）解锁竞技；原三游戏资格凭据保留但不再作为前置。扫雷由服务器逐格揭开，旧成绩和开发通关不能换资格。独立主题仅改变成长/竞速页的语义色和棋盘描边。房间/匹配各有容量保护，单进程调度器负责倒计时、平局/断线/超时，SSE鉴权后立即释放数据库连接，重启作废所有未完成房间与等待票。生产仍为一个worker、320MiB/1CPU、数据库池3/执行槽4。

Nginx需要同步合并 `deploy/nginx-site.conf.example` 的精确 `/api/v1/me/events` 路由：关闭buffer/cache，读取超时75秒；普通API维持短超时。新v1写请求4KiB，论坛维持独立32KiB。Docker镜像已包含冻结题库与历史清理工具，正式应用启动不自动迁移。

本轮验证与操作命令（在项目根目录运行，日志写入本地artifacts）：

```powershell
python -m backend.content_check
python -m backend.export_game_contract --check
python -m unittest discover -s backend/tests *> artifacts/backend/tests.log
python backend/verify_progression_mysql.py *> artifacts/backend/mysql.log
python artifacts/frontend/verify_game_progression.py *> artifacts/backend/browser.log
```

MySQL脚本要求Docker可用及本地有 `mysql:5.7.40`、`redgate/flyway:13.6.0`，随机凭据仅进入子进程环境；使用临时容器/专用测试库，结束仅删除该容器。浏览器验收要求Chrome及 `requirements-browser.txt`，仅用临时SQLite，不连接项目库。

维护清理用 `python -m backend.cleanup_game_history --batch-size 200 --max-batches 10`，必须指向明确配置并已备份的项目库：结果30天后变为7天410墓碑，再回收；永久星级、奖励凭据、资格和外观不会删除。该脚本按需运行，不新增常驻清理服务。V9仅补充清理索引，V1～V8均保留。

目标机容量观测工具：`python -m backend.probe_pk_capacity --base-url https://测试站点 --sessions-file artifacts/backend/pk-sessions.local.json --seconds 1800`。会话文件是最多16个**专用测试账号Cookie值**的JSON数组，需匹配 `--cookie-name`，不能提交或分享。工具只读HTTP/SSE，不自动创建对局；按方案另准备2/4/8人对局、8人排队及重连/结束循环，合并目标机CPU、RSS、MemAvailable、MySQL锁/OOM等证据后再判断是否通过。客户端观测报告始终不自行宣告目标容量通过。

完整边界、测试统计及发布/回退注意事项见 [成长竞速实施报告](../docs/game-progression-pk-report.md)，契约草案见 [OpenAPI](../docs/game-progression-openapi.json)。

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

确认目标库名、备份和维护窗口。新库依次执行 V1～V4，V3 为头像，`V4__create_forum_tables.sql` 为论坛五张表；已有库只执行尚未应用的版本。再次 migrate 不应有待执行迁移。配置禁止 `clean` 和自动 baseline；禁止直接修改已执行 SQL，后续变更新增 V5 等新版本。用户外键沿用现有 `INT UNSIGNED`，论坛内容编号采用 `BIGINT UNSIGNED`；兼容 MySQL 5.7，不依赖 CHECK 或窗口函数。

2 核/2GB 与宝塔共存时先检查 `MemAvailable` 和现有服务占用；必要时停止本项目 Python，再单次执行迁移，完成后退出并启动 Python。`JAVA_ARGS=-Xms32m -Xmx256m` 仅为评估起点，不能视为 Flyway 全进程内存上限。

## API 与边界

| 接口 | 成功行为 | 主要失败 |
| --- | --- | --- |
| `POST /api/auth/login` | 首次自动注册或验证已有密码；返回 `{user:{id,username,avatar_id},created}` 并设置 Cookie | 401 密码错误、403 来源错误、413 请求体过大、422 输入错误、429 频率/哈希繁忙、503 数据库/执行槽繁忙 |
| `GET /api/auth/me` | 返回 `{id,username,avatar_id}` | 401 会话无效、503 数据库/执行槽繁忙 |
| `PUT /api/auth/avatar` | 提交 `{avatar_id}`，更新当前账号并返回 `{id,username,avatar_id}` | 401 未登录、403 来源错误、413 超过4KiB、422 非严格整数/清单未知编号/多余字段、503 数据库/执行槽繁忙 |
| `POST /api/auth/logout` | 当前会话失效并清除 Cookie，返回 204 | 403 来源错误、503 暂时不可用 |

状态修改接口要求同源 `Origin` 或 `Referer`，命令行客户端也须提供正确 `Origin`。服务不开放跨源 CORS。API 响应为 `no-store`，错误不回显密码、密码摘要或数据库内部消息。

登录返回的 user 同样增加 `avatar_id`。头像原图为 `source/imge/avatar/001.png` 至 `025.png`，在开发机安装 Pillow 后执行 `python source/imge/prepare_avatars.py --preview`，生成 `frontend/assets/avatars/v1/` 的25张128px WebP及共用清单。服务器硬盘保存成品，Nginx分发；数据库只存 `TINYINT UNSIGNED NOT NULL DEFAULT 1` 编号，不存图片、Base64或路径。生产 Python 不依赖 Pillow，不在请求中处理图片。图片内容更新时使用新版本资源路径，并同步生成器、清单读取路径和前端资源路径。

头像业务使用独立 Controller/Service、现有用户 Repository和有界数据库执行器，认证和单字段写入在一个工作线程内提交。MySQL 5.7 不依赖 CHECK，严格输入校验按共用清单执行。三个单项榜现有用户关联查询直接带出当前头像，不改变历史成绩快照。清单只缓存编号，不缓存图片内容。

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

当前页面改为星数、等级和竞技积分三个榜单入口。星数按 `total_stars` 降序、同星并列；等级采用正式成长阈值计算，按 `xp` 降序、同经验并列。并列时按用户编号倒序稳定分页，仅有 `player_progression` 摘要的玩家入榜。索引由增量 V17 创建，适用于 MySQL 5.7；每页最多 50 条，名次跨页计算，不使用窗口函数。积分榜读取arena_accounts，胜利+20、失败−10、允许负分，结果和每局每人唯一流水在同一事务提交。原用时榜 API 继续兼容旧客户端。

排行榜与挑战 API：

| 接口 | 行为 |
| --- | --- |
| `GET /api/challenges/config` | 仅返回开发通关按钮开关，默认关闭 |
| `POST /api/challenges/start` | 登录后使用 request_id 幂等创建本轮；旧轮次失效 |
| `POST /api/challenges/{run_id}/restart` | 校验 revision 和 request_id，仅重置指定关卡，其他关卡不受影响 |
| `POST /api/challenges/{run_id}/complete` | 校验当前进度及 attempt_id，可按任意顺序保存单关，不生成总成绩 |
| `GET /api/rankings/{category}?page=1&page_size=20` | 公开分页；category 为 mine/akari/sudoku；单页上限 50，total 返回 422 |
| `GET /api/rankings/growth/{category}?page=1&page_size=20` | 当前公开成长榜；category 为 stars/level/points；需开启 progression；单页上限 50 |
| `GET /api/records/me?category=mine` | 默认扫雷，可切换照明/数独，返回本人最佳与最近三次，total 返回 422 |

旧挑战接口沿用 `challenge_progress`（每人最多一行，存储三个独立尝试）、`completion_records`（每人每类最多四条）和 `leaderboard_entries`（每人每类一行）。停止创建和公开整轮成绩，既有总榜字段、数据及已执行迁移保留；成长榜索引另由 V17 增量迁移提供。写入按用户行锁串行化，在同一事务维护单项最佳、最新记录和摘要。查询先用索引读取有限页，再统计更快人数得到跨页并列名次，不使用窗口函数或持久化名次。

`duration_seconds` 必须为 0～604800 的整数；未完成用 null，不能把 0 当作未完成。重开要求匹配当前 `revision`，通关要求匹配当前关卡的尝试和进度标识，不接受未来版本；其他关重开导致的版本增长不作废本关待提交成绩。重复上传相同数据不会追加记录，修改已经接收的成绩返回 409。未登录返回 401、尝试或进度冲突 409、开发标记未启用 403、校验错误 422；写请求要求同源，实际请求体不超过 4KiB，数据库繁忙沿用 503。

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

`artifacts/frontend/verify_login.py` 保留为早期登录验收材料，其数据库替身不支持当前挑战接口；当前登录与独立关卡回归使用下述 `verify_ranking.py`。需要 Chrome、`websocket-client`，可选依赖见 `requirements-browser.txt`。

`python artifacts/frontend/verify_ranking.py` 使用临时 SQLite 与独立 Chrome 验证真实登录、自由选关、单关重开、保存失败重试、单关结算、三个分榜分页与手机布局，输出摘要并保存截图。临时数据在结束后清理；该验证不替代 MySQL JSON、行锁、外键与 Flyway 验收。`test_mysql_integration.py` 覆盖真实并发重复通关与不生成整轮记录；没有专用库和 Flyway 时明确跳过。

## 文字论坛与站内消息

所有接口位于 `/api/forum/`：公开读取帖子摘要/详情、顶层评论、根评论下回复及目标评论上下文；写入须登录且同源。接口完整清单和规则见 [论坛实施报告](../docs/forum-implementation-report.md)。发布帖子只接收 request_id 和 body，无标题输入或生成标题；请求不能指定作者或根评论，回复根归属由服务端验证。文字仅按纯文本显示，正文2000、评论/回复500个 Unicode 码点，先去除首尾空白。V4 历史 title 列保留以兼容已有数据库，新帖写空字符串，接口和页面不返回/展示它，不需新增迁移。

`POST /posts`、`POST /posts/{id}/comments` 需要 UUID `request_id`。同账号同编号同负载返回原内容，改负载409；先确认幂等再检查发布间隔。`FORUM_POST_INTERVAL_SECONDS=60`、`FORUM_COMMENT_INTERVAL_SECONDS=3` 可配置，评论与回复共用间隔，超限429携带 Retry-After。帖子及评论的点赞使用 PUT/DELETE `/posts/{id}/like`、`/comments/{id}/like`，重复调用不重复计数。用户、帖子、评论按固定顺序加锁，内容、计数和通知统一提交或回滚。

`GET /notifications/unread-count` 只返回本人未读数（最多100）和最新编号；`GET /notifications` 返回有限页和 `through_id`。单条已读使用 `PUT /notifications/{id}/read`，全部已读使用 `POST /notifications/read-all` 和 `{through_id}`，不处理边界之后到达的新消息。自己互动不通知；回复只提醒直接被回复作者；首次点赞通知以固定事件键去重，取消和重新点赞不追加或重置已读。

帖子和消息按 ID 倒序，评论和回复正序；`cursor` 可选，`limit` 默认20（回复10），最大50。响应包含 `items` 与可空的 `next_cursor`。列表只含160字符摘要，完整正文由详情返回；作者、当前头像和点赞状态使用批量关联，不逐条查库。上下文接口 `/posts/{post_id}/comments/{comment_id}` 返回 `target` 和 `root` 供通知直接定位。

应用与两种 Nginx 模板为论坛写请求单独设置32KiB，按实际字节计数并覆盖无 Content-Length 请求；原登录、头像、挑战仍4KiB。沿用四槽同步数据库执行器、现有连接池和单 Uvicorn worker。页面可见且登录时，前一次检查结束后安排60秒下一轮；隐藏或退出停止，503遵循 Retry-After 退避。

本地回归运行 `python artifacts/frontend/verify_forum.py`，完整输出重定向到日志。该脚本使用独立 Chrome、临时 SQLite 和两个真实 Cookie 账号验证发布/回复/点赞、消息定位、跨浏览器已读、手机布局和棋局恢复。真实 V4/Flyway、外键及并发测试在 `test_mysql_integration.py`，只允许配置的 `jobless_auth_test_` 专用库；缺少环境时明确跳过，不能将 SQLite 当作 MySQL 验收。

## 扫雷五档关卡

新版扫雷选关入口为 `journey.html?game_id=mine`。关卡与逐星经验配置来自 `backend/content/mine-catalog-v2.json`；V10发布原七项，`V11__expand_mine_board_choices.sql` 为中等、困难、地狱各补两个矩形规格，共十三项。现有数据库只执行尚未执行的迁移，不修改已应用版本。正式开局和结算依旧要求 `PROGRESSION_ENABLED=true` 及登录。

`GET /api/v1/levels?game_id=mine` 在成长开关关闭时也允许公开读取十三项难度元数据，避免无法浏览选择；创建尝试仍受开关保护。教学动作使用 `PUT /api/v1/attempts/{id}/tutorial-actions/number` 和 `/flag`，请求空体、严格顺序、重放幂等；普通扫雷继续使用已有reveals与completion资源。新普通关首次揭格安全，矩形索引按绑定行列计算；终盘持久化时间，结算重试不会降低星级。奖励配置和教学固定1星规则按版本读取，历史资格及旧关定义保留。

`python artifacts/frontend/verify_mine_redesign.py` 运行隔离浏览器验收；加 `--preview --port 8002` 启动独立SQLite本地预览，可真实注册和领取测试成长，数据仅在忽略的artifacts目录。发布前在专用MySQL上完成Flyway V11及对应API验证。`python backend/verify_progression_mysql.py backend.tests.test_mysql_integration.MySQLIntegrationTests.test_v10_mine_catalog_and_concurrent_reward` 可创建一次性MySQL5.7容器验证全部十三项定义与并发奖励防重，结束删除本脚本容器。

## 目标服务器资源验收

新版扫雷支持 `PUT /api/v1/attempts/{id}/clock`，严格JSON为 `{paused, revision, command_id}`：只接受暂停意图、预期时钟修订和UUID，计时由服务器产生。同编号重试幂等，旧修订409；终盘后只返回原有冻结时间。JSON棋盘存储暂停起点、累计毫秒与修订，兼容缺少字段的旧尝试，无需新增数据库迁移。客户端离页请求用fetch keepalive；暂停成功后揭格和教学写操作返回409，继续后可操作，完成时扣除累计暂停时长。此端点仅适用于扫雷，不改竞速统一计时或其他游戏规则。

未提供目标机器访问凭据，不能将开发机运行成功视为服务器验收。记录启动前后 `free -m`、`/proc/meminfo` 的 `MemAvailable`、`ps -eo pid,comm,rss,%cpu`、MySQL 连接数，以及迁移全进程峰值。系统/宝塔和其他服务、MySQL、Python、Nginx 分别计入，尽量保留至少 350MiB 可用内存。

从开发机对专用测试账号逐级探测，密码通过交互读取，不写入参数或输出：

```text
python -m backend.probe_login https://your-domain.example TestPlayer --concurrency 1 --requests 20
```

分别以并发 1、2、5、10 记录成功请求和全部请求的 p50/p95、吞吐、错误率与 429/503 数量。边界限流继续有效，不能把快速拒绝的延迟当成成功登录延迟。探测会产生有效会话，须在专用测试账号范围内清理。过载同时从另一个已登录浏览器检查 `/api/auth/me` 延迟，观察哈希流程数不超过一、连接数有界、无 OOM/持续换页，长时运行内存无持续增长，并验证分批清理与日志轮转。完成实测后再调整参数，不承诺固定在线人数。



## 三模式竞技大厅与首次三星双倍（V18/V19）

执行新增V18发布39个普通关奖励版本，旧尝试继续绑定旧版本。等级曲线来自progression-policy-v2.json，1～6级为0/18/36/54/72/90；普通关首次三星的当局新增经验额外奖励同等经验，独立first-three-double凭据永久防重，历史已三星不补发。完成快照包含base_awarded_xp和first_three_star_bonus，旧结果不改写。

V19新增arena_accounts、arena_ledger、arena_invitations，扩展房主/source及成员隐藏扫雷board，并作废旧规则未结束房间及等待票。积分流水不关联可清理房间外键，历史清理不能删除该凭据。生产需备份、维护迁移并核对开关，不能用ORM自动建表代替Flyway。

| 接口 | 行为 |
| --- | --- |
| GET /api/v1/me/arena/state?last_room=UUID | 一次权威快照返回等级、积分、房间、匹配票及邀请；只恢复本人有权房间 |
| GET /api/v1/me/arena | 本人积分摘要；GET不初始化账户 |
| POST /api/v1/me/presence | 可见页面在线租约；最多4096账号，每账号4会话，60秒失效；跨标签合并 |
| GET /api/v1/arena/users?q=ID或完整用户名 | 精确搜索，最多10人，返回公开头像和可邀请状态；5级后可用 |
| POST /api/v1/arena/invitations | {user_id,game_id,difficulty:normal}，UUID幂等创建，60秒有效 |
| GET /api/v1/me/arena/invitations | 本人待处理邀请，最多20条 |
| POST /api/v1/arena/invitations/{id}/accept | 被邀请者接受，复核双方在线/等级/占用，幂等入房 |
| DELETE /api/v1/arena/invitations/{id} | 发送者取消或接收者拒绝；已接受需离开房间 |
| PUT /api/v1/rooms/{id}/mode | 好友房主If-Match切换模式，清空双方准备；匹配房锁定模式 |
| PUT /api/v1/rooms/{id}/reveals/{index} | 竞技扫雷权威揭格，空JSON；地雷不发往浏览器 |

房间/匹配DTO允许game_id为mine/akari/sudoku，三个独立池，仍只接受normal规格。双方准备后3秒开局；同局双方同题，当前竞技从正式闯关配置派生：扫雷简单10×10/10雷、照明第10关、数独简单9×9。照明旋转/镜像与数独数字双射保持规则和解，续局避免立即重题；扫雷共享隐藏雷区及0号安全起点，双方揭格进度独立。比赛不能暂停统一时钟，10分钟上限，1秒正确完成平局窗口。踩雷与退出即时判负按HTTP入口时间排序，不能让数据库排队倒置先后。

竞技初始100积分，三游戏共用，好友和匹配均计分；胜+20负-10，平局/双方超时/作废为0。初始账户只在实际入房时写入；积分余额和流水唯一键均为服务端权威。搜索/邀请/房间操作按有界运行锁及固定用户锁顺序执行；待处理邀请全局32、每目标8、每发送者1，过期通知由唯一调度器处理，终态邀请由有界历史清理回收。

2026-10-23阶段的MySQL5.7/Flyway曾因Docker启动故障未完成，仅完成独立MySQL9.5验收。2026-10-27已使用隔离MySQL5.7.40与真实Flyway执行至V21，验证隐藏棋盘、负积分、唯一结算、保留席位和并发续局；目标2核2GB容量仍需另行验收。当前证据见 [竞技流程优化报告](../docs/arena-flow-optimization-report.md)。

本机隔离预览：`python artifacts/frontend/verify_arena_preview.py --port 8006`，仅访问artifacts/frontend/sudoku-preview.sqlite3，保留账号、成长和原尝试，追加缺失版本与SQLite字段；不连接业务MySQL。双浏览器验收：`python artifacts/frontend/verify_arena.py`，仅使用新建临时库和测试账号，不修改预览账号等级。

## 竞技跨页与续局（V21）

发布前执行新增V21并同步前后端；增加pk_rooms.lobby_expires_at索引及next_room_id。原结果、提交、积分流水保持不变，不用重置已有账号数据。

`POST /api/v1/rooms/{id}/continuation` 接收 `{ready:false}` 返回准备房间，或 `{ready:true}` 确认本人再战。调用者必须是仍在场的成员，原局必须已结束；后继局由服务器保存唯一链接，双方并发和丢响应重试共用一局，无需客户端另外提供创建幂等键。对手尚未确认时不开始倒计时。新局使用新的room_id，旧结果仍可由原接口读取。

正常结束后保留仍在场的成员，最多5分钟，继续计入4房容量；主动退出立即释放，断线30秒或保留到期后回收，服务重启释放保留席位但不覆盖已有结果。准备房间也沿用原到期规则。GET仍只读，状态推进由唯一调度任务负责。

大厅为 `/pk.html`，倒计时结束后进入 `/pk-game.html?room=UUID`。独立游戏页固定读取该局，确保对手先返回时本人仍可查看结算。当前双浏览器验收入口为 `python artifacts/frontend/verify_arena_flow.py`，覆盖三棋盘、跨页恢复、再战与320/375像素布局；verify_arena.py保留旧页内布局的历史验证记录。
