# 项目目录树

更新日期：2026-10-22。以下按当前实际目录整理，每个文件夹均标注用途；截图、日志、缓存和同类素材按类型合并列示。

```text
crawler-portal/                            # 项目根目录：前端、登录后端、素材及文档
├── .git/                                 # Git 仓库元数据：远程关联、分支与提交历史；内部不展开
├── .gitignore                            # 排除秘密、本地配置、依赖、缓存及验证生成物
├── .dockerignore                         # Docker 构建上下文白名单，排除秘密与本机文件
├── .env.docker.example                   # 本机容器环境模板；真实 .env.docker 不提交
├── compose.yaml                          # 本机 Nginx/API/MySQL/Flyway 栈与资源限制
├── LICENSE                               # 远程初始提交已有的项目许可证，保留原文
├── README.md                             # 项目说明、本地预览、测试和部署入口
├── README-CONSTRAINTS.md                  # 项目硬约束：资源、技术、账号及验收要求
├── PROJECT-TREE.md                        # 本项目树及目录用途说明，随结构变更更新
├── 解密游戏+机器人提示设计.md              # 当前版本游戏规则与早期设计说明
│
├── .tools/                               # 本地辅助工具与临时提交辅助脚本；不纳入版本管理
├── backend/                              # FastAPI 登录、独立关卡、排行榜、Flyway 与部署支持
│   ├── content/                          # 冻结关卡、规则门槛与独立PK题库
│   │   ├── game-catalog-v1.json           # 十关照明、三题PK、历史初级扫雷/数独与建议参数v1
│   │   ├── mine-catalog-v2.json           # 教学与四档各三规格，共十三项扫雷、时限及逐星经验
│   │   ├── sudoku-catalog-v2.json         # 数独五档十三题、尺寸、推理技巧、时限及逐星经验
│   │   └── sudoku-audit-v2.json           # 开发机离线唯一解和逐步推理记录，不下发浏览器
│   ├── sudoku_content.py                 # 有界离线构造、两解搜索及四档逻辑分级器
│   ├── content_check.py                  # 开发机唯一解、初级单候选与只生成新文件的题库工具
│   ├── cleanup_game_history.py           # 有界历史清理，保留永久成长与资格
│   ├── export_game_contract.py           # 从实际v1路由和DTO导出/核对契约草案
│   ├── verify_progression_mysql.py       # 独立临时MySQL5.7/Flyway及并发联调入口
│   ├── probe_pk_capacity.py              # 专用测试会话HTTP/SSE共存观测，默认30分钟
│   ├── README.md                         # 本地运行、迁移、宝塔部署及资源验收说明
│   ├── .env.example                      # 不含真实凭据的应用配置模板
│   ├── flyway.conf.example               # 不含真实凭据的 Flyway 配置模板
│   ├── requirements.txt                  # 生产 Python 依赖范围
│   ├── requirements-test.txt             # API 测试依赖
│   ├── requirements-browser.txt          # 可选 Chrome/CDP 验证依赖
│   ├── cleanup_sessions.py               # 单次有界分批清理过期会话
│   ├── probe_login.py                    # 从开发机运行的小规模登录探测
│   ├── app/                              # 五层后端：控制、业务、数据访问、模型、公共
│   │   ├── __init__.py                   # 后端应用包标识
│   │   ├── main.py                       # 应用装配：注册路由、中间件、异常和静态页面
│   │   ├── controllers/                 # 控制层：HTTP 协议、Cookie 和响应映射
│   │   │   ├── __init__.py               # 控制层包标识
│   │   │   ├── auth_controller.py        # 登录、当前用户、注销路由及同源校验
│   │   │   ├── avatar_controller.py      # 当前登录账号更换预设头像的同源接口
│   │   │   ├── forum_controller.py       # 论坛公开读取、同源写入及账号消息路由
│   │   │   ├── progression_controller.py # 正式关卡、尝试、成长、资格和外观REST资源
│   │   │   ├── pk_controller.py          # 房间、成员、提交、匹配票及不持DB的SSE响应
│   │   │   ├── pk_ingress.py             # 终盘入口时间/待处理任务登记与取消清理
│   │   │   └── ranking_controller.py     # 挑战创建/重开/通关、个人记录与公开排行榜路由
│   │   ├── services/                    # 业务层：流程、事务与登录专属资源限制
│   │   │   ├── __init__.py               # 业务层包标识
│   │   │   ├── auth_service.py           # 注册/验证密码、会话业务及事务控制
│   │   │   ├── avatar_service.py         # 有界线程中认证和更新账号头像，管理事务
│   │   │   ├── forum_service.py          # 论坛幂等、频率、归属、点赞与通知原子事务
│   │   │   ├── auth_rules.py             # 用户名计数、账号键和密码长度规则
│   │   │   ├── login_limiter.py          # 有界单进程登录频率保护
│   │   │   ├── game_rules.py             # 照明/数独终盘验证、毫秒星级及版本化逐星经验
│   │   │   ├── progression_service.py    # 矩形扫雷/教学/首击安全、冻结计时及幂等奖励/资格事务
│   │   │   ├── pk_service.py             # 双人房间、统一计时、平局及FIFO匹配事务
│   │   │   ├── pk_runtime.py             # 有限SSE队列、接收窗口及单进程运行索引
│   │   │   ├── pk_lifecycle.py           # 唯一调度任务、重启作废和有界状态转换
│   │   │   └── ranking_service.py        # 独立关卡重开/通关、幂等与单项成绩保留事务
│   │   ├── repositories/                # 数据访问层：对应 Mapper，不提交业务事务
│   │   │   ├── __init__.py               # 数据访问层包标识
│   │   │   ├── user_repository.py        # 用户查询和保存
│   │   │   ├── session_repository.py     # 会话查询、保存、注销与过期分批删除
│   │   │   ├── forum_repository.py       # 当前锁定读、有限游标、作者/点赞关联及通知SQL
│   │   │   ├── progression_repository.py # 当前锁定读、有限列表与固定顺序用户锁
│   │   │   └── ranking_repository.py     # 用户行锁、进度/成绩读写、保留与榜单分页 SQL
│   │   ├── models/                      # 模型层：数据库实体和接口数据结构
│   │   │   ├── __init__.py               # 模型层包标识
│   │   │   ├── entities/                # ORM 数据库实体，不自动建表
│   │   │   │   ├── __init__.py           # 注册用户、会话、排行榜及论坛实体映射
│   │   │   │   ├── user.py               # 用户实体
│   │   │   │   ├── auth_session.py       # 账号会话实体
│   │   │   │   ├── forum.py              # 帖子、评论、两类点赞与站内通知五表实体
│   │   │   │   ├── progression.py        # 关卡版本、尝试/快照、永久成长/资格/幂等凭据
│   │   │   │   ├── cosmetic.py           # 有限主题目录、永久权益与装配版本
│   │   │   │   ├── pk.py                 # 双人房间、成员、不可变提交和唯一占用
│   │   │   │   ├── matchmaking.py        # 有界匹配票及到达/过期索引
│   │   │   │   └── ranking.py            # 当前轮次、不可变通关快照与最佳摘要实体
│   │   │   └── schemas/                 # 请求 DTO 与脱敏响应模型
│   │   │       ├── __init__.py           # 接口模型包标识
│   │   │       ├── auth.py               # 登录输入、用户输出及登录结果
│   │   │       ├── avatar.py             # 仅接收清单有效编号的严格头像写入请求
│   │   │       ├── forum.py              # 文字长度/作者隔离、UUID幂等及已读边界DTO
│   │   │       ├── progression.py        # 正式尝试/终盘/外观严格DTO，不接收客户端奖励
│   │   │       ├── pk.py                 # 单一匹配池、准备和终盘严格DTO
│   │   │       └── ranking.py            # 严格挑战请求 DTO 和脱敏成绩/榜单响应模型
│   │   └── common/                      # 公共层：跨业务基础设施，不反向依赖业务
│   │       ├── __init__.py               # 公共层包标识
│   │       ├── config.py                 # 环境配置，保持读取 backend/.env
│   │       ├── game_catalog.py           # 版本化题库与公开元数据读取，不提前发题
│   │       ├── avatar_catalog.py         # 缓存共用清单编号并核验静态资源存在性
│   │       ├── database.py               # 实体基类、有界连接池和会话生命周期
│   │       ├── security.py               # Argon2id、token 摘要与 UTC 时间工具
│   │       ├── exceptions.py             # 公共业务异常及统一 HTTP 异常处理
│   │       ├── middleware.py             # 请求体上限、API安全响应头及本地静态缓存验证
│   │       └── concurrency.py            # 有界执行槽、线程池和取消时的资源保护
│   ├── migrations/                       # Flyway 版本化 SQL，执行后不可直接修改
│   │   ├── V1__create_auth_tables.sql     # 用户、会话与相关唯一/到期索引
│   │   ├── V2__create_ranking_tables.sql  # 当前轮次、成绩、最佳摘要及排序/去重索引
│   │   ├── V3__add_user_avatar.sql       # 用户预设头像编号，新老账号默认001
│   │   ├── V4__create_forum_tables.sql   # 文字论坛、点赞、站内通知及外键/去重/分页索引
│   │   ├── V5__create_progression_tables.sql # 正式尝试/成长/资格和冻结题库种子
│   │   ├── V6__create_cosmetic_tables.sql # 主题目录、永久权益与装配配置
│   │   ├── V7__create_pk_room_tables.sql  # 双人房间、成员、提交与用户占用
│   │   ├── V8__create_matchmaking_tickets.sql # 排队票及占用票据关联
│   │   ├── V9__index_game_history_retention.sql # 终态时间索引，支持有界清理
│   │   ├── V10__publish_mine_difficulties.sql # 扫雷五档原七项不可变关卡与独立奖励定义
│   │   ├── V11__expand_mine_board_choices.sql # 中等/困难/地狱新增六个矩形棋盘，不改旧定义
│   │   └── V12__publish_sudoku_difficulties.sql # 数独教学与四档各三题，保留历史定义
│   ├── deploy/                           # 与现有宝塔服务合并使用的部署模板
│   │   ├── server/                       # Linux 宝塔复用方案与离线部署包生成
│   │   │   ├── README.md                 # IP/HTTP 临时验收、迁移、网站配置和维护
│   │   │   ├── compose.yaml              # 宿主机网络 API 与一次性 Flyway
│   │   │   ├── configure.py              # 隐藏输入密码，生成私密配置并自动 URL 编码
│   │   │   └── build_release.py          # 构建 amd64 镜像并打包网页、迁移和配置模板
│   │   ├── docker/                       # 本机完整容器部署、说明与真实 HTTP 验证
│   │   │   ├── README.md                 # 启停、迁移、数据持久化及资源边界
│   │   │   ├── api.Dockerfile            # 非 root、单 worker API 镜像
│   │   │   ├── web.Dockerfile            # 单 worker Nginx 静态站点镜像
│   │   │   ├── nginx.conf                # 本机 HTTP 站点、缓存和登录限流
│   │   │   ├── proxy.inc                 # 容器 API 代理与可信客户端头
│   │   │   └── verify_docker.py          # 本机真实 MySQL HTTP 与重建持久化验收
│   │   ├── nginx-http.conf.example       # http 级登录限流区
│   │   ├── nginx-site.conf.example       # HTTPS 站点静态资源与 API 路由
│   │   ├── nginx-proxy.conf.example      # 两个 API 路由共用的本机反向代理参数
│   │   ├── jobless-auth.service.example  # 可选单 worker systemd 服务
│   │   └── logrotate.conf.example        # 可选日志轮转，避免与宝塔重复配置
│   └── tests/                            # 后端安全、资源及真实数据库联调测试
│       ├── test_static_cache.py          # 页面/模块/样式缓存验证、304及两套Nginx策略契约
│       ├── test_auth.py                  # 真实哈希与数据库替身单元/API 测试
│       ├── test_avatar.py                # 头像存储、严格编号/来源/体积、账号隔离和三个分榜跟随
│       ├── test_mysql_integration.py     # 专用 MySQL/Flyway、登录/排行/论坛V4并发和外键联调
│       ├── test_forum.py                 # 论坛权限、文字/请求体、幂等、归属、通知及事务回滚
│       ├── test_game_content.py          # 题库唯一解、评分边界、无死锁与初级难度
│       ├── test_sudoku_content.py        # 数独唯一性、真实技巧分级和伪造推理拒绝
│       ├── test_sudoku_api.py            # 数独13题判题、教学、暂停、奖励及资格隔离
│       ├── test_mine_redesign.py         # 五档矩形扫雷、教学步骤、首击安全、经验补差及冻结时间
│       ├── test_mine_pause.py            # 服务器暂停/继续、防重版本、账号隔离及有效时长结算
│       ├── test_progression_v1.py        # 尝试/成长/资格/主题/版本/权限及回滚契约
│       ├── test_pk_v1.py                 # 房间/匹配/平局/资格组合/超时及容量边界
│       ├── test_pk_events.py             # 有界队列、单账号流与鉴权后DB释放
│       ├── test_game_cleanup.py          # 历史墓碑/回收不删除永久权益
│       ├── test_pk_probe.py              # 本地HTTP/SSE观测工具烟测
│       └── test_ranking.py               # 排名、保留集合、独立关卡、事务及挑战 API 回归
│
├── docs/                                 # 实施计划、设计说明等项目文档
│   ├── game-progression-openapi.json       # 当前v1路径与严格DTO的OpenAPI契约草案
│   ├── game-progression-pk-report.md       # 成长/资格/房间匹配实现证据及环境验收边界
│   ├── game-progression-pk-plan.md         # RESTful关卡成长/主题/房间匹配方案、数据契约及2核2GB验收
│   ├── frontend-structure-plan.md         # 已授权的目录整改范围、步骤与验收
│   ├── frontend-structure-report.md       # 目录迁移、测试基线与浏览器/打包证据
│   ├── frontend-refactor-plan.md          # 已确认的多页前端模块化、缓存与请求层重构计划
│   ├── frontend-refactor-report.md        # 重构产出、测试统计、环境待验收及发布回退说明
│   ├── mine-multilevel-mvp-plan.md         # 扫雷MVP与已确认的三尺寸九关扩展/兼容验收计划
│   ├── mine-multilevel-mvp-report.md       # MVP实际效果、测试统计、预览地址与边界说明
│   ├── mine-difficulty-redesign-plan.md    # 已确认的扫雷五档、教学、矩形棋盘及账号奖励计划
│   ├── mine-difficulty-redesign-report.md  # 扫雷重制效果、验收统计、本地预览及发布条件
│   ├── sudoku-implementation-plan.md       # 数独五档13关、推理分级、参考图界面及计时成长待确认计划
│   ├── login-implementation-plan.md       # 登录功能、数据库迁移及低资源部署计划
│   ├── login-implementation-report.md     # 实际产出、测试统计与待完成环境验收
│   ├── ranking-implementation-plan.md     # 已确认的逐关挑战、开发通关及排行榜实施计划
│   ├── ranking-implementation-report.md   # 排行榜实际产出、测试与待完成环境验收
│   ├── avatar-implementation-plan.md      # 用户确认的25张硬盘预设头像、账号及四榜实施计划
│   ├── avatar-implementation-report.md    # 头像实际行为、资源、测试及待完成MySQL/服务器验收
│   ├── forum-implementation-plan.md       # 文字论坛需求、技术选型、接口/数据设计与实施计划
│   └── forum-implementation-report.md     # 论坛实际产出、测试统计与MySQL/服务器待验收项
│
├── frontend/                             # 多页HTML、原生模块与按用途分类的样式/测试
│   ├── assets/  # 图片、音频及版本化扫雷/头像素材（URL保持不变）
│   │   └── 图片/音频/avatars/v1/minesweeper/v2等  # 原有素材路径保持
│   ├── src/  # 模块化前端代码
│   │   ├── features/  # 按业务归档的账号/音频/论坛等能力
│   │   │   ├── account/  # 登录、头像、档案与账号接口
│   │   │   │   ├── auth.js  # 登录/头像/设置/通知装配
│   │   │   │   ├── avatar-picker.js  # 头像选择窗口
│   │   │   │   ├── avatar.js  # 头像URL与选择状态
│   │   │   │   ├── client.js  # 所属业务的同源接口访问
│   │   │   │   ├── profile.js  # 服务器成长显示及权威结算同步
│   │   │   │   └── validation.js  # 用户名和密码校验
│   │   │   ├── audio/  # 背景/胜利音、偏好及设置窗口
│   │   │   │   ├── dialog.js  # 音频设置窗口
│   │   │   │   ├── music.js  # 背景/胜利音生命周期
│   │   │   │   └── settings.js  # 音量及音效偏好存储
│   │   │   ├── forum/  # 正文、讨论、接口与展示
│   │   │   │   ├── client.js  # 所属业务的同源接口访问
│   │   │   │   ├── discussion.js  # 评论/回复/编辑器与分页
│   │   │   │   └── view.js  # 论坛节点与正文安全展示
│   │   │   ├── notifications/  # 可见性轮询、站内消息与账号隔离
│   │   │   │   └── controller.js  # 所属业务/游戏控制器与生命周期
│   │   │   ├── pk/  # 竞速事件订阅与重连
│   │   │   │   └── events.js  # 共享事件或竞速SSE订阅
│   │   │   ├── progression/  # 正式成长请求与账号草稿存储
│   │   │   │   ├── client.js  # 所属业务的同源接口访问
│   │   │   │   └── journey-store.js  # 按账号、尝试与版本保存草稿
│   │   │   └── ranking/  # 排行榜读取和个人通关记录
│   │   │       ├── client.js  # 所属业务的同源接口访问
│   │   │       └── personal-records.js  # 本人最佳及最近三次通关
│   │   ├── games/  # 当前游戏规则与棋盘
│   │   │   ├── akari/  # 照明规则
│   │   │   │   └── rules.js  # 所属游戏规则算法
│   │   │   ├── mine/  # 扫雷会话、控制器、星级汇聚及爆炸音效
│   │   │   │   ├── controller.js  # 所属业务/游戏控制器与生命周期
│   │   │   │   ├── effects.js  # 爆炸顺序、时间线与音效
│   │   │   │   ├── session.js  # 正式扫雷会话，legacy内为旧三关计时
│   │   │   │   └── stars.js  # 可得星级、历史星与新增星汇聚
│   │   │   ├── sudoku/  # 数独规则与笔记
│   │   │   │   └── rules.js  # 所属游戏规则算法
│   │   │   ├── catalog.js  # 三游戏元数据及稳定导航地址
│   │   │   └── formal-board.js  # 正式照明/数独/竞速棋盘
│   │   ├── legacy/  # 已下线单关/九关练习，当前HTML不可导入
│   │   │   ├── game/  # 旧三关会话、控制器、存档与幂等挑战
│   │   │   │   ├── akari-controller.js
│   │   │   │   ├── challenge-client.js
│   │   │   │   ├── controller.js  # 所属业务/游戏控制器与生命周期
│   │   │   │   ├── dev-quick-complete.js
│   │   │   │   ├── home.js  # 当前首页入口（legacy内同名为旧首页工厂）
│   │   │   │   ├── progress-coordinator.js
│   │   │   │   ├── progress.js
│   │   │   │   ├── result-dialog.js
│   │   │   │   ├── session.js  # 正式扫雷会话，legacy内为旧三关计时
│   │   │   │   ├── sudoku-controller.js
│   │   │   │   ├── sudoku-answer.js       # 历史验收答案隔离，正式页面不导入
│   │   │   │   └── ui.js
│   │   │   ├── mine/  # 扫雷会话、控制器、星级汇聚及爆炸音效
│   │   │   │   ├── controller.js  # 所属业务/游戏控制器与生命周期
│   │   │   │   ├── levels.js
│   │   │   │   ├── practice-controller.js
│   │   │   │   ├── practice-page.js
│   │   │   │   ├── practice-store.js
│   │   │   │   └── rules.js  # 所属游戏规则算法
│   │   │   ├── README.md  # 所属目录用途和维护约定
│   │   │   ├── auth-game.js
│   │   │   └── auth-page.js
│   │   ├── pages/  # 当前HTML页面入口与装配
│   │   │   ├── forum-post.js  # 帖子详情页面入口
│   │   │   ├── forum.js  # 论坛列表页面入口
│   │   │   ├── home.js  # 当前首页入口（legacy内同名为旧首页工厂）
│   │   │   ├── journey.js  # 当前选关页与扫雷装配
│   │   │   ├── pk.js  # 竞速房间/匹配页面入口
│   │   │   └── ranking.js  # 三个独立分榜页面入口
│   │   ├── shared/  # 无业务反向依赖的DOM/HTTP/事件/生命周期/时间/UUID
│   │   │   ├── dom.js  # DOM语义名称查询
│   │   │   ├── events.js  # 共享事件或竞速SSE订阅
│   │   │   ├── http.js  # 同源JSON、超时、keepalive及错误适配
│   │   │   ├── lifecycle.js  # 监听/计时器/订阅统一清理
│   │   │   ├── request-id.js  # 安全UUID及HTTP环境回退
│   │   │   └── time.js  # 公共时间格式化
│   │   └── main.js  # 旧模块URL兼容入口，当前HTML不直接引用
│   ├── styles/  # 样式装配、组件、页面与历史样式
│   │   ├── components/  # 按原级联顺序拆分的公共组件及响应式样式
│   │   │   ├── account.css  # 所属页面/组件样式，声明顺序保留
│   │   │   ├── forum.css  # 所属页面/组件样式，声明顺序保留
│   │   │   ├── layout.css  # 所属页面/组件样式，声明顺序保留
│   │   │   ├── legacy-games.css  # 所属页面/组件样式，声明顺序保留
│   │   │   ├── navigation.css  # 所属页面/组件样式，声明顺序保留
│   │   │   ├── personal-records.css  # 所属页面/组件样式，声明顺序保留
│   │   │   ├── ranking.css  # 所属页面/组件样式，声明顺序保留
│   │   │   ├── responsive.css  # 所属页面/组件样式，声明顺序保留
│   │   │   └── settings-avatar.css  # 所属页面/组件样式，声明顺序保留
│   │   ├── legacy/  # 已下线单关/九关练习，当前HTML不可导入
│   │   │   └── mine-practice.css  # 所属页面/组件样式，声明顺序保留
│   │   ├── pages/  # 当前HTML页面入口与装配
│   │   │   ├── journey.css  # 所属页面/组件样式，声明顺序保留
│   │   │   └── mine.css  # 所属页面/组件样式，声明顺序保留
│   │   └── base.css  # 按原声明顺序装配8段公共样式
│   ├── test/  # 按功能分组的Node行为及结构契约
│   │   ├── features/  # 按业务归档的账号/音频/论坛等能力
│   │   │   ├── account/  # 登录、头像、档案与账号接口
│   │   │   │   ├── auth.test.js  # 所属模块的行为回归测试
│   │   │   │   ├── avatar.test.js  # 所属模块的行为回归测试
│   │   │   │   └── player-profile.test.js  # 所属模块的行为回归测试
│   │   │   ├── audio/  # 背景/胜利音、偏好及设置窗口
│   │   │   │   ├── audio-settings.test.js  # 所属模块的行为回归测试
│   │   │   │   └── music.test.js  # 所属模块的行为回归测试
│   │   │   ├── forum/  # 正文、讨论、接口与展示
│   │   │   │   ├── forum-body.test.js  # 所属模块的行为回归测试
│   │   │   │   └── forum.test.js  # 所属模块的行为回归测试
│   │   │   ├── notifications/  # 可见性轮询、站内消息与账号隔离
│   │   │   │   └── notifications.test.js  # 所属模块的行为回归测试
│   │   │   ├── progression/  # 正式成长请求与账号草稿存储
│   │   │   │   └── progression-client.test.js  # 所属模块的行为回归测试
│   │   │   └── ranking/  # 排行榜读取和个人通关记录
│   │   │       └── personal-records.test.js  # 所属模块的行为回归测试
│   │   ├── fixtures/  # 冻结历史DOM及CSS顺序基线，仅测试，不发布
│   │   │   ├── css-baseline.json  # 搬迁前CSS规则和顺序哈希
│   │   │   └── legacy-game.html  # 无脚本的旧首页DOM测试夹具
│   │   ├── games/  # 当前游戏规则与棋盘
│   │   │   ├── akari/  # 照明规则
│   │   │   │   ├── akari-instance.test.js  # 所属模块的行为回归测试
│   │   │   │   └── akari.test.js  # 所属模块的行为回归测试
│   │   │   ├── mine/  # 扫雷会话、控制器、星级汇聚及爆炸音效
│   │   │   │   ├── mine-effects.test.js  # 所属模块的行为回归测试
│   │   │   │   ├── mine-session.test.js  # 所属模块的行为回归测试
│   │   │   │   └── mine-stars.test.js  # 所属模块的行为回归测试
│   │   │   ├── sudoku/  # 数独规则与笔记
│   │   │   │   ├── sudoku.test.js  # 所属模块的行为回归测试
│   │   │   │   └── sudoku-variant.test.js  # 可变尺寸、笔记边界和无内置答案判题
│   │   │   └── game-catalog.test.js  # 所属模块的行为回归测试
│   │   ├── legacy/  # 已下线单关/九关练习，当前HTML不可导入
│   │   │   ├── completion.test.js  # 所属模块的行为回归测试
│   │   │   ├── controller-contracts.test.js  # 所属模块的行为回归测试
│   │   │   ├── game.test.js  # 所属模块的行为回归测试
│   │   │   ├── mine-levels.test.js  # 所属模块的行为回归测试
│   │   │   ├── progress.test.js  # 所属模块的行为回归测试
│   │   │   ├── ranking-client.test.js  # 所属模块的行为回归测试
│   │   │   └── session.test.js  # 所属模块的行为回归测试
│   │   ├── shared/  # 无业务反向依赖的DOM/HTTP/事件/生命周期/时间/UUID
│   │   │   ├── dom-events.test.js  # 所属模块的行为回归测试
│   │   │   └── http.test.js  # 所属模块的行为回归测试
│   │   └── structure.test.js  # 所属模块的行为回归测试
│   ├── README.md  # 所属目录用途和维护约定
│   ├── favicon.ico
│   ├── forum-post.html  # 独立页面入口，URL保持不变
│   ├── forum.html  # 独立页面入口，URL保持不变
│   ├── index.html  # 首页，页面URL保持不变
│   ├── journey.css  # 旧URL兼容入口
│   ├── journey.html  # 选关与扫雷游戏，页面URL保持不变
│   ├── mine-journey.css  # 旧URL兼容入口
│   ├── mine-practice.css  # 旧URL兼容入口
│   ├── mine-practice.html  # 旧练习地址跳转新版扫雷
│   ├── navigation.css  # 旧URL兼容入口
│   ├── package.json  # Node内置测试命令，无构建依赖
│   ├── pk.html  # 独立页面入口，URL保持不变
│   ├── ranking-akari.html  # 独立页面入口，URL保持不变
│   ├── ranking-mine.html  # 独立页面入口，URL保持不变
│   ├── ranking-sudoku.html  # 独立页面入口，URL保持不变
│   ├── ranking.html  # 独立页面入口，URL保持不变
│   └── styles.css  # 旧URL兼容入口
│
├── source/                               # 原始素材和将其转换为网页资源的处理脚本
│   ├── frontend/                         # 一次性目录整改工具，非网页运行代码
│   │   └── reorganize.py                 # 映射迁移、相对URL重写、旧挑战隔离及CSS基线生成
│   ├── audio/                            # 原始音频与裁剪处理脚本
│   │   ├── 爆炸声.flac                   # 爆炸音效原始文件
│   │   ├── backmusic-卡农（经典钢琴版）.ncm # 备用原始素材，未接入网页播放
│   │   ├── backmusic-墨澜音 - 阿尔法脑波音乐 (记忆力提升).ncm # 原始加密封装，网页不直接使用
│   │   ├── backmusic-墨澜音 - 阿尔法脑波音乐 (记忆力提升).mp3 # 用户补充的可播放背景原始素材
│   │   ├── 花亦落心亦冷 - PVZ胜利音效.mp3 # 开始结算时使用的胜利音效原始素材
│   │   └── prepare_explosion.py           # 裁剪、淡出并输出网页音效
│   └── imge/                             # 原始图片与图片提取脚本；保留现有目录拼写
│       ├── start.jpeg                    # 海岛入口原始图片
│       ├── 扫雷.jpeg                     # 扫雷原始图片
│       ├── minesweeper-theme.png          # 用户最新指定的扫雷主题原图，保留不覆盖
│       ├── prepare_mine_theme.py          # 从指定原图裁切九张v2 WebP棋格/入口素材
│       ├── 灯泡.png                      # 灯泡原始图片
│       ├── avatar/                       # 用户提供的25张原始PNG头像，保留编号及原图
│       │   └── *.png                     # 001至025原图
│       ├── prepare_avatars.py            # 开发机生成128px WebP、共用清单及可选联系表
│       └── extract_minesweeper.py         # 提取、处理扫雷格子素材
│
└── artifacts/                            # 验证过程产生的截图、日志与辅助检查材料
    ├── server-deploy/                    # 离线服务器部署 ZIP、校验文件及兼容性验证日志；不提交
    ├── backend/                          # 后端测试和可选真实 MySQL/Flyway 日志
    │   └── *.log                         # 完整测试输出；不纳入版本管理
    └── frontend/                         # 前端浏览器验证脚本和验证产物
        ├── verify_login.py               # 早期登录验收材料；当前关卡回归使用 verify_ranking.py
        ├── verify_ranking.py             # 临时数据库与真实浏览器：独立关卡/结算、开发按钮及三个分榜
        ├── verify_http_start.py          # 非安全 HTTP 浏览器环境下真实登录、开局重试与重新开始
        ├── verify_akari_completion.py     # 照明通关及结果界面验证脚本
        ├── verify_settlement.py          # 三关完成、祝贺与结算流程验证脚本
        ├── verify_live_timers.py         # 游戏实时计时显示验证脚本
        ├── verify_progress.py            # 数独笔记、首页续玩、规则计时、手机布局与刷新/退出恢复验证
        ├── verify_audio_settings.py      # 独立齿轮设置入口、音频音量、跨页与手机/键盘验证
        ├── verify_avatars.py             # 真实临时API/Chrome：25图、保存/失败、棋局保持、四榜及窄屏
        ├── verify_forum.py               # 双账号真实论坛/消息、键盘/手机、跨浏览器及游戏续玩
        ├── verify_refactor.py            # 真实HTTP缓存/304/206、跨页/重启续玩、计时及爆炸卸载恢复
        ├── verify_game_progression.py     # 双Chrome正式成长/三项资格/主题/房间SSE与匹配验收
        ├── verify_game_catalog.py         # 新版三卡/空目录/成长/旧关卡下线/过渡及窄屏验收
        ├── verify_mine_redesign.py       # 五档扫雷真实浏览器/临时SQLite及隔离本地预览
        ├── verify_mine_stars.py          # 三颗星/时间降星/汇聚/手机操作及换号取消专项浏览器验收
        ├── verify_mine_pause.py          # 规则/选关/真实标签切换/离页暂停与继续、活动时长星级验收
        ├── verify_frontend_structure.py  # 整改前后同状态像素比对、三个分榜及新版入口/资源验收
        ├── verify_mine_practice.py        # 九关布雷/尺寸/续玩/计时、双向滚动/窄屏及身份隔离
        ├── *.png / *.gif                 # 桌面、手机、导航及游戏状态的截图与动图
        ├── *.log                         # 自动化测试和浏览器运行日志
        ├── chain-frames/                 # 扫雷连锁爆炸逐帧检查材料
        │   ├── frame-*.png               # 动画各阶段截图
        │   └── frames.json               # 逐帧检查数据
        └── __pycache__/                   # Python 自动生成的字节码缓存
            └── *.pyc                     # 验证脚本的编译缓存
```

## 同步维护要求

- 新增、删除、移动或重命名项目目录时，必须在同一次变更中更新本文，所有新增目录必须注释用途。
- 本文列出的文件发生增删、移动、重命名，或文件及目录职责改变时，必须同步调整对应条目。
- Git 内部元数据不展开；截图、日志、缓存与已按通配符合并的同类素材不逐个列出；新增产物类别或目录时仍须更新说明。
- 此树包含本地验证产物与预留空目录；Git 不记录空目录，`.gitignore` 排除的内容不会随仓库上传，验证脚本仍保留在版本管理中。
- 未创建的目录不得作为现有结构列出；预留空目录必须明确标注，不得表述为已实现的模块。
- 每次结构变更后核对实际目录与本文，更新日期；如影响预览、测试、部署或项目约束，同步更新 README 与对应文档。

原始素材位于 `source/`，网页加载素材位于 `frontend/assets/`，验证产物位于 `artifacts/`；三者用途不同。真实 MySQL/Flyway 和目标服务器资源验收状态以实施报告为准。
