# 宝塔服务器快速部署

作用：仅常驻 Docker API，静态页面由已有宝塔 Nginx 提供，连接已有本机 MySQL。
目标环境是 Alibaba Cloud Linux 3、x86_64、Docker 26.1.3、Compose 2.27.0。
无域名阶段使用公网 IP 的 HTTP 地址临时验收；登录凭据会经过明文 HTTP，正式使用前应配置 HTTPS，并将 `.env.api` 的 `COOKIE_SECURE` 改为 `true` 后重建 API。

## 开发机打包

在项目根目录运行，完整构建输出写入日志，只查看结果或失败末尾：

```powershell
New-Item -ItemType Directory -Force artifacts/server-deploy | Out-Null
python backend/deploy/server/build_release.py *> artifacts/server-deploy/build.log
Get-Content artifacts/server-deploy/build.log -Tail 8
```

本机须有运行中的 Linux Docker 和 `redgate/flyway:13.6.0` 镜像。
输出为 `artifacts/server-deploy/jobless-game-server.zip` 和同名 `.sha256` 校验文件。
包内包含 API、Flyway 两个镜像、网页（含25张硬盘预设头像）、V1/V2/V3 迁移、Compose、交互配置脚本及 Nginx 模板。已有 V2 数据库先备份并执行 V3 用户头像迁移，再发布新后端和网页；V1/V2 原有文件保持不变。V3 本次尚未在目标 MySQL/Flyway 环境验收，详见 [头像实施报告](../../../docs/avatar-implementation-report.md)。
没有本机 `.env`、MySQL 数据、测试账号或原始素材；服务器不用构建镜像或安装 Python 项目依赖。

## 服务器首次启动

1. 在宝塔建立 `jobless_game` 数据库，用户 `jobless_app`，访问权限仅本机，字符集 `utf8mb4`。
   本文按新建空库部署；Flyway 的 `info` 若出现未知历史或其他业务表，先核实，不执行自动 baseline。
2. 上传 ZIP 与校验文件到服务器同一目录，执行 `sha256sum -c jobless-game-server.zip.sha256`。
   使用宝塔将 ZIP **内容直接解压**到 `/www/wwwroot/jobless-game`，使该目录直接包含 `compose.yaml`、`frontend/`、`images.tar` 等，不多套一层目录。
3. 在宝塔终端以 root 执行：

```bash
# 作用：导入离线镜像，交互填写宝塔数据库密码；没有域名时 HTTPS 选 N。
cd /www/wwwroot/jobless-game
docker image load -i images.tar
python3 configure.py
```

脚本自动 URL 编码密码，以 `0600` 权限生成 `.env.api`、`flyway.toml`，不会显示密码或覆盖已有配置。
数据库名及用户名按回车使用默认值；密码输入时终端不显示字符，需要输入两次。
`configure.py` 使用系统 Python 标准库，不用安装 pip 依赖。不要分享配置文件内容或完整的 `docker compose config` 输出。

4. 检查和执行迁移，再启动 API。按顺序执行，任何一步失败就停止并读取该步错误：

```bash
# 作用：只核验配置语法，不输出解析后的凭据。
docker compose config --quiet

# 作用：迁移前核对目标库，迁移完成后退出，不常驻运行 Java。
docker compose --profile tools run --rm migrate info
docker compose --profile tools run --rm migrate migrate
docker compose --profile tools run --rm migrate info

# 作用：启动唯一的常驻应用容器，健康检查会实际查询数据库。
docker compose up -d --no-build --wait --wait-timeout 90 api
docker compose ps
curl --fail http://127.0.0.1:8001/api/rankings/total?page_size=1
```

API 使用 Linux 宿主机网络，只监听 `127.0.0.1:8001`，数据库访问同样走 `127.0.0.1:3306`。
公网不需要开放 8001 或 3306；不要再用宝塔进程管理器启动第二个 API。
API 内存限制 320MiB；Flyway 内存限制 512MiB，两者均是上限而非实际占用。

## 宝塔网站

1. 宝塔 → 网站 → 添加站点，使用服务器公网 IP，网站根目录设为 `/www/wwwroot/jobless-game/frontend`；选择静态网站，不需要 PHP。
   若已有使用同一 IP 的站点，先核对宝塔默认站点及 `server_name`，避免将本游戏配置加到其他业务站点。
2. 将包内 `nginx-http.conf.example` 的一行限流区配置加入 Nginx 全局 `http {}`，只加一次。
3. 将 `nginx-site.conf.example` 合并到这个站点的 `server {}`，处理重复的 `root`、`index` 和 `location`。
   已为包内 `/www/wwwroot/jobless-game/nginx-proxy.conf` 配好路径。
4. 备份原配置，在宝塔检查 Nginx 配置，通过后重载；终端也可用 `/www/server/nginx/sbin/nginx -t` 检查。
5. 阿里云安全组与服务器防火墙允许网站 HTTP 80 端口，浏览器打开 `http://服务器公网IP/`。

API 必须经相同 IP、协议和端口的 `/api/` 调用，不要让浏览器直接请求 8001。
公网 HTTP 不提供 `crypto.randomUUID()`。当前前端已使用 `crypto.getRandomValues()` 兼容生成 UUID，
旧版遇到该错误时需更新 `frontend/index.html`、`frontend/src/main.js` 和 `frontend/src/ranking-client.js`，再重新加载页面。
有域名并配置 HTTPS 后保留宝塔证书配置，修改 `.env.api` 的 `COOKIE_SECURE=true`，再执行
`docker compose up -d --no-build --wait api`。公网 IP 的 HTTP 访问只用于临时验收。

## 验收、清理与更新

浏览器验证：首次登录创建账号、再次登录、刷新保持会话、退出、任意选关、单关通关保存与重开、单关结算、个人记录、三个单项榜。
开发一键通关始终关闭；不要将本机测试账号导入正式库。
记录启动前后 `free -m`、`docker stats --no-stream`、数据库连接数和错误日志；本机兼容性测试不代替目标服务器资源验收。

宝塔计划任务可每小时执行一次：

```bash
# 作用：有界分批清理过期会话，执行完退出。
cd /www/wwwroot/jobless-game
docker compose exec -T api python -m backend.cleanup_sessions --batch-size 500 --max-batches 10
```

Docker 日志已限制为每容器两个 5MiB 文件，网站日志使用宝塔现有轮转。
API 日志通过 `docker compose logs --tail 50 api` 查看；不要粘贴任何含凭据的自定义调试输出。

后续更新先备份数据库、旧镜像包、网页和私密配置。在维护窗口停止 API，导入新镜像并更新网页/迁移文件，
单次执行 Flyway 成功后启动 API 验收。解压新包时保留原 `.env.api` 和 `flyway.toml`，不重新运行配置脚本。
应用回退需配套原镜像和网页；已经执行的数据库迁移不会自动回退，必要时按备份恢复。
不运行 `docker compose down -v`，不修改共享 MySQL 的全局参数。

## MySQL 5.7 差异

目标 MySQL 为 5.7.40，原本机容器方案为 8.4.7。必须使用本包原始 SQL，不能为兼容改写已执行迁移文件。
MySQL 5.7 不执行 `CHECK` 约束，V2 的类别与总成绩快照一致性主要依赖应用校验；禁止绕过应用写入业务表。
Flyway 迁移通过不代表数据库行为完全相同，真实登录、并发提交及持久化结果应一并验收。
5.7 的生命周期状态与后续升级应另行规划，本部署包不会升级或替换宝塔共享 MySQL。

## 本机验证结果（2026-10-18）

- 独立 MySQL 5.7.40 容器成功执行原始 V1/V2，重复 migrate 后无 Pending。
- 既有四项真实 MySQL 集成测试通过，覆盖会话失效、账号竞争、并发重复通关和连接池超时。
- 新 Compose 的 API 启动命令、数据库健康检查及资源限制通过；Flyway TOML 配置实际连接成功。
- 包含 `@`、冒号、美元符号、单双引号、反斜杠和空格的 ASCII 数据库密码通过真实连接验证。
- 使用宿主机代理模板的 Nginx 完成 49 项 HTTP 验证，API 重建后完成 24 项持久化验证，均为 0 失败。
- Docker Desktop 验证通过共享独立测试容器网络模拟本机回环，未启用 Desktop 宿主机网络；目标 Linux 的宿主机网络、防火墙、SELinux、宝塔实际配置及资源峰值仍须服务器验收。
- 所有数据仅存在独立本机测试库中，不接触服务器数据库。详细日志位于被 Git 忽略的 `artifacts/server-deploy/`。
- 后续补充 HTTP UUID 修复：前端 50 项自动化测试通过；`artifacts/frontend/verify_http_start.py` 使用真正非安全的 HTTP 域名页面完成登录、开局失败重试及重新开始共 4 项验证，无未处理异常。HTTP 浏览器测试使用临时 SQLite，仅验证浏览器限制和交互，不替代前述 MySQL 验收。
