"""作用：TDD验证账号体力、恢复边界、扣返幂等、免费入门与原子重开。"""
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import select,delete
from backend.tests import test_progression_v1 as fixture
from backend.app.common.game_catalog import LEVELS
from backend.app.common.security import utc_now
from backend.app.services import energy_service,progression_service as service
from backend.app.models.entities.progression import PlayerEnergy,AttemptEnergy,GameAttempt
from backend.content_check import akari_solutions
from backend.sudoku_content import solutions


class EnergyTests(TestCase):
    """真实路由使用隔离数据库；自然恢复只操控后端测试时钟。"""
    setUp=fixture.ProgressionAPI.setUp
    tearDown=fixture.ProgressionAPI.tearDown

    def energy(self):
        """读取服务端体力，客户端不能提交余额或恢复时间。"""
        response=self.client.get('/api/v1/me/energy')
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def start(self,level='akari-v2-001',key=None,status=201):
        """每次显式开始冻结UUID，重放使用同键同体。"""
        service.limiter.clear()
        response=self.client.post('/api/v1/attempts',headers={'Idempotency-Key':key or str(uuid4())},json={
            'level_id':level,'level_version':LEVELS[level]['level_version'],'mode':'campaign'})
        self.assertEqual(response.status_code,status,response.text)
        return response.json()

    def finish(self,attempt):
        """按绑定题目真实判题，重复提交使用完全相同的终盘。"""
        if attempt['game_id']=='akari':payload={'bulbs':akari_solutions(attempt['puzzle']['map'])[0]}
        else:payload={'values':solutions(attempt['puzzle']['values'],attempt['puzzle']['rows'])[0]}
        response=self.client.put(attempt['links']['completion'],json=payload)
        self.assertIn(response.status_code,(200,201),response.text)
        return response.json()

    def restart(self,attempt,key=None,status=201):
        """原子重开使用独立幂等键，失败不能放弃旧棋盘。"""
        service.limiter.clear()
        response=self.client.post(attempt['links']['self']+'/restart',headers={'Idempotency-Key':key or str(uuid4())},json={})
        self.assertEqual(response.status_code,status,response.text)
        return response.json()

    def test_start_completion_repeat_and_free_tutorial(self):
        """三游戏共用5点，重复开局和终盘不重复扣返，入门不变动余额。"""
        self.assertEqual(self.energy()['current'],5)
        key=str(uuid4());first=self.start(key=key)
        self.assertEqual(first['energy']['current'],4)
        self.assertEqual(self.start(key=key)['attempt_id'],first['attempt_id'])
        self.assertEqual(self.energy()['current'],4)
        self.assertEqual(self.client.get(first['links']['self']).json()['energy']['current'],4)
        second=self.start('sudoku-v2-easy-01');third=self.start('mine-v2-easy-10')
        self.assertEqual(self.energy()['current'],2)
        tutorial=self.start('akari-v2-tutorial');self.assertEqual(tutorial['energy']['current'],2)
        self.finish(tutorial);self.assertEqual(self.energy()['current'],2)
        self.assertEqual(self.finish(first)['energy']['current'],3)
        self.finish(first);self.assertEqual(self.energy()['current'],3)
        self.finish(second);self.assertEqual(self.energy()['current'],4)
        # 扫雷失败不返，接口恢复也不额外消耗。
        with self.sessions() as db:
            row=db.get(GameAttempt,third['attempt_id']);row.board={**row.board,'outcome':'lost'};db.commit()
        self.assertEqual(self.client.put(third['links']['completion'],json={}).status_code,422)
        self.assertEqual(self.energy()['current'],4)

    def test_voluntary_exit_keeps_spent_energy_blocks_rewards_and_allows_new_attempt(self):
        """主动退出终止三游戏原局，不返体力、不发奖，历史成长不受影响。"""
        for level in ['akari-v2-001','sudoku-v2-easy-01','mine-v2-easy-10']:
            with self.subTest(level=level):
                first=self.start(level)
                before=self.client.get('/api/v1/me/progression').json()
                latest=self.client.get(first['links']['self'])
                headers={'If-Match':latest.headers['etag']}
                ended=self.client.patch(first['links']['self'],json={'status':'abandoned'},headers=headers)
                self.assertEqual(ended.status_code,200,ended.text)
                self.assertEqual(ended.json()['status'],'abandoned')
                self.assertEqual(ended.json()['energy']['current'],first['energy']['current'])
                duplicate=self.client.patch(first['links']['self'],json={'status':'abandoned'},headers=headers)
                self.assertEqual(duplicate.status_code,200,duplicate.text)
                self.assertEqual(self.energy()['current'],first['energy']['current'])
                self.assertEqual(self.client.put(first['links']['completion'],json={}).status_code,409)
                self.assertEqual(self.client.get('/api/v1/me/progression').json(),before)
                progress=self.client.get(f"/api/v1/me/level-progress?game_id={first['game_id']}&limit=50").json()['items']
                self.assertTrue(all(not item.get('current_attempt') for item in progress if item['level_id']==level))
                if level=='akari-v2-001':
                    next_attempt=self.start(level)
                    self.assertNotEqual(first['attempt_id'],next_attempt['attempt_id'])
                    self.assertEqual(next_attempt['energy']['current'],first['energy']['current']-1)

    def test_regeneration_boundaries_and_cap(self):
        """1799秒不恢复，1800秒恢复；满体力清空周期，离线最多补到5点。"""
        start=utc_now()
        with patch.object(energy_service,'utc_now',return_value=start):
            attempt=self.start();second=self.start('akari-v2-002')
        with patch.object(energy_service,'utc_now',return_value=start+timedelta(seconds=1799)):
            self.assertEqual(self.energy()['current'],3)
        with patch.object(energy_service,'utc_now',return_value=start+timedelta(seconds=1800)):
            value=self.energy();self.assertEqual(value['current'],4)
            self.assertEqual(value['next_recovery_at'],energy_service.iso(start+timedelta(seconds=3600)))
            self.finish(attempt);full=self.energy();self.assertEqual(full['current'],5);self.assertIsNone(full['next_recovery_at'])
        with patch.object(energy_service,'utc_now',return_value=start+timedelta(seconds=1900)):
            self.start('akari-v2-003')
        with patch.object(energy_service,'utc_now',return_value=start+timedelta(seconds=3600)):
            self.assertEqual(self.energy()['current'],4)
        with patch.object(energy_service,'utc_now',return_value=start+timedelta(days=20)):
            self.assertEqual(self.energy()['current'],5)

    def test_zero_atomic_restart_idempotency_and_rollback(self):
        """零体力重开失败保留旧局；恢复后重开只扣一次，旧局消费不退。"""
        shared=str(uuid4());old=self.start(key=shared);second=self.restart(old,key=shared)
        self.assertEqual(second['energy']['current'],3)
        self.assertEqual(self.client.get(old['links']['self']).json()['status'],'abandoned')
        key=str(uuid4());third=self.restart(second,key)
        self.assertEqual(self.restart(second,key)['attempt_id'],third['attempt_id'])
        self.assertEqual(self.energy()['current'],2)
        self.assertEqual(self.restart(second,status=409)['code'],'restart_conflict')
        self.assertEqual(self.energy()['current'],2)
        self.start('akari-v2-002');self.start('akari-v2-003')
        self.assertEqual(self.energy()['current'],0)
        failed=self.restart(third,status=409);self.assertEqual(failed['code'],'energy_insufficient')
        self.assertEqual(self.client.get(third['links']['self']).json()['status'],'active')
        self.start('akari-v2-004',status=409)
        self.assertEqual(self.start('mine-v2-tutorial')['energy']['current'],0)
        # 注入创建阶段故障，验证重开中的放弃及扣费一并回滚。
        with self.sessions() as db:
            row=db.get(PlayerEnergy,1);row.current=2;row.recovery_at=None;db.commit()
        with patch.object(service,'create_attempt',side_effect=RuntimeError('test rollback')):
            with self.assertRaises(RuntimeError):self.restart(third)
        self.assertEqual(self.client.get(third['links']['self']).json()['status'],'active')
        self.assertEqual(self.energy()['current'],2)

    def test_legacy_attempt_no_refund_account_isolation_and_strict_restart(self):
        """无扣费凭证的旧盘不返，其他账号不能操作，拒绝伪造余额。"""
        first=self.start()
        with self.sessions() as db:
            db.execute(delete(AttemptEnergy).where(AttemptEnergy.attempt_id==first['attempt_id']));db.commit()
        self.finish(first);self.assertEqual(self.energy()['current'],4)
        self.assertEqual(self.client.post(first['links']['self']+'/restart',headers={'Idempotency-Key':str(uuid4())},json={'energy':5}).status_code,422)
        self.client.cookies.set(self.settings.session_cookie_name,'2')
        self.assertEqual(self.energy()['current'],5)
        self.restart(first,status=404)
