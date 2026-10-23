# 前端目录整改报告

日期：2026-10-22。按用户“按你的建议开始整改”实施，已完成本地迁移与验收，未部署生产或修改数据库。

## 结果与目录

HTML地址、API、游戏规则、素材路径、账号与存档键保持。没有引入框架、构建工具或运行依赖。当前HTML全部加载 `src/pages/`，代码按业务归档，测试与源代码对应。

```text
frontend/
├── *.html                      # 原有页面URL
├── assets/                     # 原有图片、音频与版本化素材
├── src/
│   ├── pages/                  # 首页、选关、论坛、详情、分榜、竞速入口
│   ├── features/
│   │   ├── account/            # 登录、校验、头像、档案
│   │   ├── audio/              # 音乐、音效偏好与设置窗口
│   │   ├── notifications/      # 站内消息及可见性轮询
│   │   ├── forum/              # 论坛接口、正文和讨论
│   │   ├── ranking/            # 分榜读取和个人记录
│   │   ├── progression/        # 正式资源传输和账号草稿
│   │   └── pk/                 # 事件订阅与重连
│   ├── games/
│   │   ├── mine/               # 控制器、会话、星级及爆炸音效
│   │   ├── akari/              # 照明规则
│   │   └── sudoku/             # 数独规则
│   ├── shared/                 # HTTP、DOM、事件、生命周期、时间与UUID
│   ├── legacy/                 # 已下线旧单关、九关练习及兼容实现
│   └── main.js                 # 旧URL兼容转接
├── styles/
│   ├── base.css                # 按原顺序装配8个公共样式分段
│   ├── components/             # 布局、响应式、账号、论坛等样式
│   ├── pages/                  # 选关、扫雷
│   └── legacy/                 # 旧练习样式
├── test/
│   ├── features/ games/ shared/ legacy/
│   ├── fixtures/               # 历史DOM及CSS基线，不发布
│   └── structure.test.js       # 入口、引用、依赖、CSS及发布边界
└── *.css                       # 旧URL的轻量样式转接
```

原 `src/` 根目录28个JS现在只保留一个兼容入口；旧 `game/`、`lib/`、`progression/`、`pk/` 的内容全部归到新目录。旧本地扫雷规则、三关控制器及挑战客户端单独放进legacy；当前HTML引用图不允许到达legacy。原生规则模块照明/数独保留可供正式/竞速复用。

真正公共的 `formatTime`、`createRequestId` 从旧会话/排行榜中抽到shared，避免竞速/论坛依赖旧业务实现。旧session/排行榜测试仍通过重导出保护原接口，旧ChallengeClient独立隔离。

## 测试基线和CSS

整改前118项117通过，唯一失败为历史completion测试读取当前首页已经移除的节点。新增无脚本的历史DOM夹具（来自已有Git历史 `af7f8be` 父版本），保留全部业务断言；该旧流程14项通过，没有skip。该夹具只用于测试，不恢复正式旧入口。

结构契约先观察到入口分散、shared缺失、CSS基线缺失及构建白名单不匹配等失败，再完成迁移。最终完整Node测试135项全部通过（原测试包含13个此前因父测试失败未执行的子测试，加4个结构契约），0失败、0跳过。

CSS拆分保持原声明和媒体查询的完整顺序；迁移只改变相对素材URL。SHA256基线按归一化URL校验公共样式整体、选关、扫雷、导航及旧练习样式；全部一致。没有在整改中调整UI布局或游戏玩法。原 `/styles.css`、`/journey.css` 等保留小型@import兼容，其中服务端主题响应继续使用 `/journey.css`，无需修改API。

## 验收证据

| 验收 | 结果 | 日志 |
| --- | --- | --- |
| 旧测试基线 | 原失败已用独立夹具修复，14项通过 | `structure-legacy-green.log` |
| 完整Node单元/结构 | 135通过、0失败 | `structure-final-unit.log` |
| 静态HTTP/缓存/304及部署模板 | 4通过 | `structure-static-final.log` |
| 扫雷13项/四档棋盘/原图/账号/手机 | 11组通过 | `structure-mine-browser.log` |
| 规则/离页/标签页暂停与结算 | 6组通过 | `structure-pause-browser.log` |
| 星级/汇聚/账号隔离/手机 | 8组通过 | `structure-stars-browser.log` |
| 论坛/消息/账号/手机/真实新扫雷续玩 | 19组通过 | `structure-forum-browser.log` |
| 双浏览器竞速房间/SSE/准备/匹配/刷新/退出 | 3组通过 | `structure-pk-browser.log` |
| 整改前后截图、三个分榜分页、其他游戏占位及旧URL | 12组通过 | `structure-visual-browser.log` |
| 独立Nginx镜像打包/资源/测试排除/HTTP缓存 | 通过 | `structure-docker-build.log`、`structure-docker-runtime.log` |

日志均位于忽略的 `artifacts/frontend/`。浏览器合计59组通过、无未捕获脚本异常；均用临时SQLite或只读夹具，未访问业务数据库。视觉对比使用整改前 `26bb1aa` 与当前代码，固定同一数据及减少动画：首页、扫雷选关、扫雷榜单在1440/375/320px共9对截图，像素差异全部为0。

既有论坛脚本曾假设旧首页还在，已将其“打开通知不破坏棋局”的场景切到当前正式扫雷，仍验证同一存档条目及刷新续玩。星级脚本的按钮位置断言更新为用户已确认的“棋盘下方”，未为迁移改动布局或弱化奖励断言。早期针对旧页面的历史浏览器脚本保留为参考，不计入当前验收。

## 发布与兼容

Docker构建白名单增加styles和旧CSS转接路径。镜像实际验收发现 `!frontend/*.html` 也可能重新纳入嵌套HTML夹具，因此新增显式排除 `frontend/test/**`、node_modules和package文件。重新构建后确认镜像不含测试目录，新入口与样式均存在；独立无网络Nginx容器使用本机占位API主机解析，nginx配置检查和三个新资源HTTP/Cache-Control通过。临时容器已移除，没有替换现有服务。

宝塔离线打包器原本递归复制frontend并排除test，继续适用；已核对新目录会被包含。没有生成完整离线镜像发布包，也没有上传或重启正式服务。发布时须成套部署HTML、src及styles，保留根CSS/main兼容转接，避免新旧模块混用；已打开页面须刷新。

独立本地预览仍为 `http://127.0.0.1:8002/journey.html?game_id=mine`，源代码和静态页面直接读取工作区，因此本次无需修改预览数据库或重启API。所有旧账号、成长、主题和存档保留。

维护约定见 `frontend/README.md` 与 `src/legacy/README.md`，完整树见PROJECT-TREE。一次性映射工具位于 `source/frontend/reorganize.py`，已完成后拒绝重复运行。后续新增功能按该结构放置，并运行结构契约以防根目录再次堆积。
