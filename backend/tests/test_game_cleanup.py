"""清理TDD：有界回收历史，永久奖励/星级/资格不受尝试清理影响。"""
from datetime import timedelta
from unittest import TestCase
from backend.tests import test_progression_v1 as fixtures
from backend.app.common.security import utc_now
from backend.app.models.entities.progression import GameAttempt, GameCompletion, PlayerProgression, PlayerQualification


class CleanupTests(TestCase):
    """不重复运行夹具所属的API测试。"""
    setUp = fixtures.ProgressionAPI.setUp
    tearDown = fixtures.ProgressionAPI.tearDown
    create = fixtures.ProgressionAPI.create
    answer = fixtures.ProgressionAPI.answer

    def test_tombstone_then_purge_keeps_permanent_rights(self):
        """30天后保留7天410墓碑，之后404；新尝试不能重新领80经验。"""
        from backend.cleanup_game_history import clean_history
        attempt = self.create().json()
        self.client.put(attempt['links']['completion'], json=self.answer(attempt))
        now = utc_now()
        with self.sessions() as db:
            db.get(GameAttempt, attempt['attempt_id']).ended_at = now - timedelta(days=31)
            db.commit()
        clean_history(self.sessions, batch_size=1, max_batches=1, now=now)
        self.assertEqual(self.client.get(attempt['links']['self']).status_code, 410)
        with self.sessions() as db:
            self.assertIsNone(db.get(GameCompletion, attempt['attempt_id']))
            self.assertEqual(db.get(PlayerProgression, 1).xp, 80)
            self.assertIsNotNone(db.get(PlayerQualification, (1, 'akari-001')))
        clean_history(self.sessions, batch_size=1, max_batches=1, now=now + timedelta(days=8))
        self.assertEqual(self.client.get(attempt['links']['self']).status_code, 404)
        next_attempt = self.create().json()
        result = self.client.put(next_attempt['links']['completion'], json=self.answer(next_attempt))
        self.assertEqual(result.json()['awarded_xp'], 0)
