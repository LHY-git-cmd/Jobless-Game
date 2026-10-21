"""作用：在 Linux 服务器交互生成 API/Flyway 配置，密码不进入命令行或聊天。

仅使用 Python 标准库，兼容 Alibaba Cloud Linux 3 系统 Python。
在部署包根目录运行 python3 configure.py，默认针对已有的本机宝塔数据库。
"""

import getpass
import json
import os
from pathlib import Path
from urllib.parse import quote


def write_private(path, content):
    """创建仅属主可读写的配置文件；已有文件由 main 提前拒绝覆盖。"""
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
        target.write(content)


def main():
    """隐藏读取数据库密码，HTTP 临时验收默认关闭 Secure Cookie。"""
    directory = Path(__file__).resolve().parent
    api_file, flyway_file = directory / ".env.api", directory / "flyway.toml"
    if api_file.exists() or flyway_file.exists():
        raise SystemExit("配置已存在，请先备份并移走 .env.api 与 flyway.toml，再重新配置。")
    database = input("数据库名 [jobless_game]: ").strip() or "jobless_game"
    user = input("数据库用户 [jobless_app]: ").strip() or "jobless_app"
    if not database.replace("_", "").isalnum() or any(ord(char) > 127 for char in database):
        raise SystemExit("数据库名仅允许 ASCII 字母、数字和下划线。")
    if not user or any(ord(char) < 32 for char in user):
        raise SystemExit("数据库用户名无效。")
    password = getpass.getpass("数据库密码（输入不显示）: ")
    if not password or any(ord(char) < 32 or ord(char) > 126 for char in password):
        raise SystemExit("请使用宝塔生成的 ASCII 可打印字符密码，支持符号和空格。")
    if password != getpass.getpass("再次输入数据库密码: "):
        raise SystemExit("两次密码不一致，未生成配置。")
    secure = input("已配置 HTTPS？[y/N]: ").strip().lower() in {"y", "yes"}
    url = "mysql+pymysql://{}:{}@127.0.0.1:3306/{}?charset=utf8mb4".format(
        quote(user, safe=""), quote(password, safe=""), database)
    api = "\n".join([
        "# 作用：服务器 API 私密配置；不要提交或发送文件内容。",
        "DATABASE_URL='" + url + "'",
        "COOKIE_SECURE=" + str(secure).lower(),
        "DEV_QUICK_COMPLETE_ENABLED=false", "DB_POOL_SIZE=3", "DB_MAX_OVERFLOW=0",
        "PROGRESSION_ENABLED=false", "COSMETICS_ENABLED=false", "PK_ROOMS_ENABLED=false", "MATCHMAKING_ENABLED=false",
        "LOGIN_HASH_CONCURRENCY=1", "",
    ])
    flyway = "\n".join([
        "# 作用：一次性 Flyway 迁移凭据；禁止 clean 和自动 baseline。",
        "[environments.default]",
        'url = "jdbc:mysql://127.0.0.1:3306/' + database + '?useSSL=false&serverTimezone=UTC"',
        "user = " + json.dumps(user),
        "password = " + json.dumps(password),
        "[flyway]", 'environment = "default"', 'locations = ["filesystem:/flyway/sql"]',
        "cleanDisabled = true", "baselineOnMigrate = false", "",
    ])
    write_private(api_file, api)
    write_private(flyway_file, flyway)
    print("已生成 .env.api 与 flyway.toml；密码未输出。")


if __name__ == "__main__":
    main()
