# 项目目录树

更新日期：2026-10-18。以下按当前实际目录整理，每个文件夹均标注用途；截图、日志、缓存和同类素材按类型合并列示。

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
├── backend/                              # FastAPI 登录、逐关挑战、排行榜、Flyway 与部署支持
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
│   │   │   └── ranking_controller.py     # 挑战创建/重开/通关、个人记录与公开排行榜路由
│   │   ├── services/                    # 业务层：流程、事务与登录专属资源限制
│   │   │   ├── __init__.py               # 业务层包标识
│   │   │   ├── auth_service.py           # 注册/验证密码、会话业务及事务控制
│   │   │   ├── auth_rules.py             # 用户名计数、账号键和密码长度规则
│   │   │   ├── login_limiter.py          # 有界单进程登录频率保护
│   │   │   └── ranking_service.py        # 逐关资格、幂等、总榜快照与成绩保留事务
│   │   ├── repositories/                # 数据访问层：对应 Mapper，不提交业务事务
│   │   │   ├── __init__.py               # 数据访问层包标识
│   │   │   ├── user_repository.py        # 用户查询和保存
│   │   │   ├── session_repository.py     # 会话查询、保存、注销与过期分批删除
│   │   │   └── ranking_repository.py     # 用户行锁、进度/成绩读写、保留与榜单分页 SQL
│   │   ├── models/                      # 模型层：数据库实体和接口数据结构
│   │   │   ├── __init__.py               # 模型层包标识
│   │   │   ├── entities/                # ORM 数据库实体，不自动建表
│   │   │   │   ├── __init__.py           # 注册用户、会话和排行榜实体关系映射
│   │   │   │   ├── user.py               # 用户实体
│   │   │   │   ├── auth_session.py       # 账号会话实体
│   │   │   │   └── ranking.py            # 当前轮次、不可变通关快照与最佳摘要实体
│   │   │   └── schemas/                 # 请求 DTO 与脱敏响应模型
│   │   │       ├── __init__.py           # 接口模型包标识
│   │   │       ├── auth.py               # 登录输入、用户输出及登录结果
│   │   │       └── ranking.py            # 严格挑战请求 DTO 和脱敏成绩/榜单响应模型
│   │   └── common/                      # 公共层：跨业务基础设施，不反向依赖业务
│   │       ├── __init__.py               # 公共层包标识
│   │       ├── config.py                 # 环境配置，保持读取 backend/.env
│   │       ├── database.py               # 实体基类、有界连接池和会话生命周期
│   │       ├── security.py               # Argon2id、token 摘要与 UTC 时间工具
│   │       ├── exceptions.py             # 公共业务异常及统一 HTTP 异常处理
│   │       ├── middleware.py             # 请求体上限及 API 安全响应头
│   │       └── concurrency.py            # 有界执行槽、线程池和取消时的资源保护
│   ├── migrations/                       # Flyway 版本化 SQL，执行后不可直接修改
│   │   ├── V1__create_auth_tables.sql     # 用户、会话与相关唯一/到期索引
│   │   └── V2__create_ranking_tables.sql  # 当前轮次、成绩、最佳摘要及排序/去重索引
│   ├── deploy/                           # 与现有宝塔服务合并使用的部署模板
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
│       ├── test_mysql_integration.py     # 专用 MySQL/Flyway、真实登录与排行并发联调
│       └── test_ranking.py               # 排名、保留集合、快照、事务及挑战 API 回归
│
├── docs/                                 # 实施计划、设计说明等项目文档
│   ├── login-implementation-plan.md       # 登录功能、数据库迁移及低资源部署计划
│   ├── login-implementation-report.md     # 实际产出、测试统计与待完成环境验收
│   ├── ranking-implementation-plan.md     # 已确认的逐关挑战、开发通关及排行榜实施计划
│   └── ranking-implementation-report.md   # 排行榜实际产出、测试与待完成环境验收
│
├── frontend/                             # 可独立预览的网页前端及其测试
│   ├── favicon.ico                       # 用户海岛图片居中裁切的多尺寸浏览器标签图标
│   ├── index.html                        # 游戏入口、三关界面及游戏弹窗
│   ├── ranking.html                      # 完整三关总榜，可展开最佳轮次明细
│   ├── ranking-mine.html                 # 扫雷历史最佳通关排行
│   ├── ranking-akari.html                # 照明历史最佳通关排行
│   ├── ranking-sudoku.html               # 数独历史最佳通关排行
│   ├── forum.html                        # 论坛占位页面
│   ├── styles.css                        # 页面布局、海岛风格、棋盘及弹窗样式
│   ├── package.json                      # 前端项目元信息与 Node.js 测试命令
│   │
│   ├── src/                              # 浏览器运行的 JavaScript 源码
│   │   ├── main.js                       # 逐关解锁、通关保存、失败重试、规则与结算弹窗
│   │   ├── game.js                       # 扫雷棋盘与规则逻辑
│   │   ├── akari.js                      # 照明题盘、灯光与通关判断
│   │   ├── sudoku.js                     # 数独题盘、输入校验与通关判断
│   │   ├── session.js                    # 本轮关卡计时与结算记录；不是账号登录会话
│   │   ├── auth.js                       # 三页共享登录弹窗、会话恢复及退出
│   │   ├── auth-client.js                # 同源 Cookie API 客户端与错误处理
│   │   ├── auth-validation.js            # 与后端一致的用户名/密码校验
│   │   ├── auth-game.js                  # 第一关登录拦截与授权入口续接
│   │   ├── auth-page.js                  # 排行榜和论坛的登录初始化
│   │   ├── mine-effects.js               # 扫雷连锁爆炸动画与音效控制
│   │   ├── ranking-client.js             # 同源请求、HTTP 兼容 UUID、挑战幂等负载及失败重试
│   │   ├── ranking-page.js               # 四榜共享分页、反馈与原轮次明细渲染
│   │   ├── personal-records.js           # 首页我的通关记录：分类、最佳/最近三次、账号隔离与刷新
│   │   ├── music.js                      # 全站音乐开关、结算胜利音效、静音与播放位置管理
│   │   └── dev-quick-complete.js          # 可移除的开发验收：只求解当前关合法终盘
│   │
│   ├── assets/                           # 网页直接加载的处理后静态素材
│   │   ├── favicon.png                   # 海岛方形图标的 180px PNG 预览
│   │   ├── island.webp                   # 桌面海岛背景
│   │   ├── island-mobile.webp            # 手机海岛背景
│   │   ├── minesweeper.webp              # 扫雷入口图
│   │   ├── bulb.webp                     # 照明入口图
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
│       ├── sudoku.test.js                # 数独规则测试
│       ├── session.test.js               # 关卡计时与结算记录测试
│       ├── mine-effects.test.js          # 爆炸顺序、动画与声音控制测试
│       ├── auth.test.js                  # 登录规则、密码原样传递及 API 失败语义
│       ├── completion.test.js            # 逐关解锁、冻结计时、保存重试与开发通关回归
│       ├── ranking-client.test.js        # HTTP UUID、幂等负载、旧响应隔离及网络失败语义
│       ├── personal-records.test.js      # 个人记录分类、隐私隔离、失败重试与键盘切换
│       └── music.test.js                 # 音轨切换、同轮一次、静音、播放拒绝与切页状态
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
│       └── extract_minesweeper.py         # 提取、处理扫雷格子素材
│
└── artifacts/                            # 验证过程产生的截图、日志与辅助检查材料
    ├── backend/                          # 后端测试和可选真实 MySQL/Flyway 日志
    │   └── *.log                         # 完整测试输出；不纳入版本管理
    └── frontend/                         # 前端浏览器验证脚本和验证产物
        ├── verify_login.py               # 早期登录验收材料；当前逐关回归使用 verify_ranking.py
        ├── verify_ranking.py             # 临时数据库与真实浏览器：逐关、开发按钮及四榜验收
        ├── verify_http_start.py          # 非安全 HTTP 浏览器环境下真实登录、开局重试与重新开始
        ├── verify_akari_completion.py     # 照明通关及结果界面验证脚本
        ├── verify_settlement.py          # 三关完成、祝贺与结算流程验证脚本
        ├── verify_live_timers.py         # 游戏实时计时显示验证脚本
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
