# 登录功能实施报告

日期：2026-10-18

本文保留登录功能首次交付时的验证记录；其中自由选关与排行榜占位描述为历史状态。当前逐关挑战、个人记录及音乐的实现和验收见 [排行榜实施报告](./ranking-implementation-report.md)。`verify_login.py` 仅保留为历史材料，当前浏览器验收使用 `verify_ranking.py`。

执行依据：[登录功能实施计划书](./login-implementation-plan.md)。用户已明确授权连续执行，无需逐模块确认。

**交付状态：登录代码、迁移、共享弹窗、游戏接入及部署说明已完成；本地测试通过。真实 MySQL/Flyway 和目标 2 核/2GB 服务器验收尚未完成，不能据此认定已上线。**

## 后端五层重构

按用户确认的结构，将后端拆为控制层 `controllers/`、业务层 `services/`、数据访问层 `repositories/`、模型层 `models/` 和公共层 `common/`。调用方向为 Controller → Service → Repository，模型和公共能力由各层按需引用。

实施步骤已完成：提取配置/数据库/安全等公共能力；拆分实体与接口模型；封装用户和会话 Repository；将账号规则、登录限流和事务移入 Service；使用 APIRouter 建立 Controller；将 `main.py` 缩减为应用装配；同步维护命令、测试导入和目录文档。

三个关键设计：Controller 负责 HTTP/Cookie，Service 不接收 Request/Response；Service 控制事务，Repository 只执行数据操作；跨业务能力放 `common/`，用户名规则和登录限流留在业务层。业务异常使用 `AppError`，统一处理器保持原有状态码、`detail` 结构与重试响应头。

HTTP 路径、请求和响应、Cookie、Flyway SQL、数据库结构、`backend/.env` 位置、Uvicorn 启动命令以及单进程资源边界保持兼容。没有新增前端功能或迁移版本。旧平铺模块已移除，内部导入统一指向新目录。

重构验收：后端 **16 项通过、3 项真实 MySQL/Flyway 跳过、0 失败**；浏览器 **7 组通过、0 失败**。新增验证覆盖 Service 业务异常到 HTTP 响应的转换，以及执行器拒绝后归还登录计算槽。29 个 Python 文件语法、五层依赖方向、事务边界、实体关系、配置路径和维护命令加载检查通过。前端源码未改动，未重复运行未受影响的游戏单元测试。

## 模块一：数据库与后端

已新增 FastAPI API、环境示例、生产与测试依赖、用户/会话 SQLAlchemy 映射、Flyway `V1__create_auth_tables.sql`。

- 首次用户名自动注册；已有账号验证原密码，不覆盖显示名或原密码。ASCII 大小写映射到同一账号键，唯一约束和竞争后的重新验证覆盖同名注册分支。
- 前后端按同一 Unicode 15.1 汉字集合逐字符校验，汉字计 3、ASCII 字母数字计 2，上限 24；拒绝空白、标点、表情及未分配码位。密码至少六个 Unicode 字符，不做 trim 或大小写转换，总请求体最大 4KiB。
- Argon2id 显式使用 64MiB、三轮、并行度一；密码验证、新建和重哈希共用一个计算槽。数据库只保存密码哈希与会话 token 的 SHA-256 摘要。
- 会话默认七天；Cookie 为 HttpOnly、SameSite=Lax，HTTPS 配置 Secure。`me` 检查到期，`logout` 删除当前会话并清除 Cookie；所有状态修改校验同源，API 不回显敏感输入并禁止缓存。
- 登录频率可配置，哈希忙时立即 429。同步工作最多四个执行槽，无无界等待任务；MySQL 池默认三条、无溢出、等待三秒，并设置连接/读写超时。执行槽或数据库不可用返回可重试 503；任务取消不会提前释放仍在运行的工作槽。
- 提供分批过期会话清理和小规模登录探测脚本，均有作用注释与工作量限制。

接口为 `POST /api/auth/login`、`GET /api/auth/me`、`POST /api/auth/logout`。生产表不会由 ORM 自动创建。

## 模块二：三页登录与关卡接入

游戏入口、排行榜、论坛复用 `auth.js`、同源 API 客户端与输入校验。右上角提供登录、首次显示名和退出；刷新、跨页使用 Cookie 恢复状态，不保存前端密码，不定时轮询。

弹窗使用深蓝和暖金、半透明渐变、背景模糊和高光边缘；不支持模糊时有可读背景回退。包含用户名计数、字段标签、对应错误、密码提示和等待状态，支持密码管理器与粘贴。

三个首页关卡入口先向服务端确认会话；未登录时记录原目标，成功后才发送授权入口事件并显示原有规则。取消清空待续接目标，留在首页，不启动计时；右上角登录成功停在当前页。原生 dialog 隔离背景焦点，补充 Tab 循环、Escape、关闭焦点恢复及手机可视区域变化后的滚动。

保留原有游戏规则、通关、关卡衔接、计时和结算。排行榜和论坛仍为占位内容，没有新增发帖或服务端成绩功能。

截图位于本地验证目录：[桌面](../artifacts/frontend/login-desktop.png)、[手机](../artifacts/frontend/login-mobile.png)。截图和完整日志按原有 `.gitignore` 约定不提交，验证脚本保留。

## 测试与实际环境

| 验证 | 最终结果 | 证据与边界 |
| --- | --- | --- |
| 后端单元/API（重构后） | 16 通过、0 失败 | `artifacts/backend/refactor-tests.log`；真实 Argon2id、数据库测试替身，不是 SQL 联调 |
| 真实 MySQL/Flyway | 3 跳过 | 未配置 `TEST_DATABASE_URL` 与 `TEST_FLYWAY_COMMAND`；迁移、实际唯一键竞争、持久化及真实连接池耗尽待验证 |
| 前端完整回归 | 34 通过、0 失败 | `artifacts/frontend/auth-tests.log`；含原有游戏规则、计时、结算及四项登录规则/客户端测试 |
| 后续登录客户端与规则改动 | 4 通过、0 失败 | `artifacts/frontend/auth-client-final.log`；未重复运行未受影响的游戏测试 |
| Chrome 浏览器交互（重构后） | 7 组通过、0 失败 | `artifacts/frontend/login-refactor-verification.log`；真实前端、API、Cookie、Argon2id，内存数据库替身 |
| 目标资源与容量 | 未执行 | 无服务器地址/凭据，未测目标机器 CPU、内存、登录 p50/p95 或承载量 |

浏览器覆盖取消与焦点恢复、首次注册和扫雷续接、密码错误及大小写同账号、照明/数独续接、刷新与三页恢复、Tab 循环及手机短屏、网络失败重试、右上角登录保持当前页。已修复验证中发现的短屏焦点遮挡。

实际开发环境：Windows，Python 3.13.12、Node.js 24.11.0、FastAPI 0.141.1、SQLAlchemy 2.0.49、PyMySQL 1.1.2、argon2-cffi 25.1.0、Uvicorn 0.52.1、pydantic-settings 2.12.0、httpx 0.28.1、websocket-client 1.9.0。MySQL 9.5 客户端及本机 3306 监听已检测到，但无项目数据库连接配置，不尝试猜测账号或访问其他数据库。Flyway 命令未安装/不在 PATH。未使用 SQLite 等其他数据库替代 MySQL 验收。

## 模块三：部署与剩余验收

[后端 README](../backend/README.md) 包含本地同源启动、Flyway 两次运行检查、宝塔复用 Nginx/MySQL、单 Uvicorn worker、代理头信任边界、后台服务管理、日志轮转与清理计划任务。`backend/deploy/` 提供配置模板；未修改本机或远程已有 Nginx/MySQL 配置，也未启动常驻生产服务。

真实环境还需：

1. 提供明确的项目/专用测试 MySQL 配置及可运行的 MySQL Flyway 发行版。测试库名必须以 `jobless_auth_test_` 开头，运行可选集成测试，确认迁移重复执行无 Pending、二连接同名竞争和连接池耗尽行为。
2. 在目标规格机器清点系统、宝塔及已有服务，核对预算；维护窗口执行迁移，记录 JVM 全进程峰值，随后单进程启动后端，验证真实 HTTPS Cookie 和三页完整流程。
3. 分别以并发 1、2、5、10 探测专用测试账号，记录成功/全部请求的 p50/p95、吞吐、错误率与 429/503，核实普通会话查询仍可响应、哈希并发始终不超过一、MySQL 连接有界。
4. 完成长时间稳定性、OOM/换页、至少 350MiB 余量目标、会话分批清理和日志轮转检查，再确认上线参数。预算和本地结果不构成生产容量承诺。

`README-CONSTRAINTS.md` 在任务开始时已有用户未提交修改，本次保留该文件内容；计划书状态、根 README 和项目目录树已按本次交付同步。
