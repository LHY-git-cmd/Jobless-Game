"""作用：TDD验证照明16关目录、权威判题、计时、幂等奖励及旧资格兼容。"""
from datetime import timedelta
from unittest import TestCase
from uuid import uuid4
from backend.tests import test_progression_v1 as fixture
from backend.app.services import progression_service as service
from backend.app.common.security import utc_now
from backend.app.common.game_catalog import LEVELS
from backend.app.models.entities.progression import GameAttempt
from backend.content_check import akari_solutions


class AkariAPI(TestCase):
    """真实路由与隔离SQLite核对业务，不对业务库执行迁移。"""
    setUp=fixture.ProgressionAPI.setUp
    tearDown=fixture.ProgressionAPI.tearDown

    def start(self, key='akari-v2-001'):
        """只提交关卡标识，由服务器绑定冻结题目。"""
        service.limiter.clear()
        response=self.client.post('/api/v1/attempts',headers={'Idempotency-Key':str(uuid4())},json={
            'level_id':key,'level_version':LEVELS[key]['level_version'],'mode':'campaign'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def answer(self, attempt):
        """离线搜索只用于测试，页面和接口均不得提供标准答案。"""
        return {'bulbs':akari_solutions(attempt['puzzle']['map'])[0]}

    def test_public_sixteen_and_legacy_kept(self):
        """新目录只列16关，不显示内部难度或发放题目，旧资源仍存在。"""
        response=self.client.get('/api/v1/levels?game_id=akari')
        self.assertEqual(response.status_code,200)
        items=response.json()['items']
        self.assertEqual(len(items),16)
        self.assertEqual([v['number'] for v in items],list(range(16)))
        self.assertNotIn('map',str(items));self.assertNotIn('score',str(items))
        self.assertIn('akari-001',LEVELS)
        self.assertTrue(all(v['minimum_level']==1 and not v['prerequisite_level_id'] for v in items))

    def test_every_level_completion_repeat_and_qualification(self):
        """16关全部可开可结算；教学不授资格，第1关授旧资格，重放不多奖。"""
        for number in range(16):
            identity='akari-v2-tutorial' if number==0 else f'akari-v2-{number:03}'
            attempt=self.start(identity);payload=self.answer(attempt)
            result=self.client.put(attempt['links']['completion'],json=payload)
            self.assertEqual(result.status_code,201,result.text)
            data=result.json();self.assertEqual(data['stars'],1 if number==0 else 3)
            self.assertEqual(self.client.put(attempt['links']['completion'],json=payload).json(),data)
            qualified=self.client.get('/api/v1/me/pk-eligibility').json()
            self.assertEqual(qualified['eligible'],qualified['level']>=5)
            self.assertEqual(qualified['requirements'],[])
        attempt=self.start();result=self.client.put(attempt['links']['completion'],json=self.answer(attempt)).json()
        self.assertEqual((result['awarded_stars'],result['awarded_xp']),(0,0))

    def test_pause_invalid_and_account_isolation(self):
        """暂停禁提交，排除暂停时间；拒绝伪造终盘与他人读取。"""
        attempt=self.start();base=attempt['links']['self'];answer=self.answer(attempt)
        self.assertEqual(self.client.put(attempt['links']['completion'],json={'bulbs':[]}).status_code,422)
        self.assertEqual(self.client.put(attempt['links']['completion'],json={**answer,'duration_ms':0}).status_code,422)
        paused=self.client.put(base+'/clock',json={'paused':True,'revision':attempt['timing']['revision'],'command_id':str(uuid4())})
        self.assertEqual(paused.status_code,200,paused.text)
        self.assertEqual(self.client.put(attempt['links']['completion'],json=answer).status_code,409)
        resumed=self.client.put(base+'/clock',json={'paused':False,'revision':paused.json()['timing']['revision'],'command_id':str(uuid4())})
        self.assertEqual(resumed.status_code,200,resumed.text)
        with self.sessions() as db:
            row=db.get(GameAttempt,attempt['attempt_id'])
            row.started_at=utc_now()-timedelta(seconds=4000)
            row.board={**row.board,'clock_paused_ms':3999000};db.commit()
        saved=self.client.put(attempt['links']['completion'],json=answer)
        self.assertEqual(saved.status_code,201,saved.text)
        self.assertLess(saved.json()['duration_ms'],3000)
        self.client.cookies.set(self.settings.session_cookie_name,'2')
        self.assertEqual(self.client.get(base).status_code,404)

    def test_legacy_fixed_rewards_stay_bound_to_old_versions(self):
        """旧策略保持三星，新策略按时间；入门仍固定一星。"""
        from backend.app.services.game_rules import stars_for
        self.assertEqual(stars_for({'game_id':'akari','rules_version':2,'t3_ms':1,'t2_ms':2},9000000),3)
        self.assertEqual(stars_for({'game_id':'akari','rules_version':2,'reward_policy_version':2,'t3_ms':1,'t2_ms':2},9000000),1)
        self.assertEqual(stars_for({'game_id':'akari','rules_version':2,'max_stars':1},9000000),1)

    def test_new_boards_preserve_old_attempts_and_do_not_duplicate_rewards(self):
        """旧8×8尝试保留原盘，新10×10沿用同一关卡权益且不会再发一次奖励。"""
        level='akari-v2-010'
        old=self.client.post('/api/v1/attempts',headers={'Idempotency-Key':str(uuid4())},json={
            'level_id':level,'level_version':1,'mode':'campaign'})
        self.assertEqual(old.status_code,201,old.text)
        previous=old.json();self.assertEqual(previous['puzzle']['rows'],8)
        first=self.client.put(previous['links']['completion'],json=self.answer(previous))
        self.assertEqual(first.status_code,201,first.text)
        new=self.start(level);self.assertEqual(new['level_version'],LEVELS[level]['level_version']);self.assertEqual(new['puzzle']['rows'],10)
        self.assertEqual(self.client.get(previous['links']['self']).json()['puzzle']['rows'],8)
        saved=self.client.put(new['links']['completion'],json=self.answer(new)).json()
        self.assertEqual((saved['awarded_stars'],saved['awarded_xp']),(0,0))
