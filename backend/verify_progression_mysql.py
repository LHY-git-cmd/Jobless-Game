"""作用：创建独立临时MySQL5.7测试容器，执行真实Flyway及联调，结束仅删除本脚本容器。

随机凭据只传子进程环境，不打印、不连接既有本地站点或生产库；最终只输出测试统计。
"""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
output = root / 'artifacts/backend'
output.mkdir(parents=True, exist_ok=True)
name = 'jobless-progression-qa-' + secrets.token_hex(4)
password = secrets.token_hex(20)
env = dict(os.environ, MYSQL_ROOT_PASSWORD=password)
listener = socket.socket(); listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]; listener.close()
wrapper = output / 'progression-flyway.cmd'
wrapper.write_text('@echo off\nrem 作用：仅将本轮独立测试库Flyway转到相同MySQL容器网络。\n'
    f'set "FLYWAY_URL=%FLYWAY_URL::{port}/=:3306/%"\nset "FLYWAY_LOCATIONS=filesystem:/flyway/sql"\n'
    f'docker run --rm --network container:{name} -v "{root / "backend/migrations"}:/flyway/sql:ro" '
    '-e FLYWAY_URL -e FLYWAY_USER -e FLYWAY_PASSWORD -e FLYWAY_LOCATIONS -e FLYWAY_CLEAN_DISABLED '
    '-e FLYWAY_BASELINE_ON_MIGRATE -e JAVA_ARGS redgate/flyway:13.6.0 %*\nexit /b %errorlevel%\n', encoding='utf-8')
created = False
with (output / 'progression-mysql57.log').open('w', encoding='utf-8') as log:
    try:
        result = subprocess.run(['docker', 'run', '-d', '--name', name, '-e', 'MYSQL_ROOT_PASSWORD', '-e',
            'MYSQL_DATABASE=jobless_auth_test_progression', '-p', f'127.0.0.1:{port}:3306', '--memory=512m',
            'mysql:5.7.40', '--character-set-server=utf8mb4', '--collation-server=utf8mb4_bin',
            '--innodb-buffer-pool-size=64M', '--performance-schema=OFF'], env=env, stdout=log, stderr=log)
        result.check_returncode(); created = True
        import pymysql
        for attempt in range(60):
            try:
                conn = pymysql.connect(host='127.0.0.1', port=port, user='root', password=password, connect_timeout=2)
                conn.close(); break
            except pymysql.MySQLError:
                time.sleep(1)
        else:
            raise RuntimeError('隔离MySQL未就绪')
        env.update(TEST_DATABASE_URL=f'mysql+pymysql://root:{password}@127.0.0.1:{port}/jobless_auth_test_progression?charset=utf8mb4',
                   TEST_FLYWAY_COMMAND=str(wrapper))
        # 可指定测试名，只复验有变更或尚未覆盖的功能，避免重复运行整套联调。
        targets = sys.argv[1:] or ['backend.tests.test_mysql_integration']
        result = subprocess.run([sys.executable, '-m', 'unittest', *targets], cwd=root, env=env, stdout=log, stderr=log)
        print('MySQL5.7/Flyway integration: ' + ('PASS' if result.returncode == 0 else 'FAIL (see artifacts/backend/progression-mysql57.log)'))
        sys.exit(result.returncode)
    finally:
        if created:
            subprocess.run(['docker', 'rm', '-f', '-v', name], stdout=log, stderr=log)
