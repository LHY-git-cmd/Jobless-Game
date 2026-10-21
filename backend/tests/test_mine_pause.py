"""作用：暂停计时先行契约，使用隔离SQLite、真实API和服务器时钟。"""
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
from backend.tests import test_progression_v1 as fixture
from backend.app.common.security import utc_now
from backend.app.services import progression_service as service
from backend.app.models.entities.progression import GameAttempt


class MinePause(TestCase):
    """暂停时间与结算同源，旧请求不能覆盖重新进入后的计时状态。"""
    setUp=fixture.ProgressionAPI.setUp
    tearDown=fixture.ProgressionAPI.tearDown

    def start(self):
        """通过正式开局接口获取服务器时钟版本。"""
        return self.client.post('/api/v1/attempts',headers={'Idempotency-Key':str(uuid4())},json={
            'level_id':'mine-v2-easy-10','level_version':1,'mode':'campaign'}).json()

    def clock(self,attempt,paused,revision=None,key=None):
        """revision参与比较交换，command_id保证丢响应重试不会重复累计。"""
        return self.client.put(attempt['links']['self']+'/clock',json={
            'paused':paused,'revision':attempt['timing']['revision'] if revision is None else revision,'command_id':key or str(uuid4())})

    def test_pause_resume_freeze_and_completion_uses_active_time(self):
        """65秒游戏+长暂停+5秒游戏应三星，暂停期间拒绝揭格。"""
        attempt=self.start();start=utc_now()
        with self.sessions() as db:
            db.get(GameAttempt,attempt['attempt_id']).started_at=start;db.commit()
        with patch.object(service,'utc_now',return_value=start+timedelta(seconds=65)):
            paused=self.clock(attempt,True).json()
        with patch.object(service,'utc_now',return_value=start+timedelta(seconds=665)):
            snapshot=self.client.get(attempt['links']['self']).json()
            self.assertEqual(snapshot['timing']['elapsed_ms'],65000)
            self.assertTrue(snapshot['timing']['paused'])
            self.assertEqual(self.client.put(attempt['links']['self']+'/reveals/0',json={}).status_code,409)
            resumed=self.clock(snapshot,False).json()
        with self.sessions() as db:
            row=db.get(GameAttempt,attempt['attempt_id']);board=dict(row.board)
            board['outcome']='won';board['finished_at']=(start+timedelta(seconds=670)).isoformat()
            board['revealed']=sorted(set(range(100))-set(board['mine_indices']));row.board=board;db.commit()
        saved=self.client.put(attempt['links']['completion'],json={}).json()
        self.assertEqual((saved['duration_ms'],saved['stars']),(70000,3))
        self.assertEqual(resumed['timing']['paused_ms'],600000)

    def test_retry_stale_pause_and_other_account(self):
        """刷新后继续会提升时钟修订，迟到的离开请求不得再次暂停。"""
        attempt=self.start();key=str(uuid4())
        first=self.clock(attempt,True,key=key)
        self.assertEqual(first.status_code,200,first.text)
        repeat=self.clock(attempt,True,key=key)
        self.assertEqual(first.json()['timing']['revision'],repeat.json()['timing']['revision'])
        resumed=self.clock(first.json(),False).json()
        self.assertEqual(self.clock(attempt,True).status_code,409)
        self.assertFalse(self.client.get(attempt['links']['self']).json()['timing']['paused'])
        self.client.cookies.set(self.settings.session_cookie_name,'2')
        self.assertEqual(self.clock(resumed,True).status_code,404)

    def test_legacy_board_and_terminal_clock_do_not_change_result(self):
        """缺少计时字段的旧存档默认正常计时，失败后不能通过时钟修改终盘。"""
        attempt=self.start()
        with self.sessions() as db:
            row=db.get(GameAttempt,attempt['attempt_id']);row.board={k:v for k,v in row.board.items() if not k.startswith('clock_')};db.commit()
        self.assertFalse(self.client.get(attempt['links']['self']).json()['timing']['paused'])
        with self.sessions() as db:
            row=db.get(GameAttempt,attempt['attempt_id']);row.status='lost';row.ended_at=utc_now();board=dict(row.board);board['outcome']='lost';row.board=board;db.commit()
        before=self.client.get(attempt['links']['self']).json()['timing']['elapsed_ms']
        self.assertEqual(self.clock(attempt,True).json()['timing']['elapsed_ms'],before)
