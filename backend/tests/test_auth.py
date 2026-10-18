"""验证登录安全和资源边界；模拟数据库测试不代替真实 MySQL/Flyway 验收。"""

import asyncio
from datetime import timedelta
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import MagicMock, patch
from starlette.requests import Request

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, TimeoutError as PoolTimeout

from backend.app import main
from backend.app.common.config import Settings, get_settings
from backend.app.common.database import get_db
from backend.app.common.exceptions import AppError
from backend.app.common import concurrency
from backend.app.controllers import auth_controller
from backend.app.services import auth_service
from backend.app.services.login_limiter import LoginRateLimiter
from backend.app.models.entities import AuthSession, User
from backend.app.models.schemas.auth import LoginRequest
from backend.app.common.security import hash_password, hash_session_token, utc_now, verify_password
from backend.app.services.auth_rules import username_key, validate_username, validate_password

settings = get_settings()


class ValidationTests(TestCase):
    """用户名按字符计数，密码保持原样且使用真实 Argon2id。"""

    def test_username_boundaries(self):
        for name in ["中文123456789", "一二三四五六七八", "abc123ABC123", "𠀀1234567890"]:
            self.assertIsNone(validate_username(name), name)
        for name in ["", "中文1234567890", "九" * 9, " a", "a_b", "a😀", "a\n", "\ufaff", "\U0002a6e0"]:
            self.assertIsNotNone(validate_username(name), repr(name))
        self.assertEqual(username_key("Player1"), username_key("player1"))

    def test_password_hash_and_original_whitespace(self):
        self.assertIsNotNone(validate_password("12345"))
        self.assertIsNone(validate_password("      "))
        hashed = hash_password(" Abc12 ")
        self.assertTrue(hashed.startswith("$argon2id$v=19$m=65536,t=3,p=1$"))
        self.assertNotIn(" Abc12 ", hashed)
        self.assertTrue(verify_password(hashed, " Abc12 "))
        self.assertFalse(verify_password(hashed, "Abc12"))


class TransactionTests(TestCase):
    """验证业务事务分支，不使用其他数据库冒充 MySQL。"""

    def setUp(self):
        self.db = MagicMock()
        self.config = Settings()
        self.user = User(id=7, username="Player1", username_key="player1", password_hash=hash_password("secret1"), created_at=utc_now())

    def test_first_login_creates_user_and_only_token_digest(self):
        self.db.scalar.return_value = None
        def assign_id():
            self.db.add.call_args_list[0].args[0].id = 9
        self.db.flush.side_effect = assign_id
        user, created, raw, expires = auth_service.login_transaction(LoginRequest(username="新玩家", password="secret1"), self.db, self.config)
        self.assertTrue(created)
        self.assertNotEqual(user.password_hash, "secret1")
        session = self.db.add.call_args_list[-1].args[0]
        self.assertEqual(session.token_hash, hash_session_token(raw))
        self.assertGreater(expires, utc_now() + timedelta(days=6))

    def test_existing_user_and_wrong_password(self):
        self.db.scalar.return_value = self.user
        user, created, _, _ = auth_service.login_transaction(LoginRequest(username="PLAYER1", password="secret1"), self.db, self.config)
        self.assertFalse(created)
        self.assertEqual(user.username, "Player1")
        with self.assertRaises(AppError) as error:
            auth_service.login_transaction(LoginRequest(username="player1", password="wrong1"), self.db, self.config)
        self.assertEqual(error.exception.status_code, 401)
        self.assertTrue(verify_password(self.user.password_hash, "secret1"))

    def test_unique_key_race_reads_winner_and_verifies_original_password(self):
        self.db.scalar.side_effect = [None, self.user]
        self.db.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
        user, created, _, _ = auth_service.login_transaction(LoginRequest(username="PLAYER1", password="secret1"), self.db, self.config)
        self.assertEqual(user.id, 7)
        self.assertFalse(created)
        self.db.rollback.assert_called_once()

    def test_expired_session_is_invalidated(self):
        expired = AuthSession(user_id=7, token_hash="x", created_at=utc_now(), expires_at=utc_now() - timedelta(seconds=1))
        self.db.scalar.return_value = expired
        self.assertIsNone(auth_service.current_session("token", self.db))
        self.db.delete.assert_called_once_with(expired)


class APITests(TestCase):
    """验证 Cookie、同源、注销及数据库失败时的脱敏响应。"""

    def setUp(self):
        self.db = MagicMock()
        main.app.dependency_overrides[get_db] = lambda: self.db
        auth_service.rate_limiter = LoginRateLimiter(100, 60)
        self.client = TestClient(main.app, headers={"Origin": "http://testserver"})

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.client.close()

    def test_login_cookie_restore_and_logout(self):
        user = User(id=1, username="玩家", username_key="玩家", password_hash="hidden", created_at=utc_now())
        with patch.object(auth_service, "login_transaction", return_value=(user, False, "random-token", utc_now() + timedelta(days=7))):
            response = self.client.post("/api/auth/login", json={"username": "玩家", "password": "secret1"})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertNotIn("password", response.text)
        session = AuthSession(user_id=1, token_hash=hash_session_token("random-token"), created_at=utc_now(), expires_at=utc_now() + timedelta(days=1))
        session.user = user
        self.db.scalar.return_value = session
        self.assertEqual(self.client.get("/api/auth/me").json()["username"], "玩家")
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.db.execute.assert_called_once()
        self.db.commit.assert_called()

    def test_origin_and_database_pool_timeout(self):
        self.assertEqual(self.client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", headers={"Origin": "http://testserver:bad-port"}).status_code, 403)
        self.db.scalar.side_effect = PoolTimeout("secret internal server")
        self.client.cookies.set(settings.session_cookie_name, "token")
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_missing_origin_is_rejected_and_api_rate_limit_returns_retry_after(self):
        self.client.headers.pop("Origin")
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 403)
        auth_service.rate_limiter = LoginRateLimiter(1, 60)
        auth_service.rate_limiter.allow("testclient")
        response = self.client.post("/api/auth/login", headers={"Origin": "http://testserver"}, json={"username": "abc", "password": "secret1"})
        self.assertEqual(response.status_code, 429)
        self.assertIn("retry-after", response.headers)

    def test_actual_chunked_body_limit_and_safe_validation(self):
        response = self.client.post("/api/auth/login", content=iter([b'{"password":"' + b'x' * 4100, b'"}']), headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 413)
        response = self.client.post("/api/auth/login", json={"username": ["a"], "password": "private"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("private", response.text)

    def test_service_errors_keep_original_http_contract(self):
        """Service 抛公共业务异常后仍由统一处理器返回原状态码与字段错误。"""
        invalid = self.client.post("/api/auth/login", json={"username": "bad_name", "password": "secret1"})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["detail"]["field"], "username")
        self.db.scalar.return_value = User(id=3, username="Player1", username_key="player1", password_hash=hash_password("secret1"), created_at=utc_now())
        wrong = self.client.post("/api/auth/login", json={"username": "PLAYER1", "password": "wrong1"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json(), {"detail": "用户名或密码错误。"})
        self.assertNotIn("wrong1", wrong.text)
        self.db.commit.assert_not_called()

    def test_rate_limiter_is_bounded_and_recovers_after_window(self):
        limiter = LoginRateLimiter(2, 60)
        self.assertTrue(limiter.allow("a", 0))
        self.assertTrue(limiter.allow("a", 0))
        self.assertFalse(limiter.allow("a", 1))
        self.assertTrue(limiter.allow("a", 61))
        for index in range(3000):
            limiter.allow(str(index), 62)
        self.assertLessEqual(len(limiter._attempts), 2048)


class ConcurrencyTests(IsolatedAsyncioTestCase):
    """登录计算超限必须立即拒绝，不向线程池追加无限等待任务。"""

    async def test_busy_hash_gate_rejects_without_waiting(self):
        gate = auth_service.hash_semaphore
        acquired = gate.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            with self.assertRaises(AppError) as error:
                request = Request({"type": "http", "scheme": "http", "method": "POST", "path": "/api/auth/login", "headers": [(b"host", b"test"), (b"origin", b"http://test")], "client": ("test", 123)})
                await asyncio.wait_for(auth_controller.login(LoginRequest(username="abc", password="secret1"), request, MagicMock(), MagicMock()), timeout=.5)
            self.assertEqual(error.exception.status_code, 429)
        finally:
            gate.release()

    async def test_busy_database_gate_rejects_without_queue(self):
        for _ in range(4):
            self.assertTrue(concurrency.db_slots.acquire(blocking=False))
        try:
            with self.assertRaises(AppError) as error:
                await concurrency.bounded_db_call(lambda: "should not run")
            self.assertEqual(error.exception.status_code, 503)
        finally:
            for _ in range(4):
                concurrency.db_slots.release()

    async def test_hash_busy_does_not_block_ordinary_session_query(self):
        auth_service.hash_semaphore.acquire()
        try:
            self.assertEqual(await asyncio.wait_for(concurrency.bounded_db_call(lambda: "session available"), .5), "session available")
        finally:
            auth_service.hash_semaphore.release()

    async def test_executor_rejection_returns_reserved_hash_slot(self):
        """执行器拒绝在 Service 中转换为原有 503，且不能泄漏预留的计算槽。"""
        for _ in range(4):
            self.assertTrue(concurrency.db_slots.acquire(blocking=False))
        try:
            with patch.object(auth_service, "login_transaction") as transaction:
                with self.assertRaises(AppError) as error:
                    await auth_service.login(LoginRequest(username="abc", password="secret1"), "executor-rejection", MagicMock(), settings)
                self.assertEqual(error.exception.status_code, 503)
                transaction.assert_not_called()
            acquired = auth_service.hash_semaphore.acquire(blocking=False)
            self.assertTrue(acquired)
            if acquired:
                auth_service.hash_semaphore.release()
        finally:
            for _ in range(4):
                concurrency.db_slots.release()


if __name__ == "__main__":
    import unittest
    unittest.main()
