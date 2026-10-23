"""作用：在开发机构建 linux/amd64 后端，打包服务器离线部署所需镜像和文件。

部署包不包含本机配置、密码、数据库数据或测试账号；输出到 Git 忽略的 artifacts/。
"""

import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def main():
    """构建镜像、保存应用及迁移镜像，并用明确白名单生成部署 ZIP。"""
    source = Path(__file__).resolve().parent
    root = source.parents[2]
    output = root / "artifacts" / "server-deploy"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "jobless-game-server.zip"
    subprocess.run([
        "docker", "build", "--platform", "linux/amd64", "-f",
        str(root / "backend/deploy/docker/api.Dockerfile"),
        "-t", "jobless-game-api:server", str(root),
    ], check=True)
    # 迁移工具同样离线携带，服务器不需要另装 Java 或拉取镜像。
    subprocess.run(["docker", "image", "inspect", "redgate/flyway:13.6.0"],
                   check=True, stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix="jobless-release-", dir=output) as temporary:
        staging = Path(temporary)
        subprocess.run([
            "docker", "image", "save", "-o", str(staging / "images.tar"),
            "jobless-game-api:server", "redgate/flyway:13.6.0",
        ], check=True)
        shutil.copytree(root / "frontend", staging / "frontend",
                        ignore=shutil.ignore_patterns("node_modules", "test", "package*.json", "__pycache__", ".env*"))
        shutil.copytree(root / "backend/migrations", staging / "migrations")
        for name in ["compose.yaml", "configure.py", "README.md"]:
            shutil.copyfile(source / name, staging / name)
        deploy = root / "backend/deploy"
        shutil.copyfile(deploy / "nginx-http.conf.example", staging / "nginx-http.conf.example")
        shutil.copyfile(deploy / "nginx-proxy.conf.example", staging / "nginx-proxy.conf")
        site = (deploy / "nginx-site.conf.example").read_text(encoding="utf-8")
        site = site.replace("HTTPS server {}", "HTTP 或 HTTPS server {}")
        site = site.replace("/backend/deploy/nginx-proxy.conf", "/nginx-proxy.conf")
        (staging / "nginx-site.conf.example").write_text(site, encoding="utf-8")
        # 临时 ZIP 写完后再替换正式产物，避免失败时留下半个部署包。
        pending = output / "jobless-game-server.pending.zip"
        with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(staging).as_posix())
        pending.replace(archive)
    digest = hashlib.sha256()
    with archive.open("rb") as package:
        for block in iter(lambda: package.read(1024 * 1024), b""):
            digest.update(block)
    checksum = digest.hexdigest()
    # 固定使用LF，避免Windows回车被Linux的sha256sum识别为文件名的一部分。
    (output / "jobless-game-server.zip.sha256").write_bytes(
        (checksum + "  " + archive.name + "\n").encode("ascii"))
    print("部署包: " + str(archive))
    print("大小: {:.1f} MiB".format(archive.stat().st_size / 1024 / 1024))
    print("SHA256: " + checksum)


if __name__ == "__main__":
    main()
