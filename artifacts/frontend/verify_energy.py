"""作用：独立Chrome与临时SQLite验收体力展示、扣返、重开、免费教学和首页面板删除。

--preview使用既有隔离预览库启动新版，不读取或迁移业务MySQL。
"""
import argparse
import base64
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from datetime import timedelta
from sqlalchemy import select
import verify_ranking as qa
from verify_sudoku import environment
from verify_progress import browser
from backend.app.common.game_catalog import LEVELS
from backend.app.common.security import utc_now
from backend.app.models.entities.progression import PlayerEnergy,GameAttempt
from backend.app.services import progression_service
from backend.content_check import akari_solutions


def main():
    """所有账号和游戏操作限定在本次临时库，预览模式使用明确命名的SQLite。"""
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preview',action='store_true');parser.add_argument('--port',type=int,default=8005);args=parser.parse_args()
    if args.preview:
        environment(qa.OUTPUT/'sudoku-preview.sqlite3')
        print(f'Energy preview: http://127.0.0.1:{args.port}/index.html',flush=True)
        qa.uvicorn.run(qa.api.app,host='127.0.0.1',port=args.port,log_level='error');return
    checks=[]
    with tempfile.TemporaryDirectory(prefix='energy-qa-') as temp:
        engine,sessions=environment(Path(temp)/'qa.sqlite')
        listener=socket.socket();listener.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error'));worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        try:
            deadline=time.monotonic()+10
            while not server.started and time.monotonic()<deadline:time.sleep(.05)
            assert server.started
            with (qa.OUTPUT/'energy-chrome.log').open('w',encoding='utf-8') as log,browser(str(Path(temp)/'chrome'),log) as (cmd,ev):
                def wait(expression):
                    """有界等待真实页面，失败只报告条件及页面提示。"""
                    deadline=time.monotonic()+12
                    while time.monotonic()<deadline:
                        if ev(f'(()=>{{try{{return Boolean({expression});}}catch{{return false;}}}})()'):return
                        time.sleep(.03)
                    raise AssertionError((expression,ev("document.querySelector('#akari-message,#mine-message,#sudoku-message')?.textContent")))

                def click(selector):
                    """通过实际DOM事件操作，不直接修改游戏模型。"""
                    literal=json.dumps(selector);wait(f"(()=>{{const n=document.querySelector({literal});return n&&!n.disabled&&n.getClientRects().length;}})()")
                    ev(f'document.querySelector({literal}).click()')

                def shot(name):
                    """视觉证据保存在已忽略的artifact目录。"""
                    (qa.OUTPUT/name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})['data']))

                def energy(number):
                    """只读取产品展示，不以本地值代替服务器余额。"""
                    wait(f"document.querySelector('.player-energy strong')?.textContent==='{number} / 5'")

                def open_akari(identity):
                    """选关确认才开始；返回选关不返体力。"""
                    progression_service.limiter.clear()
                    close_result()
                    if ev("document.getElementById('akari-play')&&!document.getElementById('akari-play').hidden"):click('#akari-back')
                    click(f'#akari-levels [data-level="{identity}"]');click('#akari-enter-confirm')
                    wait("!document.getElementById('akari-play').hidden&&!document.getElementById('akari-restart').disabled")

                def close_result():
                    """真实Esc关闭通关弹窗，再操作背景棋盘或重开按钮。"""
                    if ev("document.getElementById('akari-result')?.open"):
                        cmd('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
                        cmd('Input.dispatchKeyEvent',{'type':'keyUp','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
                        wait("!document.getElementById('akari-result').open")

                cmd('Page.enable');cmd('Runtime.enable');cmd('Network.enable');cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
                cmd('Page.navigate',{'url':base+'index.html'});wait("document.querySelector('.auth-open')")
                assert ev("document.getElementById('personal-records')===null")
                click('.auth-open');ev("document.getElementById('auth-username').value='体力验收';document.getElementById('auth-password').value='energy-browser-test';document.querySelector('.auth-submit').click()")
                energy(5);shot('energy-home-desktop.png');checks.append('首页记录面板移除，登录后显示5/5体力')
                for width,height in [(375,812),(320,740)]:
                    cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':True})
                    assert ev('document.documentElement.scrollWidth<=innerWidth'),f'页面溢出{width}'
                    assert ev("(()=>{const r=document.querySelector('.player-energy').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;})()")
                    shot(f'energy-home-{width}.png')
                checks.append('320/375px体力区可见且无横向溢出')
                cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
                cmd('Page.navigate',{'url':base+'journey.html?game_id=akari'});wait("document.querySelectorAll('#akari-levels button').length===16");energy(5)
                open_akari('akari-v2-tutorial');energy(5)
                for action in LEVELS['akari-v2-tutorial']['puzzle']['tutorial_steps'][:-1]:
                    click(f'#akari-board [data-index="{action["index"]}"]');wait("!document.getElementById('akari-restart').disabled")
                click('#akari-board [data-index="22"]');wait("document.getElementById('akari-result-title').textContent.includes('点亮')");energy(5)
                checks.append('入门实际通关免费，不返还额外体力')
                open_akari('akari-v2-001');energy(4)
                cmd('Page.reload');wait("document.querySelectorAll('#akari-board button').length===16&&!document.getElementById('akari-restart').disabled");energy(4)
                click('#akari-restart');wait("document.getElementById('akari-restart-dialog').open")
                assert ev("document.getElementById('akari-restart-energy').textContent.includes('再消耗1点')")
                click('#akari-restart-confirm');energy(3)
                for index in akari_solutions(LEVELS['akari-v2-001']['puzzle']['map'])[0]:
                    click(f'#akari-board [data-index="{index}"]');wait("!document.getElementById('akari-restart').disabled||document.getElementById('akari-result').open")
                energy(4);checks.append('普通开局扣1、刷新不扣、重开再扣1、通关返1')
                close_result()
                for _ in range(4):
                    click('#akari-restart');click('#akari-restart-confirm');wait("!document.getElementById('akari-restart').disabled")
                energy(0)
                editable=next(i for i,c in enumerate(''.join(LEVELS['akari-v2-001']['puzzle']['map'])) if c=='.')
                click(f'#akari-board [data-index="{editable}"]');wait("!document.getElementById('akari-restart').disabled")
                click('#akari-restart');click('#akari-restart-confirm')
                wait("document.getElementById('akari-message').textContent.includes('体力不足')")
                assert ev(f'document.querySelector(\'#akari-board [data-index="{editable}"]\').classList.contains("bulb")')
                energy(0);checks.append('零体力重开失败保留原棋盘')
                # 仅测试库把下一点恢复时间提前，浏览器仍通过真实体力接口读取。
                with sessions() as db:
                    row=db.scalar(select(PlayerEnergy));row.recovery_at=utc_now()+timedelta(seconds=2);row.revision+=1;db.commit()
                cmd('Page.reload');energy(0);energy(1);checks.append('到恢复节点自动核对服务器，体力恢复1点')
                shot('energy-recovered.png')
                cmd('Page.navigate',{'url':base+'journey.html?game_id=mine'});wait("document.querySelectorAll('#mine-specs button').length===3");energy(1)
                click('#mine-start');wait("document.getElementById('mine-rules-dialog').open");click('#mine-rules-confirm');energy(0)
                checks.append('扫雷与照明共用同一余额，开始即更新体力')
                cmd('Page.navigate',{'url':base+'journey.html?game_id=sudoku'});wait("document.querySelectorAll('#sudoku-specs button').length===3");energy(0)
                click('#sudoku-start');wait("document.getElementById('sudoku-message').textContent.includes('体力不足')")
                click('#sudoku-difficulties [data-difficulty="tutorial"]');click('#sudoku-start');wait("document.querySelectorAll('#sudoku-board button').length===16");energy(0)
                checks.append('数独零体力禁止普通开局，仍可进入免费入门')
                cmd('Page.navigate',{'url':base+'index.html'});energy(0);click('.auth-logout');wait("document.querySelector('.player-energy').hidden")
                click('.auth-open');ev("document.getElementById('auth-username').value='体力新账号';document.getElementById('auth-password').value='energy-browser-test';document.querySelector('.auth-submit').click()")
                energy(5);checks.append('退出隐藏体力，换号读取独立5点余额')
                print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False))
        finally:
            server.should_exit=True;worker.join(timeout=5);qa.api.app.dependency_overrides.clear();engine.dispose()


if __name__=='__main__':main()
