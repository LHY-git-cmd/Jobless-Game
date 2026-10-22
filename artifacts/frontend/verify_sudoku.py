"""作用：独立Chrome及临时SQLite验收数独13关、教学、成长、暂停、草稿和手机布局。

只在本次测试进程离线读取题目答案，产品操作全部经真实页面和API。--preview启动独立持久预览。
"""
import argparse
import base64
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
from backend.app.models.entities.progression import GameLevel,GameLevelVersion,GameAttempt,PlayerProgression
from backend.app.services import progression_service
from backend.sudoku_content import solutions


def environment(database):
    """只装配指定隔离SQLite，不读取或迁移业务库。"""
    engine=qa.create_engine('sqlite:///'+database.as_posix(),connect_args={'check_same_thread':False,'timeout':10})
    qa.Base.metadata.create_all(engine);sessions=qa.sessionmaker(engine,expire_on_commit=False)
    with sessions() as db:
        for item in LEVELS.values():
            if db.get(GameLevel,item['level_id']) is None:
                db.add(GameLevel(level_id=item['level_id'],game_id=item['game_id'],order_index=item['order']))
                db.add(GameLevelVersion(level_id=item['level_id'],level_version=1,definition=item))
        db.commit()

    def dependency():
        """每个请求独立释放临时库会话。"""
        with sessions() as db:yield db
    qa.api.app.dependency_overrides[qa.get_db]=dependency
    settings=qa.get_settings();settings.progression_enabled=True;settings.cosmetics_enabled=True
    settings.pk_rooms_enabled=False;settings.matchmaking_enabled=False;settings.cookie_secure=False
    return engine,sessions


def main():
    """浏览器行为测试有界等待，失败只报条件和页面状态。"""
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preview',action='store_true');parser.add_argument('--port',type=int,default=8003)
    args=parser.parse_args()
    if args.preview:
        environment(qa.OUTPUT/'sudoku-preview.sqlite3')
        print(f'Sudoku preview: http://127.0.0.1:{args.port}/journey.html?game_id=sudoku',flush=True)
        qa.uvicorn.run(qa.api.app,host='127.0.0.1',port=args.port,log_level='error');return
    checks=[]
    with tempfile.TemporaryDirectory(prefix='sudoku-browser-') as temp:
        engine,sessions=environment(Path(temp)/'qa.sqlite')
        listener=socket.socket();listener.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        try:
            for _ in range(200):
                if server.started:break
                time.sleep(.05)
            assert server.started
            with (qa.OUTPUT/'sudoku-chrome.log').open('w',encoding='utf-8') as log,browser(str(Path(temp)/'chrome'),log) as (cmd,ev):
                def wait(expression,seconds=12):
                    """只轮询本机页面，失败附带状态文字而非整页输出。"""
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:
                        if ev(f'(()=>{{try{{return Boolean({expression});}}catch{{return false;}}}})()'):return
                        time.sleep(.025)
                    raise AssertionError((expression,ev("document.getElementById('sudoku-message')?.textContent")))

                def click(selector):
                    """通过实际监听器操作可见且可用的按钮。"""
                    literal=json.dumps(selector)
                    wait(f"(()=>{{const n=document.querySelector({literal});return n&&!n.disabled&&n.getClientRects().length;}})()")
                    ev(f'document.querySelector({literal}).click()')

                def shot(name):
                    """截图为视觉验收材料，保存在已忽略的artifacts中。"""
                    (qa.OUTPUT/name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})['data']))

                def active(level):
                    """验收进程读取本次临时局，页面永远不获取答案。"""
                    with sessions() as db:return db.scalar(select(GameAttempt).where(GameAttempt.level_id==level).order_by(GameAttempt.started_at.desc()))

                def choose(level):
                    """五档三题筛选不创建尝试，点击开始直接进入并计时。"""
                    progression_service.limiter.clear()
                    if ev("!document.getElementById('sudoku-play').hidden"):click('#sudoku-back')
                    click(f'#sudoku-difficulties [data-difficulty="{LEVELS[level]["difficulty"]}"]')
                    click(f'#sudoku-specs [data-level="{level}"]');click('#sudoku-start')
                    wait("!document.getElementById('sudoku-play').hidden && !document.getElementById('sudoku-restart').disabled")
                    wait(f"document.querySelectorAll('#sudoku-board [data-index]').length==={LEVELS[level]['puzzle']['rows']**2}")

                def fill(index,value):
                    """每格使用产品数字键，不注入控制器或直接修改布局。"""
                    click(f'#sudoku-board [data-index="{index}"]');click(f'#sudoku-keypad [data-digit="{value}"]')
                    wait("!document.getElementById('sudoku-restart').disabled")

                def solve(level,offline=False):
                    """离线求解只在测试机执行，逐个空格走真实输入和终盘提交。"""
                    puzzle=LEVELS[level]['puzzle'];answer=solutions(puzzle['values'],puzzle['rows'])[0]
                    blanks=[i for i,v in enumerate(puzzle['values']) if not v]
                    if offline:cmd('Network.setBlockedURLs',{'urls':['*/api/v1/attempts/*/completion']})
                    for i in blanks:fill(i,answer[i])
                    if offline:
                        wait("document.getElementById('sudoku-message').textContent.includes('连接失败')")
                        cmd('Page.reload');wait("document.getElementById('sudoku-message').textContent.includes('连接失败')")
                        cmd('Network.setBlockedURLs',{'urls':[]});click('#sudoku-retry-settlement')
                    wait("document.getElementById('sudoku-result-title').textContent==='本关成绩已保存'")

                cmd('Page.enable');cmd('Network.enable');cmd('Runtime.enable')
                cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1150,'deviceScaleFactor':1,'mobile':False})
                cmd('Page.navigate',{'url':base+'journey.html?game_id=sudoku'})
                wait("document.querySelectorAll('#sudoku-difficulties [data-difficulty]').length===5",4)
                wait("!document.getElementById('sudoku-start').disabled")
                assert ev("document.querySelectorAll('#sudoku-specs [data-level]').length===3")
                shot('sudoku-selector-desktop.png')
                click('#sudoku-difficulties [data-difficulty="tutorial"]');click('#sudoku-start')
                wait("!document.getElementById('auth-dialog').classList.contains('hidden')")
                ev("document.getElementById('auth-username').value='数独验收';document.getElementById('auth-password').value='sudoku-browser-test';document.querySelector('.auth-submit').click()")
                wait("document.querySelectorAll('#sudoku-board [data-index]').length===16 && !document.getElementById('sudoku-restart').disabled")
                fill(1,2);click('#sudoku-clear');wait("document.getElementById('sudoku-tutorial').dataset.step==='2'")
                click('#sudoku-notes');fill(1,2);click('#sudoku-notes');fill(6,1);fill(1,2)
                wait("document.getElementById('sudoku-result-title').textContent==='本关成绩已保存'")
                checks.append('4×4教学真实填数/清除/笔记/列宫输入并获得1星2经验')
                choose('sudoku-v2-easy-01');puzzle=LEVELS['sudoku-v2-easy-01']['puzzle']
                assert ev("document.querySelectorAll('#sudoku-board .tutorial-target').length===0"),'普通题不应出现教学目标框'
                blank=next(i for i,v in enumerate(puzzle['values']) if not v)
                click(f'#sudoku-board [data-index="{blank}"]');click('#sudoku-notes');click('#sudoku-keypad [data-digit="2"]')
                wait("!document.getElementById('sudoku-restart').disabled")
                cmd('Page.reload');wait("document.querySelector('#sudoku-notes')?.textContent==='笔记：开'")
                assert ev(f'document.querySelector(\'#sudoku-board [data-index="{blank}"] .sudoku-notes\')!==null')
                click('#sudoku-notes');click('#sudoku-clear');wait("!document.getElementById('sudoku-restart').disabled")
                assert ev("!document.querySelector('#sudoku-check,#sudoku-rules,#sudoku-rules-dialog')")
                assert ev("document.getElementById('sudoku-notes').closest('.sudoku-actions')!==null")
                click('#sudoku-pause-toggle');wait("document.getElementById('sudoku-clock-label').textContent.includes('已暂停')")
                before=ev("document.getElementById('sudoku-clock').textContent");time.sleep(1.1)
                assert ev("document.getElementById('sudoku-clock').textContent")==before
                click('#sudoku-pause-toggle');wait("document.getElementById('sudoku-pause').hidden")
                checks.append('底部笔记及选格刷新恢复；移除检查/规则，时间旁手动暂停并恢复')
                shot('sudoku-playing-desktop.png')
                for width,height in [(375,960),(320,850),(844,390)]:
                    cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':True})
                    assert ev('document.documentElement.scrollWidth<=innerWidth'),width
                    assert ev("(()=>{const s=document.querySelector('.sudoku-available').getBoundingClientRect(),t=document.querySelector('.sudoku-toolbar').getBoundingClientRect();return Math.abs(s.left+s.width/2-t.left-t.width/2)<1;})()"),'可得星数必须居中'
                    ev("document.getElementById('sudoku-play').scrollIntoView({block:'start'})")
                    shot(f'sudoku-playing-{width}.png')
                cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1150,'deviceScaleFactor':1,'mobile':False})
                checks.append('320/375px及横屏无页面横向溢出')
                solve('sudoku-v2-easy-01',offline=True)
                for difficulty in ('easy','medium','hard','hell'):
                    for number in range(1,4):
                        level=f'sudoku-v2-{difficulty}-{number:02}'
                        if level=='sudoku-v2-easy-01':continue
                        choose(level);solve(level)
                with sessions() as db:
                    summary=db.scalar(select(PlayerProgression));assert (summary.total_stars,summary.xp)==(37,128)
                wait("document.querySelector('.player-stars')?.textContent.includes('37')")
                shot('sudoku-completed.png')
                checks.append('全部13关通关，独立成长合计37星128经验，断网刷新后同终盘重试')
                choose('sudoku-v2-medium-01');click('#sudoku-restart')
                wait("!document.getElementById('sudoku-restart').disabled")
                click('#sudoku-restart');click('#sudoku-restart-confirm')
                wait("document.querySelectorAll('#sudoku-board [data-index]').length===81 && !document.getElementById('sudoku-restart').disabled")
                solve('sudoku-v2-medium-01')
                with sessions() as db:
                    summary=db.scalar(select(PlayerProgression));assert (summary.total_stars,summary.xp)==(37,128)
                checks.append('重新挑战同题不重复奖励')
                print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False))
        finally:
            server.should_exit=True;worker.join(timeout=5);qa.api.app.dependency_overrides.clear();engine.dispose()


if __name__=='__main__':main()
