"""预设头像测试：覆盖真实账号事务、来源/输入边界、榜单跟随和磁盘资源；SQLite 不代替 MySQL/Flyway。"""

from datetime import timedelta
import json
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import main
from backend.app.common.config import get_settings
from backend.app.common.database import Base, get_db
from backend.app.common.security import hash_session_token, utc_now
from backend.app.models.entities import AuthSession, User
from backend.app.models.entities.ranking import CompletionRecord, LeaderboardEntry

ROOT = Path(__file__).resolve().parents[2]


class AvatarTests(TestCase):
    """每例仅使用临时 SQLite，真实 HTTP Cookie 和 SQL 更新互相隔离。"""

    def setUp(self):
        """创建两个账号和会话，不连接项目 MySQL。"""
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        with self.sessions() as db:
            for number in (1, 2):
                db.add(User(id=number, username=f"玩家{number}", username_key=f"玩家{number}", password_hash="unchanged", created_at=utc_now()))
            db.flush()
            for number in (1, 2):
                db.add(AuthSession(id=number, user_id=number, token_hash=hash_session_token(f"avatar-token-{number}"),
                                   created_at=utc_now(), expires_at=utc_now() + timedelta(days=1)))
            db.commit()

        def test_db():
            """每个请求使用独立会话，保证刷新验证持久化读取。"""
            with self.sessions() as db:
                yield db

        main.app.dependency_overrides[get_db] = test_db
        self.client = TestClient(main.app, headers={"Origin": "http://testserver"})
        self.client.cookies.set(get_settings().session_cookie_name, "avatar-token-1")

    def tearDown(self):
        """关闭客户端及隔离数据库，归还全局依赖覆盖。"""
        self.client.close()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_default_save_restore_and_other_account_unchanged(self):
        """默认头像和更改结果跨会话持久，且不改变密码或另一个账号。"""
        self.assertEqual(self.client.get("/api/auth/me").json()["avatar_id"], 1)
        for value in (17, 25, 25):
            response = self.client.put("/api/auth/avatar", json={"avatar_id": value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"id": 1, "username": "玩家1", "avatar_id": value})
        self.assertEqual(self.client.get("/api/auth/me").json()["avatar_id"], 25)
        with self.sessions() as db:
            self.assertEqual(db.get(User, 1).password_hash, "unchanged")
            self.assertEqual(db.get(User, 2).avatar_id, 1)

    def test_invalid_values_and_forged_user_are_rejected(self):
        """拒绝隐式类型转换、未知编号和客户端指定的账号归属。"""
        for value in (0, 26, -1, True, 1.0, "17", None, "../../config"):
            with self.subTest(value=value):
                self.assertEqual(self.client.put("/api/auth/avatar", json={"avatar_id": value}).status_code, 422)
        self.assertEqual(self.client.put("/api/auth/avatar", json={"avatar_id": 2, "user_id": 2}).status_code, 422)
        self.assertEqual(self.client.get("/api/auth/me").json()["avatar_id"], 1)

    def test_auth_origin_and_actual_body_limit(self):
        """未登录、跨站和实际接收超限请求都在写入前拒绝。"""
        self.client.cookies.clear()
        self.assertEqual(self.client.put("/api/auth/avatar", json={"avatar_id": 2}).status_code, 401)
        self.client.cookies.set(get_settings().session_cookie_name, "avatar-token-1")
        self.assertEqual(self.client.put("/api/auth/avatar", json={"avatar_id": 2}, headers={"Origin": "https://evil.example"}).status_code, 403)
        response = self.client.put("/api/auth/avatar", content=iter([b'{"avatar_id":2,"padding":"', b'x' * 4100, b'"}']),
                                   headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_rankings_use_current_avatar_without_rewriting_records(self):
        """四榜直接读取当前用户头像，成绩快照和时间保持不变。"""
        with self.sessions() as db:
            for number, category in enumerate(("mine", "akari", "sudoku", "total"), 1):
                record = CompletionRecord(id=number, user_id=1, category=category, run_id=str(uuid4()),
                    attempt_id=str(uuid4()), duration_seconds=30, completed_at=utc_now(),
                    mine_seconds=10 if category == "total" else None, akari_seconds=10 if category == "total" else None,
                    sudoku_seconds=10 if category == "total" else None)
                db.add(record)
                db.flush()
                db.add(LeaderboardEntry(user_id=1, category=category, best_record_id=number, best_duration_seconds=30, achieved_at=utc_now()))
            db.commit()
        self.assertEqual(self.client.put("/api/auth/avatar", json={"avatar_id": 18}).status_code, 200)
        for category in ("mine", "akari", "sudoku", "total"):
            row = self.client.get(f"/api/rankings/{category}").json()["entries"][0]
            self.assertEqual((row["avatar_id"], row["duration_seconds"], row["rank"]), (18, 30, 1))
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(CompletionRecord)).all()), 4)


class AvatarAssetsTests(TestCase):
    """清单和实际发布文件必须覆盖 001 至 025，且不包含原始 PNG。"""

    def test_catalog_and_disk_assets(self):
        """默认图、有效编号、版本路径和整体体积均可从发布目录验证。"""
        folder = ROOT / "frontend/assets/avatars/v1"
        catalog = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["default_id"], 1)
        self.assertEqual([entry["id"] for entry in catalog["avatars"]], list(range(1, 26)))
        total = 0
        for entry in catalog["avatars"]:
            self.assertEqual(entry["src"], f'/assets/avatars/v1/{entry["id"]:03}.webp')
            data = (ROOT / "frontend" / entry["src"].lstrip("/")).read_bytes()
            self.assertEqual(data[:4], b"RIFF")
            self.assertEqual(data[8:12], b"WEBP")
            total += len(data)
        self.assertLess(total, 200 * 1024)
