"""作用：真实Chrome/临时SQLite验收规则、选关、标签页及离页的服务器暂停计时。

只访问隔离库。测试夹具设置暂停前的游戏时长，产品仍由服务器验证最终星级。
"""
import base64
from datetime import timedelta
import json
from pathlib import Path
import socket
import tempfile
import threading
import time

import verify_ranking as qa
from verify_progress import browser
from sqlalchemy import select
from backend.app.common.game_catalog import LEVELS
from backend.app.common.security import utc_now
from backend.app.models.entities.progression import GameLevel,GameLevelVersion,GameAttempt


def main():
    """暂停后读取时钟及服务端暂停状态，恢复后原局继续，离页请求使用真实keepalive。"""
    checks=[]
    with tempfile.TemporaryDirectory(prefix='mine-pause-browser-') as temp:
        engine=qa.create_engine('sqlite:///'+(Path(temp)/'qa.sqlite').as_posix(),connect_args={'check_same_thread':False,'timeout':10})
        qa.Base.metadata.create_all(engine);sessions=qa.sessionmaker(engine,expire_on_commit=False)
        with sessions() as db:
            for item in LEVELS.values():
                db.add(GameLevel(level_id=item['level_id'],game_id=item['game_id'],order_index=item['order']))
                db.add(GameLevelVersion(level_id=item['level_id'],level_version=1,definition=item))
            db.commit()
        def dependency():
            """独立临时数据库会话，无业务库连接。"""
            with sessions() as db:yield db
        qa.api.app.dependency_overrides[qa.get_db]=dependency
        settings=qa.get_settings();settings.progression_enabled=True;settings.cosmetics_enabled=False
        settings.pk_rooms_enabled=False;settings.matchmaking_enabled=False;settings.cookie_secure=False
        listener=socket.socket();listener.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        try:
            for _ in range(200):
                if server.started:break
                time.sleep(.05)
            assert server.started
            with (qa.OUTPUT/'mine-pause-chrome.log').open('w',encoding='utf-8') as log,browser(str(Path(temp)/'chrome'),log) as (cmd,ev):
                def wait(expression,seconds=15):
                    """有界等待只读取失败摘要。"""
                    until=time.monotonic()+seconds
                    while time.monotonic()<until:
                        if ev(f'(()=>{{try{{return Boolean({expression});}}catch{{return false;}}}})()'):return
                        time.sleep(.04)
                    raise AssertionError((expression,ev("({clock:document.getElementById('mine-clock')?.textContent,label:document.getElementById('mine-clock-label')?.textContent,message:document.getElementById('mine-message')?.textContent})")))
                def click(selector):
                    """按钮必须可见且未禁用，只走真实页面操作。"""
                    literal=json.dumps(selector)
                    wait(f"(()=>{{const node=document.querySelector({literal});return node&&!node.disabled&&node.getClientRects().length>0;}})()")
                    ev(f'document.querySelector({literal}).click()')
                def row():
                    """离线读取本次隔离尝试。"""
                    with sessions() as db:return db.scalar(select(GameAttempt).order_by(GameAttempt.started_at.desc()))
                def paused(value):
                    """服务端状态必须与显示的暂停意图一致。"""
                    until=time.monotonic()+10
                    while time.monotonic()<until:
                        if bool(row().board.get('clock_paused_at'))==value:return
                        time.sleep(.04)
                    raise AssertionError('server pause mismatch')
                def reveal(index):
                    """先选后排，等待恢复按钮以确保服务器揭格完成。"""
                    click(f'#mine-board [data-index="{index}"]');click('#mine-reveal');wait("!document.getElementById('mine-restart').disabled")
                cmd('Page.enable');cmd('Network.enable')
                cmd('Page.navigate',{'url':base+'journey.html?game_id=mine'})
                wait("!document.getElementById('mine-start').disabled")
                click('#mine-start');wait("!document.getElementById('auth-dialog').classList.contains('hidden')")
                ev("document.getElementById('auth-username').value='暂停验收';document.getElementById('auth-password').value='mine-pause-test-secret';document.querySelector('.auth-submit').click()")
                wait("document.getElementById('mine-rules-dialog').open");click('#mine-rules-confirm')
                wait("document.querySelectorAll('.mine-square').length===100 && !document.getElementById('mine-restart').disabled")
                attempt_id=row().attempt_id
                wait("document.getElementById('mine-clock').textContent!=='00:00'")
                click('#mine-rules');paused(True)
                wait("document.getElementById('mine-clock-label').textContent.includes('已暂停')")
                frozen=ev("document.getElementById('mine-clock').textContent")
                time.sleep(1.3)
                assert ev("document.getElementById('mine-clock').textContent")==frozen
                assert ev("document.querySelectorAll('.mine-square:not(:disabled)').length===0")
                (qa.OUTPUT/'mine-paused-rules.png').write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data']))
                cmd('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
                wait("!document.getElementById('mine-rules-dialog').open");paused(False)
                wait("document.getElementById('mine-clock').textContent!=="+json.dumps(frozen))
                checks.append('打开规则冻结时间/星级并禁用棋盘，Esc关闭后恢复')
                click('#mine-rules');paused(True);click('#mine-rules-confirm');paused(False)
                checks.append('规则继续按钮正确恢复服务器时钟')
                click('#mine-back');paused(True)
                before=row().board['clock_paused_at'];time.sleep(1.2)
                assert row().board['clock_paused_at']==before
                click('#mine-start');wait("!document.getElementById('mine-play').hidden");paused(False)
                assert row().attempt_id==attempt_id
                checks.append('返回选关停止计时，继续原关不重开且扣除停留时间')
                target=cmd('Target.getTargetInfo')['targetInfo']['targetId']
                other=cmd('Target.createTarget',{'url':'about:blank'})['targetId'];cmd('Target.activateTarget',{'targetId':other})
                wait('document.hidden');paused(True);time.sleep(1.2)
                cmd('Target.activateTarget',{'targetId':target});wait('!document.hidden');paused(False)
                cmd('Target.closeTarget',{'targetId':other})
                checks.append('真实切换标签页后台暂停，回到游戏继续')
                cmd('Page.navigate',{'url':base+'index.html'});wait("location.pathname==='/index.html'");paused(True)
                time.sleep(1.2);assert row().attempt_id==attempt_id
                cmd('Page.navigate',{'url':base+'journey.html?game_id=mine'})
                wait("document.querySelectorAll('.mine-square').length===100 && !document.getElementById('mine-restart').disabled");paused(False)
                assert row().attempt_id==attempt_id
                cmd('Page.reload');wait("document.querySelectorAll('.mine-square').length===100 && !document.getElementById('mine-restart').disabled");paused(False)
                checks.append('跨页离开keepalive暂停，返回/刷新恢复同一棋局')
                # 将纯活动时间设为约70秒，已暂停区间仍由服务器累计，用于核对三星结算。
                with sessions() as db:
                    current=db.get(GameAttempt,attempt_id)
                    current.started_at=utc_now()-timedelta(milliseconds=70000+current.board.get('clock_paused_ms',0));db.commit()
                cmd('Page.reload');wait("document.querySelectorAll('.mine-square').length===100 && !document.getElementById('mine-restart').disabled")
                click('#mine-rules');paused(True);time.sleep(2.5);click('#mine-rules-confirm');paused(False)
                reveal(0)
                mines=set(row().board['mine_indices'])
                for index in range(100):
                    if index not in mines and not ev(f'document.querySelector(\'#mine-board [data-index="{index}"]\').hasAttribute("data-number")'):reveal(index)
                wait("document.getElementById('mine-result-kicker').textContent==='本关成绩已保存'")
                assert ev("document.getElementById('mine-result-stars').dataset.stars==='3'")
                checks.append('结算扣除全部暂停区间，时间与三星评价同源')
        finally:
            server.should_exit=True;worker.join(timeout=10);listener.close();qa.api.app.dependency_overrides.clear();engine.dispose()
    print(json.dumps({'checks_passed':len(checks),'checks':checks,'uncaught_errors':0},ensure_ascii=False))


if __name__=='__main__':main()
