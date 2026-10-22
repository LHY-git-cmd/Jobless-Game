"""作用：在独立Chrome和临时SQLite内验收照明16关、教学、续玩、断网及窄屏。

标准答案只由测试进程离线求解；产品页面经真实点击和API完成，不向产品注入答案。
"""
import base64
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from sqlalchemy import select
import verify_ranking as qa
from verify_progress import browser
from verify_sudoku import environment
from backend.app.common.game_catalog import AKARI_LEVELS
from backend.app.models.entities.progression import PlayerProgression
from backend.app.services import progression_service
from backend.content_check import akari_solutions


def main():
    """只操作本次创建的临时服务和浏览器；结果输出统计及截图。"""
    checks=[]
    with tempfile.TemporaryDirectory(prefix='akari-levels-qa-') as temporary:
        engine,sessions=environment(Path(temporary)/'qa.sqlite')
        listener=socket.socket();listener.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        try:
            deadline=time.monotonic()+10
            while not server.started and time.monotonic()<deadline:time.sleep(.05)
            assert server.started
            with (qa.OUTPUT/'akari-levels-chrome.log').open('w',encoding='utf-8') as log,browser(str(Path(temporary)/'chrome'),log) as (cmd,ev):
                def wait(expression,seconds=12):
                    """有界等待真实页面状态，失败只附带状态文本。"""
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:
                        if ev(f'(()=>{{try{{return Boolean({expression});}}catch{{return false;}}}})()'):return
                        time.sleep(.025)
                    raise AssertionError((expression,ev("document.getElementById('akari-message')?.textContent")))

                def click(selector):
                    """调用实际DOM按钮监听器，不直接修改游戏状态。"""
                    literal=json.dumps(selector)
                    wait(f"(()=>{{const n=document.querySelector({literal});return n&&!n.disabled&&n.getClientRects().length;}})()")
                    ev(f'document.querySelector({literal}).click()')

                def shot(name):
                    """截图保存在忽略目录，供人工视觉复核。"""
                    (qa.OUTPUT/name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})['data']))

                def choose(level):
                    """切关本身不建局，点击开始后才进入正式尝试。"""
                    progression_service.limiter.clear()
                    if ev("!document.getElementById('akari-play').hidden"):click('#akari-back')
                    click(f'#akari-levels [data-level="{level["level_id"]}"]');click('#akari-start')
                    wait(f"document.querySelectorAll('#akari-board [data-index]').length==={level['puzzle']['rows']**2}&&!document.getElementById('akari-restart').disabled")

                def bulb(index):
                    """每次操作等待会话释放忙碌状态，最终一步由结算负责冻结。"""
                    click(f'#akari-board [data-index="{index}"]')
                    wait("!document.getElementById('akari-restart').disabled||!document.getElementById('akari-result').hidden")

                cmd('Page.enable');cmd('Network.enable');cmd('Runtime.enable')
                cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1150,'deviceScaleFactor':1,'mobile':False})
                cmd('Page.navigate',{'url':base+'journey.html?game_id=akari'})
                wait("document.querySelectorAll('#akari-levels [data-level]').length===16&&!document.getElementById('akari-start').disabled")
                assert ev("document.getElementById('akari-selector').textContent.includes('难度系数')")==False
                shot('akari-levels-desktop.png');checks.append('游客16关目录和编号，无难度系数')
                click('#akari-start');wait("!document.getElementById('auth-dialog').classList.contains('hidden')")
                ev("document.getElementById('auth-username').value='照明验收';document.getElementById('auth-password').value='akari-browser-test';document.querySelector('.auth-submit').click()")
                wait("document.querySelectorAll('#akari-board [data-index]').length===25&&!document.getElementById('akari-restart').disabled")
                assert ev("(()=>{const r=document.getElementById('akari-board').getBoundingClientRect();return Math.abs(r.width-r.height)<1;})()"),'入门应为5×5方形，不应保留旧10行'
                shot('akari-tutorial-desktop.png')
                bulb(9);assert ev("document.getElementById('akari-message').textContent.includes('高亮')")
                for step,action in enumerate(AKARI_LEVELS[0]['puzzle']['tutorial_steps'][:-1]):
                    assert ev(f'document.querySelector(\'#akari-board [data-index="{action["index"]}"]\').classList.contains("tutorial-target")')
                    bulb(action['index']);wait(f"document.getElementById('akari-guide-count').textContent.startsWith('第{step+2}步')")
                    if step==3:
                        assert ev("document.querySelectorAll('#akari-board .error.bulb').length===2")
                        assert ev("document.getElementById('akari-conflicts').textContent.includes('互相照射')")
                        shot('akari-tutorial-conflict.png')
                    if step==4:
                        assert ev("document.querySelectorAll('#akari-board .error').length===0")
                cmd('Page.reload');wait("document.getElementById('akari-guide-count').textContent.startsWith('第7步')&&!document.getElementById('akari-restart').disabled")
                assert ev("document.querySelectorAll('#akari-board .bulb').length===2")
                shot('akari-tutorial-numbers.png')
                checks.append('七步教学目标高亮、误操作阻止、实际互照/撤灯/数字墙及刷新恢复')
                for number,level in enumerate(AKARI_LEVELS):
                    if number:choose(level)
                    answer=akari_solutions(level['puzzle']['map'])[0]
                    if number==0:
                        answer=[i for i in answer if not ev(f'document.querySelector(\'#akari-board [data-index="{i}"]\').classList.contains("bulb")')]
                    if number>=10:
                        assert level['puzzle']['rows']==level['puzzle']['cols']==10
                    if number==1:
                        click('#akari-rules');wait("document.getElementById('akari-rules-dialog').open&&!document.getElementById('akari-pause').hidden")
                        frozen=ev("document.getElementById('akari-clock').textContent");time.sleep(1.1)
                        assert ev("document.getElementById('akari-clock').textContent")==frozen
                        click('#akari-rules-close');wait("document.getElementById('akari-pause').hidden")
                        checks.append('规则阅读暂停并恢复')
                    if number==3:
                        bulb(answer[0]);cmd('Page.reload')
                        wait(f'document.querySelector(\'#akari-board [data-index="{answer[0]}"]\')?.classList.contains("bulb")&&!document.getElementById("akari-restart").disabled')
                        assert ev("document.getElementById('akari-status').textContent.includes('已放灯：1')")
                        answer=answer[1:];checks.append('刷新核验正式资源并恢复同一局灯泡')
                    if number==4:
                        bulb(answer[0]);click('#akari-restart');wait("document.getElementById('akari-restart-dialog').open")
                        click('#akari-restart-confirm');wait("document.getElementById('akari-status').textContent.includes('已放灯：0')&&!document.getElementById('akari-restart').disabled")
                        checks.append('重开确认只清空当前关')
                    if number==7:
                        cmd('Network.setBlockedURLs',{'urls':['*/api/v1/attempts/*/completion']})
                    if number==15:
                        for width,height,suffix in [(1440,1150,'desktop'),(375,812,'mobile'),(320,740,'small')]:
                            cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<600})
                            ev("document.getElementById('akari-play').scrollIntoView({block:'start',behavior:'instant'})")
                            assert ev('document.documentElement.scrollWidth<=innerWidth'),f'页面溢出{width}'
                            assert ev("[...document.querySelectorAll('#akari-board button')].every(n=>{const r=n.getBoundingClientRect();return r.width>=44&&r.height>=44;})")
                            assert ev("[...document.querySelectorAll('#akari-board button')].every(n=>{const r=n.getBoundingClientRect();return Math.abs(r.width-r.height)<1;})"),'棋格必须为正方形'
                            shot(f'akari-final-{suffix}.png')
                        cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1150,'deviceScaleFactor':1,'mobile':False})
                        checks.append('10×10最终关在1440/375/320px无页面溢出，格子至少44px')
                    for index in answer:bulb(index)
                    if number==7:
                        wait("document.getElementById('akari-message').textContent.includes('连接失败')")
                        cmd('Page.reload');wait("document.getElementById('akari-message').textContent.includes('连接失败')")
                        cmd('Network.setBlockedURLs',{'urls':[]});click('#akari-retry-settlement')
                        checks.append('断网终盘刷新后以原负载重试')
                    wait("!document.getElementById('akari-result').hidden&&document.getElementById('akari-result-title').textContent.includes('点亮')")
                    if number==0:
                        shot('akari-tutorial-complete.png')
                    assert ev("document.querySelectorAll('#akari-board button:not(:disabled)').length===0")
                    checks.append(f'{level["name"]}真实点击完成及服务器结算')
                shot('akari-final-complete.png')
                assert ev("document.getElementById('akari-result-title').textContent.includes('全部点亮')")
                click('#akari-next');wait("!document.getElementById('akari-selector').hidden")
                choose(AKARI_LEVELS[1]);wait("!document.getElementById('akari-result').hidden")
                assert ev("document.getElementById('akari-result-description').textContent.includes('经验')")
                # 最后一关完成后的下一关按钮回选关，入门下一关单独验证无跨游戏跳转。
                click('#akari-back');choose(AKARI_LEVELS[0]);click('#akari-next')
                wait("document.getElementById('akari-kicker').textContent.startsWith('第1关')")
                checks.append('查看旧结果、最终关返回选关及入门下一关导航')
                with sessions() as db:
                    summary=db.scalar(select(PlayerProgression));assert summary.total_stars==46
                print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False))
        finally:
            server.should_exit=True;worker.join(timeout=5);qa.api.app.dependency_overrides.clear();engine.dispose()


if __name__=='__main__':main()
