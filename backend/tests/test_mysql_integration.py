"""可选真实 MySQL/Flyway 联调：仅允许显式配置的专用测试库，不创建生产表或替代数据库。

设置 TEST_DATABASE_URL（MySQL SQLAlchemy URL，数据库名以 jobless_auth_test_ 开头）
和 TEST_FLYWAY_COMMAND（Flyway 可执行文件路径）后运行本模块；未配置时明确跳过。
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
from unittest import TestCase, skipUnless
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, inspect, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from backend.app import main
from backend.app.common.database import get_db
from backend.app.common.config import get_settings
from backend.app.common.exceptions import AppError
from backend.app.services import auth_service
from backend.app.services.login_limiter import LoginRateLimiter
from backend.app.models.entities import AuthSession, User
from backend.app.models.schemas.auth import LoginRequest
from backend.app.common.security import utc_now

ROOT = Path(__file__).resolve().parents[2]
TEST_URL = os.getenv("TEST_DATABASE_URL")
FLYWAY_COMMAND = os.getenv("TEST_FLYWAY_COMMAND")


@skipUnless(TEST_URL and FLYWAY_COMMAND, "未配置专用 TEST_DATABASE_URL 与 TEST_FLYWAY_COMMAND，真实 MySQL/Flyway 联调待完成")
class MySQLIntegrationTests(TestCase):
    """执行真实迁移、唯一键竞争、持久化会话和连接池超时。"""

    @classmethod
    def setUpClass(cls):
        """先核对专用测试库，再通过 Flyway 执行 SQL；不调用 ORM create_all。"""
        url = make_url(TEST_URL)
        if url.drivername != "mysql+pymysql" or not (url.database or "").startswith("jobless_auth_test_"):
            raise ValueError("只允许 mysql+pymysql 且数据库名以 jobless_auth_test_ 开头的专用测试库")
        cls.engine = create_engine(url, pool_size=3, max_overflow=0, pool_timeout=.2, connect_args={"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5})
        unexpected = set(inspect(cls.engine).get_table_names()) - {"users", "auth_sessions", "flyway_schema_history", "challenge_progress", "completion_records", "leaderboard_entries"}
        if unexpected:
            raise ValueError("测试库存在其他业务表，已停止")
        env = dict(os.environ)
        env.update({
            "FLYWAY_URL": f"jdbc:mysql://{url.host}:{url.port or 3306}/{url.database}?serverTimezone=UTC",
            "FLYWAY_USER": url.username or "",
            "FLYWAY_PASSWORD": url.password or "",
            "FLYWAY_LOCATIONS": f"filesystem:{(ROOT / 'backend/migrations').as_posix()}",
            "FLYWAY_CLEAN_DISABLED": "true",
            "FLYWAY_BASELINE_ON_MIGRATE": "false",
            "JAVA_ARGS": "-Xms32m -Xmx256m",
        })
        output_dir = ROOT / "artifacts/backend"
        output_dir.mkdir(parents=True, exist_ok=True)
        with (output_dir / "mysql-flyway.log").open("w", encoding="utf-8") as log:
            for action in ["migrate", "migrate", "info"]:
                result = subprocess.run([FLYWAY_COMMAND, "-outputType=json", action], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                log.write(result.stdout + result.stderr)
                if result.returncode:
                    raise AssertionError("Flyway 执行失败，详见本地 mysql-flyway.log；不要将凭据粘贴进报告")
                if action == "info":
                    data = json.loads(result.stdout)
                    if any(item.get("state") == "Pending" for item in data.get("migrations", [])):
                        raise AssertionError("Flyway 重跑后仍有 Pending 迁移")
        cls.sessions = sessionmaker(cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        """关闭测试连接池。"""
        cls.engine.dispose()

    def setUp(self):
        self.keys = []
        def test_db():
            with self.sessions() as db:
                yield db
        main.app.dependency_overrides[get_db] = test_db
        auth_service.rate_limiter = LoginRateLimiter(100, 60)
        self.client = TestClient(main.app, headers={"Origin": "http://testserver"})

    def tearDown(self):
        """只删除本用例创建的唯一测试账号；会话由外键级联删除。"""
        self.client.close()
        main.app.dependency_overrides.clear()
        with self.sessions() as db:
            db.execute(delete(User).where(User.username_key.in_(self.keys)))
            db.commit()

    def new_name(self):
        """生成满足 12 个字符上限的隔离测试账号。"""
        name = "qa" + uuid4().hex[:10]
        self.keys.append(name)
        return name

    def test_real_cookie_expiry_and_logout(self):
        name = self.new_name()
        response = self.client.post("/api/auth/login", json={"username": name, "password": " secret "})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["created"])
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        with self.sessions() as db:
            user = db.scalar(select(User).where(User.username_key == name))
            self.assertTrue(user.password_hash.startswith("$argon2id$"))
            db.execute(update(AuthSession).where(AuthSession.user_id == user.id).values(expires_at=utc_now() - timedelta(seconds=1)))
            db.commit()
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": name.upper(), "password": " secret "}).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_two_connections_race_on_case_insensitive_account(self):
        name = self.new_name()
        def login_once(display, password):
            with self.sessions() as db:
                try:
                    user, created, _, _ = auth_service.login_transaction(LoginRequest(username=display, password=password), db, get_settings())
                    return user.id, created
                except AppError as error:
                    self.assertEqual(error.status_code, 401)
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(login_once, name, "first-password")
            second = pool.submit(login_once, name.upper(), "other-password")
            outcomes = [first.result(), second.result()]
        self.assertEqual(sum(outcome is not None for outcome in outcomes), 1)
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(User).where(User.username_key == name)).all()), 1)

    def test_ranking_concurrent_retry_and_retention(self):
        """真实 InnoDB 用户锁使并发重复提交只记一次，V2 快照与保留规则可读。"""
        from backend.app.services import ranking_service
        from backend.app.models.schemas.ranking import StartRequest, CompleteRequest
        from backend.app.models.entities.ranking import CompletionRecord
        name = self.new_name()
        with self.sessions() as db:
            user, _, raw, _ = auth_service.login_transaction(LoginRequest(username=name, password="test-password"), db, get_settings())
            user_id = user.id
            state = ranking_service.start_transaction(raw, StartRequest(request_id=uuid4()), db)
        payload = CompleteRequest(category="mine", revision=0, attempt_id=state["levels"][0]["attempt_id"], duration_seconds=10)

        def submit():
            """每个并发写入独立使用会话，依赖真实行锁而非进程锁。"""
            with self.sessions() as db:
                return ranking_service.complete_transaction(raw, state["run_id"], payload, db, get_settings())

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(results[0], results[1])
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(CompletionRecord).where(CompletionRecord.user_id == user_id)).all()), 1)
            self.assertEqual(ranking_service.records_transaction(raw, "mine", db)["best"]["duration_seconds"], 10)
            for category, seconds in [("akari", 20), ("sudoku", 30)]:
                idx = ranking_service.GAMES.index(category)
                payload = CompleteRequest(category=category, revision=0, attempt_id=state["levels"][idx]["attempt_id"], duration_seconds=seconds)
                state = ranking_service.complete_transaction(raw, state["run_id"], payload, db, get_settings())
            self.assertEqual(ranking_service.records_transaction(raw, "total", db)["best"]["times"], [10, 20, 30])

    def test_pool_exhaustion_returns_bounded_503(self):
        # 占满真实测试库三条连接，API 应在 pool_timeout 后返回 503。
        held = [self.engine.connect() for _ in range(3)]
        try:
            self.client.cookies.set(get_settings().session_cookie_name, "test-token")
            self.assertEqual(self.client.get("/api/auth/me").status_code, 503)
        finally:
            for connection in held:
                connection.close()

    def test_avatar_defaults_and_persistence(self):
        """真实 Flyway 新列的默认值与编号更新应在重新登录后保持。"""
        name = self.new_name()
        first = self.client.post("/api/auth/login", json={"username": name, "password": "avatar-secret"})
        self.assertEqual(first.json()["user"]["avatar_id"], 1)
        self.assertEqual(self.client.put("/api/auth/avatar", json={"avatar_id": 17}).status_code, 200)
        self.client.post("/api/auth/logout")
        again = self.client.post("/api/auth/login", json={"username": name, "password": "avatar-secret"})
        self.assertEqual(again.json()["user"]["avatar_id"], 17)


if __name__ == "__main__":
    import unittest
    unittest.main()
