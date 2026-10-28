# 无职游戏

手机端优先的网页解谜游戏，包含扫雷、照明和数独，支持闯关、星级与等级成长、双人竞技、排行榜和文字论坛。

前端使用 HTML / CSS / JavaScript，后端使用 Python + FastAPI，数据存储使用 MySQL，数据库迁移由 Flyway 管理。

## 克隆后快速启动

适合在自己电脑上体验和验证。Docker 会启动网页、API 和独立数据库，并自动执行数据库迁移，无需单独安装 Python、MySQL、Nginx 或前端依赖。

### 1. 准备环境并克隆仓库

安装 Git、Docker Engine 或 Docker Desktop，以及 Docker Compose v2。启动 Docker，Docker Desktop 请选择 Linux 容器模式；首次构建需要联网下载镜像和依赖。

```bash
# 下载仓库。
git clone https://github.com/LHY-git-cmd/Jobless-Game.git
# 进入项目根目录，后续命令均在此执行。
cd Jobless-Game
```

### 2. 准备本地配置

复制根目录的 `.env.docker.example` 为 `.env.docker`：

```bash
# Linux / macOS：复制配置模板。
cp .env.docker.example .env.docker
```

Windows PowerShell 使用：

```powershell
# Windows：复制配置模板。
Copy-Item .env.docker.example .env.docker
```

编辑 `.env.docker`，填写两个**不同的随机密码，每个至少 32 位十六进制字符**（仅使用 `0-9`、`a-f`），并将四个功能开关设为 `true`：

```dotenv
# 分别填写数据库管理员密码和应用密码，不能留空。
MYSQL_ROOT_PASSWORD=填写第一个随机十六进制密码
MYSQL_PASSWORD=填写第二个随机十六进制密码
# 本地 HTTP 访问使用以下配置。
COOKIE_SECURE=false
WEB_PORT=8080
# 开启闯关成长、主题、竞技房间和自动匹配。
PROGRESSION_ENABLED=true
COSMETICS_ENABLED=true
PK_ROOMS_ENABLED=true
MATCHMAKING_ENABLED=true
```

`.env.docker` 已被 Git 忽略，请保存在本机。默认模板的功能开关为 `false`，体验完整游戏前需要按上面修改。

### 3. 构建并启动

按顺序执行，配置检查通过后再启动：

```bash
# 检查配置是否完整，不输出密码。
docker compose --env-file .env.docker config --quiet
# 构建并启动服务，等待数据库迁移和健康检查完成。
docker compose --env-file .env.docker up -d --build --wait --wait-timeout 180
# 查看所有服务，包括执行完毕的迁移容器。
docker compose --env-file .env.docker ps -a
```

打开 [http://127.0.0.1:8080/](http://127.0.0.1:8080/)。首次拉取镜像和构建耗时较长；若等待超时，先查看下方日志，确认原因。

### 4. 验证是否可用

- **服务状态**：`mysql`、`api`、`web` 应为运行且健康；`migrate` 显示 `Exited (0)` 表示迁移成功，属于正常状态。
- **账号与闯关**：使用新用户名和密码登录会自动创建账号；进入扫雷、照明或数独的入门关，完成后检查星数和经验，刷新页面确认仍保持登录。
- **论坛**：发布一条测试帖子，刷新后确认仍可查看。
- **数据持久化**：执行下方停止命令，再重新执行启动命令，确认原账号、成长和帖子仍存在。
- **双人竞技（可选）**：账号达到 5 级后解锁。使用两个达到等级的账号，分别在两个浏览器或独立浏览器会话登录，邀请或匹配，双方准备后开始对局。

## 日常操作与排查

```bash
# 停止服务，保留数据库数据；重新启动使用上面的 up 命令。
docker compose --env-file .env.docker stop
# 启动失败时，查看各服务最近的日志。
docker compose --env-file .env.docker logs --tail 50 mysql migrate api web
```

- **8080 端口被占用**：修改 `.env.docker` 的 `WEB_PORT` 后重新启动，访问对应端口。
- **配置修改后未生效**：重新执行启动命令，让容器加载新配置。
- **已有数据库的密码错误**：修改 `.env.docker` 不会同步修改数据卷内的数据库密码；请保持与首次初始化时一致。
- **数据保存位置**：本地命名卷 `jobless-game-local_mysql_data`。`stop` 和不带 `-v` 的 `down` 会保留数据；`down -v` 会删除数据。

本方案仅监听本机地址，用于克隆后体验，不会连接作者或其他服务器的数据库。不要直接将它作为公网部署配置。

更多说明：[Docker 部署细节](./backend/deploy/docker/README.md) · [宝塔服务器部署](./backend/deploy/server/README.md) · [后端开发与部署](./backend/README.md) · [项目目录](./PROJECT-TREE.md) · [项目约束](./README-CONSTRAINTS.md)
