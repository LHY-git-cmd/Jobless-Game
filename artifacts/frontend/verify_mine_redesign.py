"""作用：独立Chrome/临时SQLite验收原图主题、五档十三项扫雷、教学、奖励、续玩及窄屏。

真实登录、真实API和真实页面操作；只在测试进程读取临时雷图，不访问业务数据库。
"""
import base64
import argparse
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

import verify_ranking as qa
from verify_progress import browser
from sqlalchemy import select, func
from backend.app.common.game_catalog import LEVELS, MINE_LEVELS
from backend.app.models.entities.progression import GameLevel, GameLevelVersion, GameAttempt, PlayerProgression
from backend.app.services import progression_service


def main():
    """界面操作覆盖正常、失败和重试；服务与数据库始终只属于本次隔离验收。"""
    checks=[]
    with tempfile.TemporaryDirectory(prefix='mine-redesign-browser-') as temporary:
        engine=qa.create_engine('sqlite:///'+(Path(temporary)/'qa.sqlite').as_posix(),connect_args={'check_same_thread':False,'timeout':10})
        qa.Base.metadata.create_all(engine)
        sessions=qa.sessionmaker(engine,expire_on_commit=False)
        with sessions() as db:
            for item in LEVELS.values():
                db.add(GameLevel(level_id=item['level_id'],game_id=item['game_id'],order_index=item['order']))
                db.add(GameLevelVersion(level_id=item['level_id'],level_version=1,definition=item))
            db.commit()
        def dependency():
            """每次请求使用独立临时会话。"""
            with sessions() as db:
                yield db
        qa.api.app.dependency_overrides[qa.get_db]=dependency
        settings=qa.get_settings()
        settings.progression_enabled=True;settings.cosmetics_enabled=True;settings.pk_rooms_enabled=False;settings.matchmaking_enabled=False
        settings.cookie_secure=False
        listener=socket.socket();listener.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        try:
            for _ in range(200):
                if server.started:break
                time.sleep(.05)
            assert server.started
            with (qa.OUTPUT/'mine-redesign-chrome.log').open('w',encoding='utf-8') as log, browser(str(Path(temporary)/'chrome'),log) as (cmd,ev):
                def wait(expression,seconds=15):
                    """有界等待只返回失败条件与界面状态，避免整页DOM日志。"""
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:
                        if ev(f'(()=>{{try{{return Boolean({expression});}}catch{{return false;}}}})()'):return
                        time.sleep(.04)
                    raise AssertionError((expression,ev("({message:document.getElementById('mine-message')?.textContent,result:document.getElementById('mine-result-description')?.textContent,auth:document.querySelector('.auth-status')?.textContent})")))
                def click(selector):
                    """通过页面按钮及监听操作，不调用内部控制器或改写棋盘。"""
                    literal=json.dumps(selector)
                    wait(f"(()=>{{const x=document.querySelector({literal});return x&&!x.disabled&&x.getClientRects().length>0;}})()")
                    ev(f'document.querySelector({literal}).click()')
                def shot(name):
                    """保存当前真实视口以检查桌面及移动端布局。"""
                    (qa.OUTPUT/name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data']))
                def account(name):
                    """真实登录只创建本次临时账号。"""
                    ev(f"document.getElementById('auth-username').value={json.dumps(name)};document.getElementById('auth-password').value='mine-redesign-qa-secret';document.querySelector('.auth-submit').click()")
                    wait(f'document.querySelector(".auth-username")?.textContent==={json.dumps(name)}')
                def active(level):
                    """仅验收进程读取隔离棋盘来稳定定位安全格。"""
                    with sessions() as db:
                        return db.scalar(select(GameAttempt).where(GameAttempt.level_id==level).order_by(GameAttempt.started_at.desc()))
                def choose(level):
                    """选关只筛选，确认规则后才开局。"""
                    progression_service.limiter.clear()
                    if ev("!document.getElementById('mine-play').hidden"):click('#mine-back')
                    click(f'[data-difficulty="{LEVELS[level]["difficulty"]}"]')
                    assert ev("document.querySelectorAll('#mine-specs [data-level]').length===3")
                    click(f'[data-level="{level}"]');click('#mine-start')
                    wait("document.getElementById('mine-rules-dialog').open || !document.getElementById('mine-play').hidden")
                    if ev("document.getElementById('mine-rules-dialog').open"):click('#mine-rules-confirm')
                    wait("!document.getElementById('mine-play').hidden && !document.getElementById('mine-restart').disabled")
                    wait(f"document.querySelectorAll('#mine-board [data-index]').length==={LEVELS[level]['puzzle']['rows']*LEVELS[level]['puzzle']['cols']}")
                def reveal(index):
                    """先选格再排雷，等待权威揭格响应完成。"""
                    click(f'#mine-board [data-index="{index}"]');click('#mine-reveal')
                    wait("!document.getElementById('mine-restart').disabled || document.getElementById('mine-result-title').textContent.includes('碰到')")
                def solve(level,block_completion=False):
                    """所有操作都走UI；已展开安全格不重复点击。"""
                    row=active(level);mines=set(row.board['mine_indices']);count=LEVELS[level]['puzzle']['rows']*LEVELS[level]['puzzle']['cols']
                    if block_completion:cmd('Network.setBlockedURLs',{'urls':['*/api/v1/attempts/*/completion']})
                    for index in range(count):
                        if index not in mines and not ev(f'document.querySelector(\'#mine-board [data-index="{index}"]\').hasAttribute("data-number")'):
                            reveal(index)
                    if block_completion:
                        wait("document.getElementById('mine-message').textContent.includes('连接失败')")
                        frozen=ev("document.getElementById('mine-clock').textContent")
                        cmd('Network.setBlockedURLs',{'urls':[]});click('#mine-retry-settlement')
                        assert ev("document.getElementById('mine-clock').textContent")==frozen
                    wait("document.getElementById('mine-result-kicker').textContent==='本关成绩已保存'")

                cmd('Network.enable');cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
                cmd('Page.navigate',{'url':base+'journey.html?game_id=mine'})
                wait("document.querySelectorAll('[data-difficulty]').length===5 && !document.getElementById('mine-start').disabled")
                assert ev("document.querySelectorAll('[data-level]').length===3")
                shot('mine-five-desktop.png')
                click('[data-difficulty="tutorial"]');click('#mine-start')
                wait("!document.getElementById('auth-dialog').classList.contains('hidden')")
                account('扫雷验收甲');wait("document.getElementById('mine-rules-dialog').open")
                with sessions() as db:assert db.scalar(select(func.count()).select_from(GameAttempt))==0
                click('#mine-rules-confirm');wait("document.querySelectorAll('#mine-board [data-index]').length===25")
                assert ev("getComputedStyle(document.querySelector('#mine-board [data-index=\"0\"]')).backgroundImage.includes('/minesweeper/v2/covered.webp')")
                reveal(4)
                assert ev("document.querySelectorAll('#mine-board [data-number]').length===0")
                reveal(0);wait("!document.getElementById('mine-understood').hidden")
                assert ev("getComputedStyle(document.querySelector('#mine-board [data-index=\"0\"]')).backgroundImage.includes('/minesweeper/v2/number-1.webp') && document.querySelector('#mine-board [data-index=\"0\"]').textContent===''")
                click('#mine-understood');click('#mine-board [data-index="6"]');click('#mine-flag')
                wait("document.querySelector('#mine-board [data-index=\"6\"]').classList.contains('mine-flagged')")
                assert ev("getComputedStyle(document.querySelector('#mine-board [data-index=\"6\"]')).backgroundImage.includes('/minesweeper/v2/flag.webp')")
                shot('mine-original-theme-tutorial.png')
                checks.append('格子、红旗、数字直接使用指定原图切片')
                solve('mine-v2-tutorial')
                assert ev("document.getElementById('mine-result-description').textContent.includes('1 星、2 经验')")
                checks.append('游客先登录、首次规则不计时、四步教学与固定奖励')
                shot('mine-tutorial-result.png')

                choose('mine-v2-easy-20')
                click('#mine-board [data-index="299"]');click('#mine-flag')
                wait("document.getElementById('mine-left').textContent==='29'")
                started=active('mine-v2-easy-20').started_at
                cmd('Page.reload');wait("document.querySelectorAll('#mine-board [data-index]').length===300")
                wait("document.getElementById('mine-left').textContent==='29'")
                assert active('mine-v2-easy-20').started_at==started
                ev("document.querySelector('#mine-board [data-index=\"299\"]').focus()")
                cmd('Input.dispatchKeyEvent',{'type':'keyDown','key':'ArrowLeft','code':'ArrowLeft'})
                wait("document.querySelector('#mine-board [data-index=\"298\"]').getAttribute('aria-pressed')==='true'")
                click('#mine-rules');wait("document.getElementById('mine-rules-dialog').open")
                assert active('mine-v2-easy-20').started_at==started
                click('#mine-rules-confirm')
                checks.append('方向键选格与游戏中重看规则保留原始计时')
                for width in (1440,375,320):
                    cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':width<700})
                    assert ev('document.documentElement.scrollWidth<=innerWidth'),f'{width}px整页溢出'
                    ev("(()=>{const box=document.getElementById('mine-viewport');box.scrollLeft=box.scrollWidth;box.scrollTop=box.scrollHeight})()")
                    assert ev("document.getElementById('mine-viewport').scrollLeft>0") if width<700 else True
                    shot(f'mine-five-{width}-board.png')
                checks.append('20×15实际行列、末格旗标、刷新原始计时与320/375px容器滚动')
                click('#mine-restart');wait("document.getElementById('mine-restart-dialog').open")
                click('#mine-restart-cancel');assert active('mine-v2-easy-20').started_at==started
                click('#mine-restart');click('#mine-restart-confirm')
                wait("document.getElementById('mine-left').textContent==='30' && !document.getElementById('mine-restart').disabled")
                checks.append('重开确认与当前关旗标清空')
                cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
                ordinary=[v for v in MINE_LEVELS if v['difficulty']!='tutorial']
                # 首项已打开，其余按目录逐项验证，包括中等之后的全部矩形棋盘。
                ordinary.sort(key=lambda v: v['level_id']!='mine-v2-easy-20')
                for definition in ordinary:
                    level,xp=definition['level_id'],definition['star_xp'][-1]
                    if level!='mine-v2-easy-20':choose(level)
                    # 首揭完成后读取实际布局，兼容首击安全导致的地雷迁移。
                    reveal(0);solve(level,block_completion=level=='mine-v2-easy-10')
                    assert ev(f"document.getElementById('mine-result-description').textContent.includes('3 星、{xp} 经验')")
                wait("document.querySelector('.player-stars strong').textContent==='37'")
                checks.append('十二种普通棋盘全部通关、每档三个规格、精确37星194经验与顶部刷新')
                checks.append('结算请求断网、终盘计时冻结、原尝试重试成功')
                shot('mine-five-result.png')
                choose('mine-v2-hell')
                click('#mine-restart');wait("!document.getElementById('mine-restart').disabled && document.getElementById('mine-result').hidden")
                reveal(0)
                row=active('mine-v2-hell');mine=row.board['mine_indices'][0]
                click(f'#mine-board [data-index="{mine}"]');click('#mine-reveal')
                wait("!document.getElementById('mine-result').hidden && document.getElementById('mine-result-title').textContent.includes('碰到')",seconds=20)
                assert ev("document.querySelectorAll('.mine-visible').length===18")
                assert ev("getComputedStyle(document.querySelector('.mine-visible')).backgroundImage.includes('/minesweeper/v2/exploded.webp') && getComputedStyle(document.querySelector('.mine-visible')).opacity==='1'")
                shot('mine-original-theme-lost.png')
                click('#mine-sound');assert ev("document.getElementById('mine-sound').textContent==='音效：关'")
                checks.append('失败连锁显示全部地雷，音效开关遵循共享设置')
                click('#mine-back')
                cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
                choose('mine-v2-hell');click('#mine-restart')
                wait("!document.getElementById('mine-restart').disabled && document.getElementById('mine-result').hidden")
                reveal(0);mine=active('mine-v2-hell').board['mine_indices'][0]
                reveal(mine)
                wait("!document.getElementById('mine-result').hidden")
                assert ev("document.querySelectorAll('.mine-visible').length===18 && !document.querySelector('.mine-blasting')")
                click('#mine-back')
                checks.append('减少动画偏好下直接展示完整失败终盘')
                for width in (375,320,812):
                    cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':900 if width<700 else 375,'deviceScaleFactor':1,'mobile':True})
                    assert ev('document.documentElement.scrollWidth<=innerWidth')
                    shot(f'mine-five-{width}-selection.png')
                click('.auth-logout');wait("!document.querySelector('.auth-open').classList.contains('hidden')")
                click('.auth-open');account('扫雷验收乙');wait("document.querySelector('.player-stars strong').textContent==='0'")
                assert ev("document.getElementById('mine-play').hidden")
                checks.append('退出及换号清空棋盘与旧成长')
                for game in ('akari','sudoku'):
                    cmd('Page.navigate',{'url':base+'journey.html?game_id='+game})
                    wait(f"document.body.dataset.game==='{game}' && document.getElementById('catalog-empty-title').textContent.includes('重新设计')")
                    assert ev("!document.querySelector('#mine-journey')")
                checks.append('照明/数独重制占位页保持正常')
                with sessions() as db:
                    summary=db.scalars(select(PlayerProgression).order_by(PlayerProgression.user_id)).first()
                    assert (summary.total_stars,summary.xp)==(37,194)
        finally:
            server.should_exit=True;worker.join(timeout=10);listener.close()
            qa.api.app.dependency_overrides.clear();engine.dispose()
    print(json.dumps({'checks_passed':len(checks),'checks':checks,'uncaught_errors':0},ensure_ascii=False))


def preview(port):
    """仅在127.0.0.1启动独立SQLite预览，账号与正式/已有开发数据库隔离。"""
    engine=qa.create_engine('sqlite:///'+(qa.OUTPUT/'mine-redesign-preview.sqlite3').as_posix(),connect_args={'check_same_thread':False,'timeout':10})
    qa.Base.metadata.create_all(engine)
    sessions=qa.sessionmaker(engine,expire_on_commit=False)
    with sessions() as db:
        for item in LEVELS.values():
            if not db.get(GameLevel,item['level_id']):
                db.add(GameLevel(level_id=item['level_id'],game_id=item['game_id'],order_index=item['order']))
            if not db.get(GameLevelVersion,(item['level_id'],1)):
                db.add(GameLevelVersion(level_id=item['level_id'],level_version=1,definition=item))
        db.commit()
    def dependency():
        """预览请求只使用本脚本的SQLite会话。"""
        with sessions() as db:
            yield db
    qa.api.app.dependency_overrides[qa.get_db]=dependency
    settings=qa.get_settings();settings.progression_enabled=True;settings.cosmetics_enabled=True
    settings.pk_rooms_enabled=False;settings.matchmaking_enabled=False;settings.cookie_secure=False
    try:
        qa.uvicorn.run(qa.api.app,host='127.0.0.1',port=port,log_level='warning')
    finally:
        qa.api.app.dependency_overrides.clear();engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview',action='store_true',help='运行独立本地预览，不执行浏览器验收')
    parser.add_argument('--port',type=int,default=8002)
    args=parser.parse_args()
    preview(args.port) if args.preview else main()
