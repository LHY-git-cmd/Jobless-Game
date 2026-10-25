"""作用：独立Chrome及临时SQLite验证扫雷手机布局、爆炸中重开、设置暂停和通关弹窗。

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
from backend.app.models.entities.progression import GameAttempt
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
            with (qa.OUTPUT / 'mine-mobile-play-chrome.log').open('w', encoding='utf-8') as log, browser(str(Path(temporary) / 'chrome'), log) as (cmd, ev):
                def wait(expression):
                    """有界等待；失败只输出条件及游戏内提示。"""
                    for _ in range(250):
                        if ev(f'(()=>{{try{{return Boolean({expression})}}catch{{return false}}}})()'):
                            return
                        time.sleep(.04)
                    shot('mine-compact-failure.png')
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
                ev("document.querySelector('#auth-username').value='手机扫雷';document.querySelector('#auth-password').value='mine-mobile-test';document.querySelector('.auth-submit').click()")
                wait("!document.querySelector('.auth-user').classList.contains('hidden')")
                wait("document.querySelector('#journey-status').textContent==='账号资料已同步。'")
                # 登录后的目录重读完成后再进入关卡，避免点击旧游客目录的瞬时节点。
                time.sleep(.25)
                wait("document.querySelector('#mine-specs [data-level=\"mine-v2-easy-10\"]:not(:disabled)')")
                click('#mine-specs [data-level="mine-v2-easy-10"]')
                click('#mine-enter-confirm')
                wait("document.querySelectorAll('.mine-square').length===100&&!document.querySelector('#mine-restart').disabled")
                assert ev("!document.querySelector('#mine-rules')&&!document.querySelector('#mine-sound')&&!document.querySelector('.mine-game-brand')"), '绿圈区域仍在游戏面板中'
                checks.append('移除图标、规则及独立音效区')
                for width, height in ((320, 568), (375, 667), (430, 780), (844, 390)):
                    cmd('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False})
                    ev("document.querySelector('#mine-play').scrollIntoView({block:'start',behavior:'instant'})")
                    if height > width:
                        wait("(()=>{const b=document.querySelector('#mine-board').getBoundingClientRect();return b.top>=-1&&b.bottom<=innerHeight+1&&b.left>=0&&b.right<=innerWidth})()")
                    assert ev("document.querySelector('#mine-viewport').scrollWidth<=document.querySelector('#mine-viewport').clientWidth")
                    assert ev("document.querySelector('.mine-square').getBoundingClientRect().width>=24")
                    shot(f'mine-compact-{width}.png')
                checks.append('320/375/430竖屏10×10棋盘完整可见，短横屏保持可点选并允许滚动')
                cmd('Emulation.setDeviceMetricsOverride', {'width': 375, 'height': 667, 'deviceScaleFactor': 1, 'mobile': False})
                initial = attempt().attempt_id
                reveal(0)
                wait("document.querySelector('#mine-board [data-index=\"0\"]').classList.contains('mine-open')&&!document.querySelector('#mine-restart').disabled")
                row = attempt()
                remaining = 90 - len(row.board['revealed'])
                assert ev("document.querySelector('#mine-left').textContent") == str(remaining)
                mine = row.board['mine_indices'][0]
                click(f'#mine-board [data-index="{mine}"]')
                click('#mine-flag')
                assert ev("document.querySelector('#mine-left').textContent") == str(remaining)
                click('#mine-flag')
                reveal(mine)
                wait("document.querySelector('.mine-visible')&&!document.querySelector('#mine-restart').disabled")
                assert ev("!!document.querySelector('.mine-blasting')"), '未在爆炸时间线内验证重开'
                click('#mine-restart')
                assert not ev("document.querySelector('#mine-restart-dialog').open"), '踩雷重开不应再次确认'
                wait("document.querySelectorAll('.mine-square').length===100&&!document.querySelector('#mine-restart').disabled&&!document.querySelector('.mine-visible')")
                assert attempt().attempt_id != initial
                check_row = attempt()
                time.sleep(.25)
                assert not ev("!!document.querySelector('.mine-visible')"), '旧爆炸回调污染新棋盘'
                checks.append('安全格计数不受标旗影响；爆炸中立即重开且旧动画不污染新局')
                click('#mine-restart')
                wait("document.querySelector('#mine-restart-dialog').open")
                click('#mine-restart-cancel')
                assert attempt().attempt_id == check_row.attempt_id
                checks.append('进行中的重开仍需确认，取消保留原局')
                click('#mine-settings')
                wait("document.querySelector('#game-settings').open")
                paused(True)
                frozen = ev("document.querySelector('#mine-clock').textContent")
                time.sleep(1.1)
                assert ev("document.querySelector('#mine-clock').textContent") == frozen
                assert ev("document.querySelectorAll('.mine-square:not(:disabled)').length===0")
                shot('mine-compact-settings.png')
                cmd('Input.dispatchKeyEvent', {'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
                wait("!document.querySelector('#game-settings').open")
                paused(False)
                assert ev("document.activeElement.id") == 'mine-settings'
                click('.auth-settings')
                paused(True)
                click('.settings-close')
                paused(False)
                checks.append('面板及顶部设置均暂停服务端时钟，关闭/ESC后继续')
                click('#mine-settings')
                paused(True)
                target_id=cmd('Target.getTargetInfo')['targetInfo']['targetId']
                other_id=cmd('Target.createTarget',{'url':'about:blank'})['targetId']
                cmd('Target.activateTarget',{'targetId':other_id})
                wait('document.hidden')
                click('.settings-close')
                time.sleep(.15)
                assert bool(attempt().board.get('clock_paused_at'))
                cmd('Target.activateTarget',{'targetId':target_id})
                wait('!document.hidden')
                paused(False)
                cmd('Target.closeTarget',{'targetId':other_id})
                checks.append('设置与后台暂停叠加，关闭设置不能解除后台暂停')
                # 接近终盘夹具只写临时库的合法已揭安全格；最终格仍经真实HTTP揭格、结算。
                reveal(0)
                wait("document.querySelector('#mine-board [data-index=\"0\"]').classList.contains('mine-open')")
                row = attempt()
                mines = set(row.board['mine_indices'])
                safe = [index for index in range(100) if index not in mines]
                target = next(index for index in reversed(safe) if any(abs(index//10-m//10)<=1 and abs(index%10-m%10)<=1 for m in mines))
                with sessions() as db:
                    current = db.get(GameAttempt, row.attempt_id)
                    board = dict(current.board)
                    board['revealed'] = sorted(index for index in safe if index!=target)
                    current.board = board
                    db.commit()
                cmd('Page.reload')
                wait("document.querySelector('#mine-left')?.textContent==='1'&&!document.querySelector('#mine-restart').disabled")
                cmd('Network.setBlockedURLs', {'urls':['*/completion']})
                reveal(target)
                wait("document.querySelector('#mine-result').open&&!document.querySelector('#mine-retry-settlement').hidden")
                assert ev("document.querySelector('#mine-next').disabled")
                assert ev("!document.querySelector('#mine-play #mine-result')"), '通关信息不应位于棋盘下方'
                cmd('Network.setBlockedURLs', {'urls':[]})
                click('#mine-retry-settlement')
                wait("!document.querySelector('#mine-next').disabled")
                assert ev("document.querySelector('#mine-left').textContent") == '0'
                assert '15' in ev("document.querySelector('#mine-next').textContent")
                shot('mine-compact-result.png')
                checks.append('通关弹窗保存失败可重试，保存后显示奖励及下一关，棋盘下无通关卡片')
                click('#mine-next')
                wait("document.querySelectorAll('.mine-square').length===180&&!document.querySelector('#mine-restart').disabled")
                assert attempt().level_id == 'mine-v2-easy-15'
                assert ev("document.querySelector('.mine-square').getBoundingClientRect().width") == 44
                assert ev("document.querySelector('#mine-viewport').scrollWidth>document.querySelector('#mine-viewport').clientWidth")
                shot('mine-compact-large.png')
                checks.append('下一关进入同难度15×12，大棋盘保留44px格子及滚动')
                click('#mine-back')
                click('[data-exit-confirm]')
                wait("!document.querySelector('#mine-selector').hidden")
                click('#mine-difficulties [data-difficulty="hell"]')
                click('#mine-specs [data-level="mine-v2-hell-20"]')
                click('#mine-enter-confirm')
                wait("document.querySelectorAll('.mine-square').length===300&&!document.querySelector('#mine-restart').disabled")
                reveal(0)
                wait("document.querySelector('#mine-board [data-index=\"0\"]').classList.contains('mine-open')")
                row=attempt()
                mines=set(row.board['mine_indices'])
                safe=[index for index in range(300) if index not in mines]
                final=next(index for index in reversed(safe) if any(abs(index//20-m//20)<=1 and abs(index%20-m%20)<=1 for m in mines))
                with sessions() as db:
                    current=db.get(GameAttempt,row.attempt_id);board=dict(current.board)
                    board['revealed']=sorted(index for index in safe if index!=final)
                    current.board=board;db.commit()
                cmd('Page.reload')
                wait("document.querySelector('#mine-left')?.textContent==='1'&&!document.querySelector('#mine-restart').disabled")
                cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
                reveal(final)
                wait("document.querySelector('#mine-result').open&&!document.querySelector('#mine-next').disabled")
                assert '最后一关' in ev("document.querySelector('#mine-next').textContent")
                click('#mine-next')
                wait("!document.querySelector('#mine-selector').hidden&&!document.querySelector('#mine-result').open")
                checks.append('最后一关结算后返回选关，减少动画模式正常')
                click('#mine-difficulties [data-difficulty="easy"]')
                click('#mine-specs [data-level="mine-v2-easy-10"]')
                click('#mine-enter-confirm')
                wait("document.querySelector('#mine-result').open&&!document.querySelector('#mine-result-back').disabled")
                click('#mine-result-back')
                wait("!document.querySelector('#mine-selector').hidden&&!document.querySelector('#mine-result').open")
                checks.append('已保存的通关结果恢复后可直接返回选关')
                assert not ev('window.mineErrors'), ev('window.mineErrors')
                print(json.dumps({'checks_passed':len(checks),'checks':checks}, ensure_ascii=False))
        finally:
            server.should_exit = True
            worker.join(5)
            qa.api.app.dependency_overrides.clear()
            engine.dispose()


if __name__ == '__main__':
    main()
