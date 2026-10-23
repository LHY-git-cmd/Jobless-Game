"""双人房间/匹配TDD：资格、有限容量、受控发题、平局及重启恢复。"""

from datetime import timedelta
from unittest import TestCase
from uuid import uuid4
from sqlalchemy import delete
from backend.tests import test_progression_v1 as fixtures
from backend.app.common.security import utc_now
from backend.app.common.game_catalog import QUALIFICATIONS
from backend.app.models.entities.progression import PlayerQualification,PlayerProgression
from backend.content_check import akari_solutions


class PKTests(TestCase):
    """复用隔离夹具，不继承或重复运行成长测试。"""

    def setUp(self):
        """隔离数据库及本进程房间状态。"""
        fixtures.ProgressionAPI.setUp(self)
        from backend.app.services.pk_runtime import runtime
        runtime.reset()

    def tearDown(self):
        """关闭客户端并还原开关。"""
        fixtures.ProgressionAPI.tearDown(self)

    def identity(self, uid):
        """模拟真实Cookie切换，归属仍由服务端认证。"""
        self.client.cookies.set(self.settings.session_cookie_name, str(uid))

    def qualify(self, uid, completed=QUALIFICATIONS):
        """测试夹具直接建立永久成果；产品没有此入口。"""
        with self.sessions() as db:
            db.execute(delete(PlayerQualification).where(PlayerQualification.user_id == uid))
            for key in completed:
                db.add(PlayerQualification(user_id=uid, requirement_id=key, level_version=1,
                       attempt_id=str(uuid4()), completed_at=utc_now()))
            summary=db.get(PlayerProgression,uid)
            if summary:summary.xp=72 if len(completed)==3 else 0
            else:db.add(PlayerProgression(user_id=uid,xp=72 if len(completed)==3 else 0,total_stars=0,revision=0))
            db.commit()

    def post(self, url, data, key=None):
        """创建型资源统一携带UUID幂等键。"""
        return self.client.post('/api/v1/' + url, json=data, headers={'Idempotency-Key': key or str(uuid4())})

    def room(self):
        """按正常流程创建双方已加入的房间。"""
        for uid in (1, 2):
            self.qualify(uid)
        self.identity(1)
        first = self.post('rooms', {'game_id': 'akari', 'difficulty': 'normal'})
        self.assertEqual(first.status_code, 201, first.text)
        room = first.json()
        self.identity(2)
        joined = self.post('room-memberships', {'room_code': room['room_code']})
        self.assertEqual(joined.status_code, 201, joined.text)
        return room['room_id']

    def ready(self, room_id, uid):
        """条件更新准备状态使用最新房间ETag。"""
        self.identity(uid)
        response = self.client.get('/api/v1/rooms/' + room_id)
        return self.client.put(f'/api/v1/rooms/{room_id}/members/me/readiness', json={'ready': True}, headers={'If-Match': response.headers['etag']})

    def tick(self, now=None, restart=False):
        """显式推进调度器；GET从来不推进状态。"""
        from backend.app.services.pk_service import maintenance
        maintenance(self.sessions, now=now, restart=restart)

    def playing(self):
        """按统一倒计时开局，无隐藏的客户端开始命令。"""
        room_id = self.room()
        self.ready(room_id, 1)
        self.ready(room_id, 2)
        from backend.app.models.entities.pk import PKRoom
        with self.sessions() as db:
            row = db.get(PKRoom, room_id)
            row.starts_at = utc_now() - timedelta(seconds=1)
            db.commit()
        self.tick()
        return room_id

    def test_all_qualification_combinations_guard_three_entrances(self):
        """缺任意正式资格，创建/加入/入队均403，而非只隐藏按钮。"""
        self.qualify(1)
        room = self.post('rooms', {'game_id': 'akari', 'difficulty': 'normal'}).json()
        self.identity(2)
        for mask in range(7):
            self.qualify(2, [key for i, key in enumerate(QUALIFICATIONS) if mask & (1 << i)])
            for url, body in [('rooms', {'game_id': 'akari', 'difficulty': 'normal'}),
                              ('room-memberships', {'room_code': room['room_code']}),
                              ('matchmaking-tickets', {'game_id': 'akari', 'difficulty': 'normal'})]:
                result = self.post(url, body)
                self.assertEqual(result.status_code, 403, result.text)
                self.assertEqual(result.json()['code'], 'pk_locked')
        self.qualify(2)
        self.assertEqual(self.post('room-memberships', {'room_code': room['room_code']}).status_code, 201)

    def test_hidden_puzzle_ready_preconditions_countdown_and_leave(self):
        """未开局不可发题；GET不开始比赛；倒计时退出取消并重置准备。"""
        room_id = self.room()
        base = '/api/v1/rooms/' + room_id
        response = self.client.get(base)
        self.assertNotIn('puzzle', response.json())
        self.assertEqual(self.client.put(base + '/members/me/readiness', json={'ready': True}).status_code, 428)
        self.ready(room_id, 1)
        self.assertEqual(self.ready(room_id, 2).json()['status'], 'countdown')
        self.assertNotIn('puzzle', self.client.get(base).json())
        self.assertEqual(self.client.put(base + '/submissions/me', json={'bulbs': []}).status_code, 409)
        left = self.client.delete(base + '/members/me')
        self.assertEqual(left.status_code, 204)
        self.assertEqual(left.content, b'')
        self.identity(1)
        value = self.client.get(base).json()
        self.assertEqual(value['status'], 'waiting')
        self.assertFalse(value['members'][0]['ready'])

    def test_submission_draw_idempotency_and_no_growth_reward(self):
        """同题竞速平局窗口内完成为平局，重复有效提交无副作用。"""
        room_id = self.playing()
        base = '/api/v1/rooms/' + room_id
        for uid in (1, 2):
            self.identity(uid)
            room = self.client.get(base).json()
            payload = {'bulbs': akari_solutions(room['puzzle']['map'])[0]}
            first = self.client.put(base + '/submissions/me', json=payload)
            self.assertEqual(first.status_code, 201, first.text)
            self.assertEqual(self.client.put(base + '/submissions/me', json=payload).status_code, 200)
            self.assertNotIn('bulbs', str(self.client.get(base).json()))
        self.tick(utc_now() + timedelta(seconds=2))
        result = self.client.get(base + '/result')
        self.assertEqual(result.json()['outcome'], 'draw')
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'], 72)

    def test_pending_ingress_prevents_early_winner_and_restart_cancels(self):
        """平局窗口内已接收请求必须先处理，不能靠DB队列决定胜者。"""
        from backend.app.services.pk_runtime import runtime
        room_id = self.playing()
        base = '/api/v1/rooms/' + room_id
        room = self.client.get(base).json()
        pending = runtime.receive(room_id, utc_now())
        self.client.put(base + '/submissions/me', json={'bulbs': akari_solutions(room['puzzle']['map'])[0]})
        self.tick(utc_now() + timedelta(seconds=2))
        self.assertEqual(self.client.get(base + '/result').status_code, 404)
        runtime.processed(pending)
        self.tick(utc_now() + timedelta(seconds=2))
        self.assertEqual(self.client.get(base + '/result').json()['outcome'], 'win')
        self.client.delete(base + '/members/me')
        self.tick(restart=True)

    def test_occupancy_idempotency_pair_cancel_and_ticket_expiry(self):
        """同账号只占一个PK身份，配对与取消只有一个结果。"""
        for uid in (1, 2):
            self.qualify(uid)
        payload = {'game_id': 'akari', 'difficulty': 'normal'}
        key = str(uuid4())
        one = self.post('matchmaking-tickets', payload, key)
        self.assertEqual(one.status_code, 201, one.text)
        ticket = one.json()
        self.assertEqual(self.post('matchmaking-tickets', payload, key).json(), ticket)
        self.assertEqual(self.post('rooms', payload).status_code, 409)
        self.identity(2)
        two = self.post('matchmaking-tickets', payload)
        self.assertEqual(two.status_code, 201, two.text)
        self.assertEqual(two.json()['status'], 'matched')
        self.identity(1)
        updated = self.client.get(ticket['links']['self']).json()
        self.assertEqual(updated['room_id'], two.json()['room_id'])
        self.assertEqual(self.client.delete(ticket['links']['self']).status_code, 409)
        self.tick(restart=True)
        self.assertEqual(self.client.get('/api/v1/rooms/' + updated['room_id']).json()['reason'], 'server_restart')
        new = self.post('matchmaking-tickets', payload).json()
        self.tick(utc_now() + timedelta(seconds=61))
        self.assertEqual(self.client.get(new['links']['self']).json()['status'], 'expired')
        self.assertEqual(self.client.delete(new['links']['self']).status_code, 204)

    def test_capacity_rejects_new_rooms_but_allows_join(self):
        """满额时创建503，已存在房间仍可加入。"""
        self.settings.pk_room_limit = 1
        try:
            self.qualify(1)
            self.qualify(2)
            first = self.post('rooms', {'game_id': 'akari', 'difficulty': 'normal'}).json()
            self.identity(2)
            rejected = self.post('rooms', {'game_id': 'akari', 'difficulty': 'normal'})
            self.assertEqual(rejected.status_code, 503)
            self.assertIn('Retry-After', rejected.headers)
            self.assertEqual(self.post('room-memberships', {'room_code': first['room_code']}).status_code, 201)
        finally:
            self.settings.pk_room_limit = 4

    def test_disconnect_grace_both_offline_void_and_one_offline_loss(self):
        """双方离线作废，单方宽限超时判负，不把离线先后当成完成时间。"""
        from unittest.mock import patch
        from backend.app.services.pk_runtime import runtime
        room_id = self.playing()
        base = '/api/v1/rooms/' + room_id
        self.tick(utc_now()+timedelta(seconds=31))
        value = self.client.get(base+'/result').json()
        self.assertEqual((value['outcome'], value['reason']), ('cancelled', 'both_offline'))
        self.client.delete(base+'/members/me')
        next_room = self.playing()
        with patch.object(runtime, 'online', side_effect=lambda uid: uid == 1):
            self.tick(utc_now()+timedelta(seconds=31))
        value = self.client.get('/api/v1/rooms/'+next_room+'/result').json()
        self.assertEqual((value['outcome'], value['winner_id'], value['reason']), ('win', 1, 'opponent_disconnected'))

    def test_waiting_timeout_releases_occupancy_and_get_does_not_advance(self):
        """等待房到期只由调度器关闭，释放后可重新创建。"""
        from backend.app.models.entities.pk import PKRoom
        self.qualify(1)
        room = self.post('rooms', {'game_id': 'akari', 'difficulty': 'normal'}).json()
        with self.sessions() as db:
            db.get(PKRoom, room['room_id']).expires_at = utc_now()-timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.client.get(room['links']['self']).json()['status'], 'waiting')
        self.tick()
        self.assertEqual(self.client.get(room['links']['self']).json()['status'], 'expired')
        self.assertEqual(self.post('rooms', {'game_id': 'akari', 'difficulty': 'normal'}).status_code, 201)
