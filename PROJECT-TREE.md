# 项目目录树

更新日期：2026-10-21。以下按当前实际目录整理，每个文件夹均标注用途；截图、日志、缓存和同类素材按类型合并列示。

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
│   │   │   └── ranking_controller.py     # 挑战创建/重开/通关、个人记录与公开排行榜路由
│   │   ├── services/                    # 业务层：流程、事务与登录专属资源限制
│   │   │   ├── __init__.py               # 业务层包标识
│   │   │   ├── auth_service.py           # 注册/验证密码、会话业务及事务控制
│   │   │   ├── avatar_service.py         # 有界线程中认证和更新账号头像，管理事务
│   │   │   ├── forum_service.py          # 论坛幂等、频率、归属、点赞与通知原子事务
│   │   │   ├── auth_rules.py             # 用户名计数、账号键和密码长度规则
│   │   │   ├── login_limiter.py          # 有界单进程登录频率保护
│   │   │   └── ranking_service.py        # 独立关卡重开/通关、幂等与单项成绩保留事务
│   │   ├── repositories/                # 数据访问层：对应 Mapper，不提交业务事务
│   │   │   ├── __init__.py               # 数据访问层包标识
│   │   │   ├── user_repository.py        # 用户查询和保存
│   │   │   ├── session_repository.py     # 会话查询、保存、注销与过期分批删除
│   │   │   ├── forum_repository.py       # 当前锁定读、有限游标、作者/点赞关联及通知SQL
│   │   │   └── ranking_repository.py     # 用户行锁、进度/成绩读写、保留与榜单分页 SQL
│   │   ├── models/                      # 模型层：数据库实体和接口数据结构
│   │   │   ├── __init__.py               # 模型层包标识
│   │   │   ├── entities/                # ORM 数据库实体，不自动建表
│   │   │   │   ├── __init__.py           # 注册用户、会话、排行榜及论坛实体映射
│   │   │   │   ├── user.py               # 用户实体
│   │   │   │   ├── auth_session.py       # 账号会话实体
│   │   │   │   ├── forum.py              # 帖子、评论、两类点赞与站内通知五表实体
│   │   │   │   └── ranking.py            # 当前轮次、不可变通关快照与最佳摘要实体
│   │   │   └── schemas/                 # 请求 DTO 与脱敏响应模型
│   │   │       ├── __init__.py           # 接口模型包标识
│   │   │       ├── auth.py               # 登录输入、用户输出及登录结果
│   │   │       ├── avatar.py             # 仅接收清单有效编号的严格头像写入请求
│   │   │       ├── forum.py              # 文字长度/作者隔离、UUID幂等及已读边界DTO
│   │   │       └── ranking.py            # 严格挑战请求 DTO 和脱敏成绩/榜单响应模型
│   │   └── common/                      # 公共层：跨业务基础设施，不反向依赖业务
│   │       ├── __init__.py               # 公共层包标识
│   │       ├── config.py                 # 环境配置，保持读取 backend/.env
│   │       ├── avatar_catalog.py         # 缓存共用清单编号并核验静态资源存在性
│   │       ├── database.py               # 实体基类、有界连接池和会话生命周期
│   │       ├── security.py               # Argon2id、token 摘要与 UTC 时间工具
│   │       ├── exceptions.py             # 公共业务异常及统一 HTTP 异常处理
│   │       ├── middleware.py             # 请求体上限及 API 安全响应头
│   │       └── concurrency.py            # 有界执行槽、线程池和取消时的资源保护
│   ├── migrations/                       # Flyway 版本化 SQL，执行后不可直接修改
│   │   ├── V1__create_auth_tables.sql     # 用户、会话与相关唯一/到期索引
│   │   ├── V2__create_ranking_tables.sql  # 当前轮次、成绩、最佳摘要及排序/去重索引
│   │   ├── V3__add_user_avatar.sql       # 用户预设头像编号，新老账号默认001
│   │   └── V4__create_forum_tables.sql   # 文字论坛、点赞、站内通知及外键/去重/分页索引
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
│       ├── test_auth.py                  # 真实哈希与数据库替身单元/API 测试
│       ├── test_avatar.py                # 头像存储、严格编号/来源/体积、账号隔离和三个分榜跟随
│       ├── test_mysql_integration.py     # 专用 MySQL/Flyway、登录/排行/论坛V4并发和外键联调
│       ├── test_forum.py                 # 论坛权限、文字/请求体、幂等、归属、通知及事务回滚
│       └── test_ranking.py               # 排名、保留集合、独立关卡、事务及挑战 API 回归
│
├── docs/                                 # 实施计划、设计说明等项目文档
│   ├── login-implementation-plan.md       # 登录功能、数据库迁移及低资源部署计划
│   ├── login-implementation-report.md     # 实际产出、测试统计与待完成环境验收
│   ├── ranking-implementation-plan.md     # 已确认的逐关挑战、开发通关及排行榜实施计划
│   ├── ranking-implementation-report.md   # 排行榜实际产出、测试与待完成环境验收
│   ├── avatar-implementation-plan.md      # 用户确认的25张硬盘预设头像、账号及四榜实施计划
│   ├── avatar-implementation-report.md    # 头像实际行为、资源、测试及待完成MySQL/服务器验收
│   └── forum-implementation-report.md     # 论坛实际产出、测试统计与MySQL/服务器待验收项
│
├── frontend/                             # 可独立预览的网页前端及其测试
│   ├── favicon.ico                       # 用户海岛图片居中裁切的多尺寸浏览器标签图标
│   ├── index.html                        # 游戏入口、三关界面及游戏弹窗
│   ├── ranking.html                      # 排行榜默认入口，展示扫雷分榜及三个单项导航
│   ├── ranking-mine.html                 # 扫雷历史最佳通关排行
│   ├── ranking-akari.html                # 照明历史最佳通关排行
│   ├── ranking-sudoku.html               # 数独历史最佳通关排行
│   ├── forum.html                        # 正文列表、卡片下展开评论、直接回复及只填正文发布
│   ├── forum-post.html                   # 可收藏帖子正文、评论/两层回复及通知定位
│   ├── styles.css                        # 页面布局、海岛风格、棋盘及弹窗样式
│   ├── package.json                      # 前端项目元信息与 Node.js 测试命令
│   │
│   ├── src/                              # 浏览器运行的 JavaScript 源码
│   │   ├── main.js                       # 首页自由选关、独立重开/续玩、规则计时与单关结算
│   │   ├── game.js                       # 扫雷棋盘与规则逻辑
│   │   ├── akari.js                      # 照明题盘、灯光与通关判断
│   │   ├── sudoku.js                     # 数独题盘、正式答案/候选笔记、旧存档兼容与通关判断
│   │   ├── session.js                    # 各关独立开始/冻结/重开计时；不是账号登录会话
│   │   ├── progress.js                   # 按账号保存棋局/候选笔记、绝对计时起点及待确认请求
│   │   ├── audio-settings.js             # 音乐/音效独立开关、音量偏好持久化与订阅同步
│   │   ├── settings.js                   # 共享游戏设置：头像选择、音频开关/滑块和键盘焦点
│   │   ├── avatar.js                     # 固定图片路径、清单读取、错误回退及按账号隔离保存状态
│   │   ├── avatar-picker.js              # 设置中的头像网格、按需加载、明确保存和失败重试
│   │   ├── auth.js                       # 共享登录弹窗、会话恢复、用户名设置入口及退出
│   │   ├── auth-client.js                # 同源 Cookie API 客户端与错误处理
│   │   ├── auth-validation.js            # 与后端一致的用户名/密码校验
│   │   ├── auth-game.js                  # 首页三个独立关卡的登录拦截与授权续接
│   │   ├── auth-page.js                  # 排行榜共享登录及站内消息初始化
│   │   ├── forum-client.js               # 同源请求、码点校验、固定重试负载和账号响应隔离
│   │   ├── forum-view.js                 # 紧凑纯文本卡片、左评论数/右图标、红色拇指点赞及输入计数
│   │   ├── forum-page.js                 # 正文游标页、评论输入保留、发布模态和返回位置恢复
│   │   ├── forum-discussion.js           # 单帖限高/评论内滚动、单一两行回复框、纸飞机及草稿续接
│   │   ├── forum-post-page.js            # 主题详情、评论/回复分页、上下文定位及账号切换
│   │   ├── notifications.js              # 全站/游戏铃铛、已读边界、可见性轮询及失败退避
│   │   ├── mine-effects.js               # 扫雷连锁爆炸动画与音效控制
│   │   ├── ranking-client.js             # 同源请求、HTTP 兼容 UUID、挑战幂等负载及失败重试
│   │   ├── ranking-page.js               # 三个单项榜共享分页、反馈与玩家头像渲染
│   │   ├── personal-records.js           # 首页我的通关记录：分类、最佳/最近三次、账号隔离与刷新
│   │   ├── music.js                      # 背景/胜利音独立控制、实时音量、手势解锁与播放位置管理
│   │   └── dev-quick-complete.js          # 可移除的开发验收：只求解当前关合法终盘
│   │
│   ├── assets/                           # 网页直接加载的处理后静态素材
│   │   ├── favicon.png                   # 海岛方形图标的 180px PNG 预览
│   │   ├── island.webp                   # 桌面海岛背景
│   │   ├── island-mobile.webp            # 手机海岛背景
│   │   ├── minesweeper.webp              # 扫雷入口图
│   │   ├── bulb.webp                     # 照明入口图
│   │   ├── avatars/                      # 用户共用的硬盘预设头像，账号只保存编号
│   │   │   └── v1/                       # 版本化成品；修改内容后使用新版本路径
│   │   │       ├── catalog.json           # 前后端共用的25个有效编号和站内图片路径
│   │   │       └── *.webp                # 001至025，128px预设头像
│   │   ├── audio/                        # 网页使用的音频资源
│   │   │   ├── explosion.wav             # 裁剪处理后的爆炸音效
│   │   │   ├── background.mp3            # 用户提供的阿尔法脑波背景音乐，低音量循环播放
│   │   │   └── victory.mp3               # 用户指定的 PVZ 胜利音效；开始结算时播放一次
│   │   └── minesweeper/                  # 扫雷格子状态素材
│   │       └── *.webp                    # 覆盖格、打开格、旗帜、地雷、爆炸与数字图片
│   │
│   └── test/                             # Node.js 自动化测试，验证规则与页面流程
│       ├── game.test.js                  # 扫雷规则测试
│       ├── akari.test.js                 # 照明规则测试
│       ├── sudoku.test.js                # 数独规则、候选笔记独立性、编辑保护与旧存档兼容
│       ├── session.test.js               # 关卡计时与结算记录测试
│       ├── progress.test.js              # 存档往返、灯泡/候选笔记恢复、旧存档、计时与存储异常
│       ├── audio-settings.test.js        # 默认开启、独立音量、偏好持久化与存储异常
│       ├── mine-effects.test.js          # 爆炸顺序、动画、实时增益与静音停止测试
│       ├── auth.test.js                  # 登录规则、密码原样传递及 API 失败语义
│       ├── forum.test.js                 # 码点长度、冻结重试、点赞串行及旧账号成功/失败隔离
│       ├── forum-body.test.js            # 正文表单/链接、旧标题隐藏、左评论按钮及右侧图标交互
│       ├── notifications.test.js         # 浏览器计时器、登录/可见性、账号隔离及已读边界
│       ├── avatar.test.js                # 头像路径、清单错误、保存重试和退出/换号晚到响应隔离
│       ├── completion.test.js            # 自由选关、单关重开/结算、规则计时、退出恢复与保存回归
│       ├── ranking-client.test.js        # HTTP UUID、幂等负载、旧响应隔离及网络失败语义
│       ├── personal-records.test.js      # 个人记录分类、隐私隔离、失败重试与键盘切换
│       └── music.test.js                 # 音轨切换、独立音量/静音、同轮一次、播放拒绝与切页状态
│
├── source/                               # 原始素材和将其转换为网页资源的处理脚本
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
        ├── verify_audio_settings.py      # 用户名设置入口、真实音频音量、跨页偏好与手机/键盘验证
        ├── verify_avatars.py             # 真实临时API/Chrome：25图、保存/失败、棋局保持、四榜及窄屏
        ├── verify_forum.py               # 双账号真实论坛/消息、键盘/手机、跨浏览器及游戏续玩
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
