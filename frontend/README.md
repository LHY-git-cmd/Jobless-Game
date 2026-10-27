# 前端目录约定

保留多页HTML及原生ES Module，没有构建步骤；根目录HTML地址兼容现有链接，图片、音频继续使用 `assets/` 路径。

| 目录 | 用途与边界 |
| --- | --- |
| `src/pages/` | HTML直接加载的入口，连接DOM、身份与业务模块 |
| `src/features/` | 账号、音频、通知、论坛、排行榜、成长、竞速等业务能力 |
| `src/games/` | 当前游戏规则与棋盘；扫雷控制器/会话/星级/音效集中在mine |
| `src/shared/` | HTTP、DOM、事件、生命周期、格式化与请求ID，不反向引用业务 |
| `src/legacy/` | 已下线旧游戏与本地练习，仅作兼容及回归参考，当前入口不可导入 |
| `styles/` | base装配公共样式，components保留组件和响应式覆盖，pages放选关/扫雷样式 |
| `test/` | 按features/games/shared/legacy分类，fixtures只供测试 |

页面 → 业务/游戏 → 公共能力。页面入口不能互相导入；无业务的工具才能进入shared。`features/progression`由扫雷与竞速复用；其他业务之间的依赖必须有明确用途。

`src/main.js`与根目录五个CSS文件是旧URL兼容转接，新增页面直接引用 `src/pages/` 和 `styles/`。服务端已有主题响应仍引用 `/journey.css`，因此保留兼容地址，不增加重复样式实现。CSS拆分严格保持原声明和层叠顺序，`test/fixtures/css-baseline.json`保护搬迁前规则不变。

运行 `npm test` 执行全部测试，包含HTML入口、相对资源、legacy隔离、共享依赖、CSS顺序及Docker打包契约。不要用跳过测试代替修复夹具；新增页面与样式须检查窄屏及静态缓存。

完整过程见项目 `docs/frontend-structure-plan.md` 与 `docs/frontend-structure-report.md`。一次性迁移工具 `source/frontend/reorganize.py` 只适用于整改前结构，检测新目录后会拒绝重复运行。

竞技大厅入口为 `pk.html`，双方准备并倒计时结束后跳转 `pk-game.html?room=UUID`。两个pages入口调用 `features/pk/page.js`，由服务器快照驱动跳转、结算和再战。`games/arena-board.js` 复用闯关棋盘样式/素材及规则，竞技只保存本人草稿，不调用闯关体力、经验和星级接口。数独笔记及最近100步撤回可在同浏览器刷新恢复。跨页503读取最多重试三次，SSE被拒后有退避重建；业务写请求仍由用户重试与服务器幂等保护。

竞技对局内移除公共账号/体力/导航及大标题，时间置于棋盘标题右侧。三种棋盘按真实可用宽高首次完整适配；照明与数独完成后自动提交，完整草稿刷新后恢复提交。终盘网络错误有界退避重试并冻结原负载，连续失败后保留草稿，可点击现有刷新状态恢复。页面不再提供“提交解答”按钮；竞技大厅与闯关页面保持原有结构。
