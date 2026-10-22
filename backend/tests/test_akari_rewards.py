"""作用：TDD验证照明按服务器用时评星、简单档经验补差及旧成绩兼容。"""
from datetime import timedelta
from unittest import TestCase
from uuid import uuid4
import json
from pathlib import Path
from backend.tests import test_progression_v1 as fixture
from backend.app.common.game_catalog import LEVELS
from backend.app.common.security import utc_now
from backend.app.models.entities.progression import GameAttempt
from backend.app.services import progression_service as service
from backend.app.services.game_rules import stars_for
from backend.content_check import akari_solutions


class AkariRewards(TestCase):
    """完整路由和事务判分，不接受浏览器自报时间、星星或经验。"""
    setUp=fixture.ProgressionAPI.setUp
    tearDown=fixture.ProgressionAPI.tearDown

    def start(self):
        """按最新发布版本开始，同一关每次形成独立的正式尝试。"""
        service.limiter.clear();level=LEVELS['akari-v2-001']
        response=self.client.post('/api/v1/attempts',headers={'Idempotency-Key':str(uuid4())},json={
            'level_id':level['level_id'],'level_version':level['level_version'],'mode':'campaign'})
        self.assertEqual(response.status_code,201,response.text);return response.json()

    def finish(self,attempt,milliseconds):
        """只调整隔离测试库的开始时间，真实HTTP入口时间由服务器记录。"""
        with self.sessions() as db:
            row=db.get(GameAttempt,attempt['attempt_id']);row.started_at=utc_now()-timedelta(milliseconds=milliseconds);db.commit()
        answer={'bulbs':akari_solutions(attempt['puzzle']['map'])[0]}
        response=self.client.put(attempt['links']['completion'],json=answer)
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(self.client.put(attempt['links']['completion'],json=answer).json(),response.json())
        return response.json()

    def test_all_normal_levels_use_timed_stars_and_easy_xp(self):
        """15关共用简单档经验，时限包含边界；入门固定1星2经验。"""
        items=self.client.get('/api/v1/levels?game_id=akari').json()['items']
        self.assertEqual(len(items),16)
        for item in items:
            if item['number']==0:
                self.assertEqual(item['star_xp'],[2]);self.assertEqual(stars_for(item,99999999),1);continue
            self.assertEqual(item['star_xp'],[2,4,6])
            self.assertEqual([stars_for(item,t) for t in (item['t3_ms'],item['t3_ms']+1,item['t2_ms'],item['t2_ms']+1)],[3,2,2,1])

    def test_improvement_only_pays_difference_and_repeat_pays_zero(self):
        """慢速一星得2，再到二星补2，三星再补2，重复三星0。"""
        level=LEVELS['akari-v2-001'];total=0
        for ms,stars,xp,added in [(level['t2_ms']+5000,1,2,1),(level['t3_ms']+5000,2,2,1),(1000,3,2,1),(1000,3,0,0)]:
            result=self.finish(self.start(),ms)
            self.assertEqual((result['stars'],result['awarded_xp'],result['awarded_stars']),(stars,xp,added))
            total+=xp
        summary=self.client.get('/api/v1/me/progression').json()
        self.assertEqual((summary['xp'],summary['total_stars']),(total,3))

    def test_new_versions_do_not_overwrite_old_catalog_or_migration(self):
        """只追加15个评分版本，题盘不变，保留旧80经验定义与成绩。"""
        root=Path(__file__).resolve().parents[1]
        before=json.loads((root/'content/akari-catalog-v3.json').read_text(encoding='utf-8'))['levels']
        after=json.loads((root/'content/akari-catalog-v4.json').read_text(encoding='utf-8'))['levels']
        sql=(root/'migrations/V16__align_akari_timed_rewards.sql').read_text(encoding='utf-8')
        self.assertNotIn('UPDATE ',sql);self.assertEqual(after[0],before[0])
        for old,new in zip(before[1:],after[1:]):
            self.assertEqual(new['puzzle'],old['puzzle']);self.assertEqual(new['level_id'],old['level_id'])
            self.assertEqual(new['level_version'],old['level_version']+1)
            self.assertEqual((new['t3_ms'],new['t2_ms']),(old['t3_ms'],old['t2_ms']))
            self.assertIn(json.dumps(new,ensure_ascii=False,separators=(',',':')),sql)

    def test_old_awarded_eighty_xp_is_kept_without_repaying(self):
        """旧版已获80经验不追回，切换新版再次通关不会借策略升级重复领奖。"""
        from backend.app.common.game_catalog import AKARI_V3_LEVELS
        old=next(level for level in AKARI_V3_LEVELS if level.get('number')==1)
        service.limiter.clear()
        response=self.client.post('/api/v1/attempts',headers={'Idempotency-Key':str(uuid4())},json={
            'level_id':old['level_id'],'level_version':old['level_version'],'mode':'campaign'})
        self.assertEqual(response.status_code,201,response.text)
        first=self.finish(response.json(),1000)
        self.assertEqual((first['stars'],first['awarded_xp']),(3,80))
        second=self.finish(self.start(),1000)
        self.assertEqual((second['awarded_stars'],second['awarded_xp']),(0,0))
        self.assertEqual(self.client.get('/api/v1/me/progression').json()['xp'],80)
