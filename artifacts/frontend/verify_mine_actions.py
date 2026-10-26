"""作用：独立Chrome及临时SQLite验证四个操作按钮、重返通关关卡及重新挑战。

全部账号和棋盘仅位于临时测试库；服务端真实揭格和结算，不连接现有预览库或服务器。
"""
import base64
from pathlib import Path
import json
import socket
import tempfile
import threading
import time
from sqlalchemy import select
from verify_sudoku import environment
from verify_progress import browser
import verify_ranking as qa
from backend.app.models.entities.progression import GameAttempt, PlayerEnergy
from backend.app.services import progression_service


def main():
    """通过真实按钮和HTTP请求验证，不调用前端控制器的内部方法。"""
    checks = []
    with tempfile.TemporaryDirectory(prefix='mine-mobile-') as temporary:
        engine, sessions = environment(Path(temporary) / 'qa.sqlite')
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        base = f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server = qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app, log_level='error', lifespan='off'))
        worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(.04)
            assert server.started
            with (qa.OUTPUT / 'mine-actions-chrome.log').open('w', encoding='utf-8') as log, browser(str(Path(temporary) / 'chrome'), log) as (cmd, ev):
                def wait(expression):
                    """有界等待；失败只输出条件及游戏内提示。"""
                    for _ in range(250):
                        if ev(f'(()=>{{try{{return Boolean({expression})}}catch{{return false}}}})()'):
                            return
                        time.sleep(.04)
                    shot('mine-actions-failure.png')
                    raise AssertionError((expression, ev("({message:document.querySelector('#mine-message')?.textContent,status:document.querySelector('#mine-result-description')?.textContent,board:document.querySelector('#mine-board')?.getBoundingClientRect().toJSON(),viewport:[innerWidth,innerHeight],play:document.querySelector('#mine-play')?.getBoundingClientRect().toJSON()})")))

                def click(selector):
                    """只点击真实可见且未禁用的产品按钮。"""
                    encoded = json.dumps(selector)
                    wait(f'document.querySelector({encoded})?.getClientRects().length&&!document.querySelector({encoded}).disabled')
                    ev(f'document.querySelector({encoded}).click()')

                def attempt():
                    """只读本轮隔离库的最新尝试，定位雷区和服务端计时。"""
                    with sessions() as db:
                        return db.scalar(select(GameAttempt).order_by(GameAttempt.started_at.desc()))

                def paused(value):
                    """核对暂停已写到服务端，而不只检查本地标签。"""
                    for _ in range(150):
                        if bool(attempt().board.get('clock_paused_at')) is value:
                            return
                        time.sleep(.04)
                    raise AssertionError('server clock pause mismatch')

                def shot(name):
                    """保存原始视口截图，供布局视觉核对。"""
                    (qa.OUTPUT / name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot', {'format': 'png'})['data']))

                def reveal(index):
                    """通过先点选后排雷发出真实揭格请求。"""
                    click(f'#mine-board [data-index="{index}"]')
                    click('#mine-reveal')

                cmd('Page.addScriptToEvaluateOnNewDocument', {'source':"window.mineErrors=[];addEventListener('error',e=>mineErrors.push(e.message));addEventListener('unhandledrejection',e=>mineErrors.push(String(e.reason?.stack||e.reason)))"})
                cmd('Page.enable')
                cmd('Network.enable')
                cmd('Emulation.setDeviceMetricsOverride', {'width': 375, 'height': 667, 'deviceScaleFactor': 1, 'mobile': False})
                cmd('Page.navigate', {'url': base + 'journey.html?game_id=mine'})
                wait("document.querySelector('.auth-open')")
                click('.auth-open')
                ev("document.querySelector('#auth-username').value='扫雷操作验收';document.querySelector('#auth-password').value='mine-mobile-test';document.querySelector('.auth-submit').click()")
                wait("!document.querySelector('.auth-user').classList.contains('hidden')")
                wait("document.querySelector('#journey-status').textContent==='账号资料已同步。'")
                # 登录后的目录重读完成后再进入关卡，避免点击旧游客目录的瞬时节点。
                time.sleep(.25)
                wait("document.querySelector('#mine-specs [data-level=\"mine-v2-easy-10\"]:not(:disabled)')")
                click('#mine-specs [data-level="mine-v2-easy-10"]')
                click('#mine-enter-confirm')
                wait("document.querySelectorAll('.mine-square').length===100&&!document.querySelector('#mine-restart').disabled")
                assert ev("[...document.querySelectorAll('.mine-operation button')].map(b=>b.textContent).join(',')") == '标记,排雷,标记,排雷'
                assert ev("[...document.querySelectorAll('.mine-operation button')].every(b=>b.disabled)")
                click('#mine-board [data-index="5"]')
                click('#mine-flag-right')
                wait("document.querySelector('#mine-board [data-index=\"5\"]').classList.contains('mine-flagged')")
                assert ev("[...document.querySelectorAll('[data-mine-action=\"flag\"]')].every(b=>b.textContent==='取消标记'&&!b.disabled)")
                assert ev("[...document.querySelectorAll('[data-mine-action=\"reveal\"]')].every(b=>b.disabled)")
                for width in (320,375,430,844):
                    cmd('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 780, 'deviceScaleFactor': 1, 'mobile': True})
                    time.sleep(.08)
                    assert ev("(()=>{const b=[...document.querySelectorAll('.mine-operation button')],r=b.map(n=>n.getBoundingClientRect());return r.length===4&&r.every(v=>Math.abs(v.top-r[0].top)<1&&v.height>=44&&v.left>=0&&v.right<=innerWidth)&&b.every(n=>n.scrollWidth<=n.clientWidth+1)})()"), (width,ev("[...document.querySelectorAll('.mine-operation button')].map(n=>({rect:n.getBoundingClientRect().toJSON(),scroll:n.scrollWidth,client:n.clientWidth}))"))
                    shot(f'mine-four-actions-{width}.png')
                click('#mine-flag')
                wait("!document.querySelector('#mine-board [data-index=\"5\"]').classList.contains('mine-flagged')")
                click('#mine-flag')
                wait("document.querySelector('#mine-board [data-index=\"5\"]').classList.contains('mine-flagged')")
                click('#mine-flag-right')
                wait("!document.querySelector('#mine-board [data-index=\"5\"]').classList.contains('mine-flagged')")
                checks.append('四按钮依次标记/排雷/标记/排雷；两侧标记同步取消及禁用，四种宽度不换行')
                click('#mine-board [data-index="0"]')
                click('#mine-reveal-right')
                wait("document.querySelector('#mine-board [data-index=\"0\"]').classList.contains('mine-open')")
                row=attempt()
                mines=set(row.board['mine_indices'])
                safe=[index for index in range(100) if index not in mines]
                target=next(index for index in reversed(safe) if any(abs(index//10-m//10)<=1 and abs(index%10-m%10)<=1 for m in mines))
                # 只在临时数据库准备合法近终盘，最终一步仍经真实排雷与结算接口。
                with sessions() as db:
                    current=db.get(GameAttempt,row.attempt_id);board=dict(current.board)
                    board['revealed']=sorted(index for index in safe if index!=target)
                    current.board=board;db.commit()
                cmd('Page.reload')
                wait("document.querySelector('#mine-left')?.textContent==='1'&&!document.querySelector('#mine-restart').disabled")
                reveal(target)
                wait("document.querySelector('#mine-result').open&&!document.querySelector('#mine-next').disabled")
                assert ev("document.querySelector('#mine-next').textContent") == '重新挑战'
                checks.append('左右排雷执行真实揭格，刚通关弹窗显示重新挑战')
                click('#mine-result-back')
                click('#mine-specs [data-level="mine-v2-easy-10"]')
                click('#mine-enter-confirm')
                wait("document.querySelector('#mine-result').open&&!document.querySelector('#mine-next').disabled")
                assert ev("document.querySelector('#mine-next').textContent") == '重新挑战'
                cmd('Emulation.setDeviceMetricsOverride', {'width': 375, 'height': 780, 'deviceScaleFactor': 1, 'mobile': True})
                shot('mine-restored-rechallenge.png')
                original=attempt()
                # 临时账号体力耗尽时，重开失败应保留已保存成绩与原通关弹窗。
                with sessions() as db:
                    energy=db.scalar(select(PlayerEnergy));energy.current=0;energy.recovery_at=None;db.commit()
                click('#mine-next')
                wait("document.querySelector('.energy-empty-notice')&&!document.querySelector('#mine-next').disabled")
                assert attempt().attempt_id==original.attempt_id
                assert ev("document.querySelector('#mine-result').open")
                checks.append('零体力重新挑战保留原通关弹窗和成绩，可再次尝试')
                with sessions() as db:
                    energy=db.scalar(select(PlayerEnergy));energy.current=5;db.commit()
                click('#mine-next')
                wait("!document.querySelector('#mine-result').open&&!document.querySelector('#mine-restart').disabled&&document.querySelector('#mine-left').textContent==='90'")
                retried=attempt()
                assert retried.attempt_id!=original.attempt_id and retried.level_id==original.level_id
                assert ev("document.querySelectorAll('.mine-open').length===0")
                checks.append('重新进入已通关关卡显示重新挑战，点击创建同关新棋盘并清空已揭格')
                reveal(0)
                wait("document.querySelector('#mine-board [data-index=\"0\"]').classList.contains('mine-open')&&!document.querySelector('#mine-restart').disabled")
                row=attempt();mines=set(row.board['mine_indices'])
                safe=[index for index in range(100) if index not in mines]
                target=next(index for index in reversed(safe) if any(abs(index//10-m//10)<=1 and abs(index%10-m%10)<=1 for m in mines))
                with sessions() as db:
                    current=db.get(GameAttempt,row.attempt_id);board=dict(current.board)
                    board['revealed']=sorted(index for index in safe if index!=target)
                    current.board=board;db.commit()
                cmd('Page.reload')
                wait("document.querySelector('#mine-left')?.textContent==='1'&&!document.querySelector('#mine-restart').disabled")
                reveal(target)
                wait("document.querySelector('#mine-result').open&&!document.querySelector('#mine-next').disabled")
                original=attempt()
                click('#mine-next')
                wait("!document.querySelector('#mine-result').open&&!document.querySelector('#mine-restart').disabled&&document.querySelector('#mine-left').textContent==='90'")
                assert attempt().level_id==original.level_id and attempt().attempt_id!=original.attempt_id
                checks.append('刚通关直接点击重新挑战，同样创建当前关卡的新尝试')
                assert ev('mineErrors')==[], ev('mineErrors')
                print(json.dumps({'checks':len(checks),'failures':0,'details':checks},ensure_ascii=False))
        finally:
            server.should_exit=True;worker.join(10)
            qa.api.app.dependency_overrides.clear();engine.dispose()


if __name__=='__main__':
    main()
