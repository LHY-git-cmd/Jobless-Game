"""作用：独立真实Chrome验证数独键盘、冲突、暂停/离页、重开和换号，不重复13题通关。"""
import base64
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from verify_sudoku import environment,qa,browser,GameAttempt,select,solutions,LEVELS


def main():
    """全部操作只访问临时库和本机页面，读取服务器暂停状态验证实际持久化。"""
    checks=[]
    with tempfile.TemporaryDirectory(prefix='sudoku-interactions-') as temp:
        engine,sessions=environment(Path(temp)/'qa.sqlite')
        listener=socket.socket();listener.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        try:
            for _ in range(200):
                if server.started:break
                time.sleep(.05)
            assert server.started
            with (qa.OUTPUT/'sudoku-interactions-chrome.log').open('w',encoding='utf-8') as log,browser(str(Path(temp)/'chrome'),log) as (cmd,ev):
                def wait(expression,seconds=12):
                    """有界等候失败只报告条件及游戏反馈。"""
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:
                        if ev(f'(()=>{{try{{return Boolean({expression});}}catch{{return false;}}}})()'):return
                        time.sleep(.03)
                    raise AssertionError((expression,ev("document.getElementById('sudoku-message')?.textContent")))

                def click(selector):
                    """仅点击可见可用的产品按钮。"""
                    literal=json.dumps(selector)
                    wait(f"(()=>{{const n=document.querySelector({literal});return n&&!n.disabled&&n.getClientRects().length;}})()")
                    ev(f'document.querySelector({literal}).click()')

                def row():
                    """只读隔离库的最新数独局，不连接业务库。"""
                    with sessions() as db:return db.scalar(select(GameAttempt).where(GameAttempt.game_id=='sudoku').order_by(GameAttempt.started_at.desc()))

                def paused(value):
                    """同时检查时钟状态已到达服务端，不以本地文字代替。"""
                    deadline=time.monotonic()+10
                    while time.monotonic()<deadline:
                        if bool(row().board.get('clock_paused_at'))==value:return
                        time.sleep(.03)
                    raise AssertionError('server pause mismatch')

                def key(value,code=None):
                    """真实键盘事件用于检查焦点保留和数字处理。"""
                    cmd('Input.dispatchKeyEvent',{'type':'keyDown','key':value,'code':code or ('Digit'+value if value.isdigit() else value),'windowsVirtualKeyCode':ord(value) if len(value)==1 else {'Delete':46,'ArrowRight':39,'ArrowDown':40,'Escape':27}.get(value,0)})
                    cmd('Input.dispatchKeyEvent',{'type':'keyUp','key':value,'code':code or value})

                def login(name):
                    """只在隔离环境创建验收账号，密码不进入业务环境。"""
                    ev(f"document.getElementById('auth-username').value={json.dumps(name)};document.getElementById('auth-password').value='sudoku-interactions-test';document.querySelector('.auth-submit').click()")

                cmd('Page.enable');cmd('Network.enable');cmd('Page.navigate',{'url':base+'journey.html?game_id=sudoku'})
                wait("!document.getElementById('sudoku-start').disabled");click('#sudoku-start');wait("document.getElementById('auth-dialog').open")
                login('数独交互甲')
                wait("document.querySelectorAll('#sudoku-board .sudoku-cell').length===81 && !document.getElementById('sudoku-restart').disabled")
                assert ev("!document.getElementById('sudoku-description') && document.getElementById('sudoku-difficulty-label').textContent==='简单'")
                assert ev("document.getElementById('sudoku-undo').disabled")
                attempt=row();original=attempt.attempt_id;puzzle=attempt.board
                givens=LEVELS[attempt.level_id]['puzzle']['values'];blank=next(i for i,v in enumerate(givens) if not v)
                same_row=[v for i,v in enumerate(givens) if i//9==blank//9 and v];duplicate=same_row[0]
                click(f'#sudoku-board [data-index="{blank}"]');ev(f'document.querySelector(\'#sudoku-board [data-index="{blank}"]\').focus()');key(str(duplicate))
                wait("document.querySelectorAll('#sudoku-board .conflict').length>=2")
                assert ev('document.activeElement.dataset.index')==str(blank),'键盘输入重绘后必须保留格子焦点'
                assert ev("document.querySelectorAll('#sudoku-board .same-value').length>=2")
                assert ev("document.querySelector('#sudoku-board .conflict').getAttribute('aria-label').includes('存在重复')")
                (qa.OUTPUT/'sudoku-conflict-desktop.png').write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data']))
                key('Delete');wait("document.querySelectorAll('#sudoku-board .conflict').length===0")
                click('#sudoku-undo');wait("document.querySelectorAll('#sudoku-board .conflict').length>=2")
                click('#sudoku-undo');wait("document.querySelectorAll('#sudoku-board .conflict').length===0 && document.getElementById('sudoku-undo').disabled")
                # 重建后实际焦点仍是已选格，方向键不能跨越左右边界。
                ev(f'document.querySelector(\'#sudoku-board [data-index="{blank}"]\').focus()');key('ArrowRight')
                expected=blank+1 if blank%9<8 else blank
                assert ev('document.activeElement.dataset.index')==str(expected)
                given=next(i for i,v in enumerate(givens) if v)
                click(f'#sudoku-board [data-index="{given}"]');key('9')
                assert ev(f'document.querySelector(\'#sudoku-board [data-index="{given}"]\').textContent')==str(givens[given])
                checks.append('键盘填数/删除/方向焦点、题目数字保护、同数与冲突高亮')

                click(f'#sudoku-board [data-index="{blank}"]');click('#sudoku-notes')
                note_on=ev("getComputedStyle(document.getElementById('sudoku-notes')).backgroundColor")
                click('#sudoku-keypad [data-digit="2"]');wait("!document.getElementById('sudoku-restart').disabled")
                cmd('Page.reload');wait("document.querySelector('#sudoku-notes')?.textContent==='笔记：开' && !document.getElementById('sudoku-undo').disabled")
                click('#sudoku-undo');wait("document.querySelectorAll('#sudoku-board .sudoku-notes').length===0")
                click('#sudoku-notes');assert ev("getComputedStyle(document.getElementById('sudoku-notes')).backgroundColor")!=note_on
                for width,height in [(1440,1100),(375,1100),(320,1000)]:
                    cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<700})
                    assert ev('document.documentElement.scrollWidth<=innerWidth'),width
                    assert ev("(()=>{const a=document.querySelector('.auth-controls').getBoundingClientRect(),p=document.querySelector('.player-profile').getBoundingClientRect(),n=document.querySelector('.auth-username').getBoundingClientRect(),s=document.querySelector('.player-stars').getBoundingClientRect();return a.top<=p.top+1 && a.right<=innerWidth && n.right<=a.left && s.right<=a.left;})()"),'账号操作应位于首行右侧且不遮挡资料'
                    assert ev("(()=>{const s=document.querySelector('.sudoku-available').getBoundingClientRect(),t=document.querySelector('.sudoku-toolbar').getBoundingClientRect();return Math.abs(s.left+s.width/2-t.left-t.width/2)<1;})()"),'星级保持居中'
                    ev("window.scrollTo({top:0,behavior:'instant'})")
                    (qa.OUTPUT/f'sudoku-header-{width}.png').write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data']))
                    ev("document.querySelector('.sudoku-input').scrollIntoView({block:'end',behavior:'instant'})")
                    (qa.OUTPUT/f'sudoku-undo-{width}.png').write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data']))
                checks.append('难度位置/说明移除、连续撤回和刷新后撤回、笔记开关颜色及320/375px右上账号布局')

                click('#sudoku-pause-toggle');paused(True)
                cmd('Page.reload');wait("!document.getElementById('sudoku-pause').hidden && !document.getElementById('sudoku-clock-retry').disabled");paused(True)
                click('#sudoku-clock-retry');paused(False)
                target=cmd('Target.getTargetInfo')['targetInfo']['targetId'];other=cmd('Target.createTarget',{'url':'about:blank'})['targetId']
                cmd('Target.activateTarget',{'targetId':other});wait('document.hidden');paused(True)
                cmd('Target.activateTarget',{'targetId':target});wait('!document.hidden');paused(False);cmd('Target.closeTarget',{'targetId':other})
                click('#sudoku-back');paused(True);time.sleep(.3);click('#sudoku-start')
                wait("!document.getElementById('sudoku-play').hidden && !document.getElementById('sudoku-restart').disabled");paused(False)
                assert row().attempt_id==original
                cmd('Page.navigate',{'url':base+'index.html'});wait("location.pathname==='/index.html'");paused(True)
                cmd('Page.navigate',{'url':base+'journey.html?game_id=sudoku'})
                wait("document.querySelectorAll('#sudoku-board .sudoku-cell').length===81 && !document.getElementById('sudoku-restart').disabled");paused(False)
                assert row().attempt_id==original
                checks.append('真实标签切换、返回选关、跨页keepalive暂停及同局恢复')

                click(f'#sudoku-board [data-index="{blank}"]');click('#sudoku-notes');click('#sudoku-keypad [data-digit="2"]')
                wait("!document.getElementById('sudoku-restart').disabled");click('#sudoku-restart');paused(True);click('#sudoku-restart-cancel');paused(False)
                assert ev(f'document.querySelector(\'#sudoku-board [data-index="{blank}"] .sudoku-notes\')!==null')
                click('#sudoku-restart');click('#sudoku-restart-confirm')
                wait("!document.getElementById('sudoku-restart').disabled && document.querySelectorAll('#sudoku-board .sudoku-notes').length===0")
                assert row().attempt_id!=original
                with sessions() as db:assert db.get(GameAttempt,original).status=='abandoned'
                checks.append('取消重开保留笔记，确认重开仅放弃当前局并恢复计时')

                # 暂停请求失败时必须禁用棋盘，恢复网络后原命令可重放。
                cmd('Network.setBlockedURLs',{'urls':['*/api/v1/attempts/*/clock']});click('#sudoku-pause-toggle')
                wait("document.getElementById('sudoku-message').textContent.includes('连接失败')")
                assert ev("!document.getElementById('sudoku-pause').hidden")
                cmd('Network.setBlockedURLs',{'urls':[]});click('#sudoku-clock-retry');wait("document.getElementById('sudoku-pause').hidden");paused(False)
                checks.append('暂停网络失败禁用输入，恢复网络可继续原局')

                cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
                click(f'#sudoku-board [data-index="{blank}"]');click('#sudoku-notes');click('#sudoku-keypad [data-digit="3"]')
                wait("!document.getElementById('sudoku-restart').disabled")
                assert ev(f'document.querySelector(\'#sudoku-board [data-index="{blank}"] .sudoku-notes\')!==null')
                click('.auth-logout');wait("!document.querySelector('.auth-open').classList.contains('hidden')")
                assert ev("document.querySelectorAll('#sudoku-board .sudoku-cell').length===0"),'退出时必须立即移除旧账号棋盘DOM'
                click('#sudoku-start');wait("document.getElementById('auth-dialog').open");login('数独交互乙')
                wait("document.querySelectorAll('#sudoku-board .sudoku-cell').length===81 && !document.getElementById('sudoku-restart').disabled")
                assert ev("document.querySelectorAll('#sudoku-board .sudoku-notes').length===0")
                click('.auth-logout');wait("!document.querySelector('.auth-open').classList.contains('hidden')")
                click('#sudoku-start');wait("document.getElementById('auth-dialog').open");login('数独交互甲')
                wait("!document.getElementById('sudoku-play').hidden && document.querySelectorAll('#sudoku-board .sudoku-notes').length>0")
                checks.append('减少动画可操作，退出/换号隔离草稿，换回账号恢复笔记')
                print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False))
        finally:
            server.should_exit=True;worker.join(timeout=5);qa.api.app.dependency_overrides.clear();engine.dispose()


if __name__=='__main__':main()
