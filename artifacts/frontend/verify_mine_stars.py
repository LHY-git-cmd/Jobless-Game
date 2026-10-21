"""作用：真实Chrome/临时SQLite验证空星点亮、按时间降星、收集到总数及手机操作。

仅测试进程调整隔离棋局起点来跨过时限；产品代码不伪造时间、星数或奖励。
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
from backend.app.models.entities.progression import GameLevel,GameLevelVersion,GameAttempt,PlayerProgression
from backend.app.services import progression_service


def main():
    """使用真实按钮和账号；测试结束仅清理本次临时服务器和数据库。"""
    checks=[]
    with tempfile.TemporaryDirectory(prefix='mine-stars-') as temporary:
        engine=qa.create_engine('sqlite:///'+(Path(temporary)/'qa.sqlite').as_posix(),connect_args={'check_same_thread':False,'timeout':10})
        qa.Base.metadata.create_all(engine);sessions=qa.sessionmaker(engine,expire_on_commit=False)
        with sessions() as db:
            for item in LEVELS.values():
                db.add(GameLevel(level_id=item['level_id'],game_id=item['game_id'],order_index=item['order']))
                db.add(GameLevelVersion(level_id=item['level_id'],level_version=1,definition=item))
            db.commit()
        def dependency():
            """所有请求只访问隔离库。"""
            with sessions() as db:yield db
        qa.api.app.dependency_overrides[qa.get_db]=dependency
        settings=qa.get_settings();settings.progression_enabled=True;settings.cosmetics_enabled=True
        settings.pk_rooms_enabled=False;settings.matchmaking_enabled=False;settings.cookie_secure=False
        listener=socket.socket();listener.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        try:
            for _ in range(200):
                if server.started:break
                time.sleep(.05)
            assert server.started
            with (qa.OUTPUT/'mine-stars-chrome.log').open('w',encoding='utf-8') as log,browser(str(Path(temporary)/'chrome'),log) as (cmd,ev):
                def wait(expression,seconds=15):
                    """超时只报告条件与界面摘要，不返回完整DOM。"""
                    until=time.monotonic()+seconds
                    while time.monotonic()<until:
                        if ev(f'(()=>{{try{{return Boolean({expression});}}catch{{return false;}}}})()'):return
                        time.sleep(.025)
                    raise AssertionError((expression,ev("({message:document.getElementById('mine-message')?.textContent,stars:document.getElementById('mine-available-stars')?.dataset.stars,result:document.getElementById('mine-result-description')?.textContent,total:document.querySelector('.player-stars strong')?.textContent,batches:window.flightBatches,overlay:!!document.querySelector('.mine-star-collection')})")))
                def click(selector):
                    """遵守disabled/隐藏状态，只经页面监听操作。"""
                    value=json.dumps(selector)
                    wait(f"(()=>{{const x=document.querySelector({value});return x&&!x.disabled&&x.getClientRects().length>0;}})()")
                    ev(f'document.querySelector({value}).click()')
                def shot(name):
                    """截图实际视口，核对星星和手机布局。"""
                    (qa.OUTPUT/name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data']))
                def active(level):
                    """离线读取隔离库布局，仅供稳定触发通关。"""
                    with sessions() as db:return db.scalar(select(GameAttempt).where(GameAttempt.level_id==level).order_by(GameAttempt.started_at.desc()))
                def choose(level):
                    """切换及规则确认仍由页面实现，不直接创建尝试。"""
                    progression_service.limiter.clear()
                    if ev("!document.getElementById('mine-play').hidden"):click('#mine-back')
                    click(f'[data-difficulty="{LEVELS[level]["difficulty"]}"]');click(f'[data-level="{level}"]');click('#mine-start')
                    wait("document.getElementById('mine-rules-dialog').open || !document.getElementById('mine-play').hidden")
                    if ev("document.getElementById('mine-rules-dialog').open"):click('#mine-rules-confirm')
                    wait("!document.getElementById('mine-play').hidden && !document.getElementById('mine-restart').disabled")
                def reveal(index):
                    """选格后排雷，等待一次服务器揭格完成。"""
                    click(f'#mine-board [data-index="{index}"]');click('#mine-reveal')
                    wait("!document.getElementById('mine-restart').disabled")
                def solve(level):
                    """每个安全格都通过真实UI揭开，结果仍由服务器结算。"""
                    row=active(level);mines=set(row.board['mine_indices'])
                    for index in range(LEVELS[level]['puzzle']['rows']*LEVELS[level]['puzzle']['cols']):
                        if index not in mines and not ev(f'document.querySelector(\'#mine-board [data-index="{index}"]\').hasAttribute("data-number")'):reveal(index)
                    wait("document.getElementById('mine-result-kicker').textContent==='本关成绩已保存'")
                def login(name):
                    """真实登录账号只存在于临时库。"""
                    ev(f"document.getElementById('auth-username').value={json.dumps(name)};document.getElementById('auth-password').value='mine-stars-test-secret';document.querySelector('.auth-submit').click()")
                    wait(f'document.querySelector(".auth-username")?.textContent==={json.dumps(name)}')
                def elapsed(level,seconds):
                    """仅测试夹具调整起点，刷新后显示须读取服务端真实尝试。"""
                    with sessions() as db:
                        row=db.get(GameAttempt,active(level).attempt_id);row.started_at=utc_now()-timedelta(seconds=seconds);db.commit()
                    cmd('Page.reload');wait("!document.getElementById('mine-play').hidden && !document.getElementById('mine-restart').disabled")
                cmd('Page.enable')
                cmd('Page.addScriptToEvaluateOnNewDocument',{'source':"window.flightBatches=0;document.addEventListener('DOMContentLoaded',()=>new MutationObserver(records=>records.forEach(r=>r.addedNodes.forEach(n=>{if(n.classList?.contains('mine-star-collection'))window.flightBatches++}))).observe(document.body,{childList:true}));"})
                cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
                cmd('Page.navigate',{'url':base+'journey.html?game_id=mine'})
                wait("document.querySelectorAll('.mine-spec .mine-rating').length===3")
                assert ev("window.flightBatches===0")
                assert ev("Array.from(document.querySelectorAll('.mine-spec .mine-rating')).every(x=>x.children.length===3 && x.dataset.stars==='0' && !x.querySelector('.is-lit'))")
                shot('mine-stars-empty-cards.png');checks.append('三张规格卡各三颗空星，未通关不点亮')
                click('[data-difficulty="tutorial"]');click('#mine-start');wait("!document.getElementById('auth-dialog').classList.contains('hidden')")
                login('星数验收甲');wait("document.getElementById('mine-rules-dialog').open");click('#mine-rules-confirm')
                wait("document.getElementById('mine-available-stars').dataset.stars==='1'")
                reveal(0);click('#mine-understood');click('#mine-board [data-index="6"]');click('#mine-flag');wait("document.querySelector('.mine-flagged')")
                solve('mine-v2-tutorial');wait("document.querySelectorAll('.mine-flying-star').length===1")
                assert ev("document.querySelector('.player-stars strong').textContent==='0'")
                wait("document.querySelector('.player-stars strong').textContent==='1' && !document.querySelector('.mine-flying-star')")
                click('#mine-back')
                assert ev("document.querySelector('.mine-spec .mine-rating').dataset.stars==='1' && document.querySelectorAll('.mine-spec .mine-rating svg').length===3")
                assert ev("getComputedStyle(document.querySelector('.mine-spec .mine-rating')).color===getComputedStyle(document.querySelector('.player-stars')).color")
                checks.append('教学固定一星、实得一星汇入顶部后更新、历史星与顶部同色')
                choose('mine-v2-easy-10');wait("document.getElementById('mine-available-stars').dataset.stars==='3'")
                elapsed('mine-v2-easy-10',76);wait("document.getElementById('mine-available-stars').dataset.stars==='2'")
                elapsed('mine-v2-easy-10',149);wait("document.getElementById('mine-available-stars').dataset.stars==='2'")
                wait("document.getElementById('mine-available-stars').dataset.stars==='1'",seconds=4)
                reveal(0);solve('mine-v2-easy-10');wait("document.querySelector('.player-stars strong').textContent==='2'")
                frozen=ev("document.getElementById('mine-clock').textContent")
                wait("!document.querySelector('.mine-star-collection')")
                assert ev("document.getElementById('mine-available-stars').dataset.stars==='1'")
                assert ev("document.getElementById('mine-clock').textContent")==frozen
                checks.append('跨75/150秒显示3→2→1、刷新继续计时、通关后一星冻结')
                click('#mine-restart');wait("document.getElementById('mine-result').hidden && !document.getElementById('mine-restart').disabled")
                cmd('Emulation.setDeviceMetricsOverride',{'width':375,'height':812,'deviceScaleFactor':1,'mobile':True})
                ev("document.querySelector('.mine-operation').scrollIntoView({behavior:'instant',block:'start'})")
                wait("document.querySelector('.player-stars').getBoundingClientRect().bottom<0")
                assert ev("document.querySelector('.mine-operation').getBoundingClientRect().bottom<=document.getElementById('mine-viewport').getBoundingClientRect().top && document.getElementById('mine-flag').getBoundingClientRect().height>=44 && document.getElementById('mine-reveal').getBoundingClientRect().height>=44")
                before=ev('scrollY');reveal(0);solve('mine-v2-easy-10')
                wait("document.querySelectorAll('.mine-flying-star').length===2 && document.querySelector('.mine-star-total')")
                assert ev("document.querySelector('.player-stars strong').textContent==='2'")
                shot('mine-stars-mobile-flight.png')
                wait("document.querySelector('.player-stars strong').textContent==='4'")
                assert abs(ev('scrollY')-before)<2
                assert ev("document.getElementById('mine-result-description').textContent.includes('本次新增 2 星、4 经验')")
                checks.append('手机双星补差动画、可见总数接收位置、不强制滚动、44px操作区')
                batches=ev('window.flightBatches');click('#mine-restart')
                wait("document.getElementById('mine-result').hidden && !document.getElementById('mine-restart').disabled")
                reveal(0);solve('mine-v2-easy-10')
                assert ev('window.flightBatches')==batches
                assert ev("document.getElementById('mine-result-description').textContent.includes('本次新增 0 星、0 经验') && !document.querySelector('.mine-flying-star')")
                click('#mine-back');assert ev("document.querySelector('[data-level=\"mine-v2-easy-10\"] .mine-rating').dataset.stars==='3'")
                shot('mine-stars-mobile-earned.png')
                cmd('Page.reload');wait("!document.getElementById('mine-result').hidden && window.flightBatches===0 && !document.querySelector('.mine-star-collection')")
                checks.append('相同成绩无重复汇聚，规格卡三颗点亮，刷新查看结果不重播')
                cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
                choose('mine-v2-medium');reveal(0);solve('mine-v2-medium')
                wait("document.querySelector('.player-stars strong').textContent==='7'")
                assert ev("window.flightBatches===0 && !document.querySelector('.mine-flying-star')")
                checks.append('减少动画偏好下直接同步真实总数')
                choose('mine-v2-hell-20');wait("Math.abs(document.getElementById('mine-play').getBoundingClientRect().top)<2")
                click('#mine-board [data-index="299"]');click('#mine-flag')
                for width,height in ((320,812),(375,812),(812,375)):
                    cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':True})
                    ev("document.getElementById('mine-play').scrollIntoView({behavior:'instant',block:'start'})")
                    assert ev('document.documentElement.scrollWidth<=innerWidth')
                    ev("(()=>{const box=document.getElementById('mine-viewport');box.scrollLeft=box.scrollWidth;box.scrollTop=box.scrollHeight})()")
                    assert ev("document.querySelector('#mine-board [data-index=\"299\"]').classList.contains('mine-flagged')")
                    shot(f'mine-stars-{width}-board.png')
                checks.append('手机开局定位游戏、320/375px及横屏大棋盘区域内滚动，星数与操作正常')
                cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'no-preference'}]})
                choose('mine-v2-hard');reveal(0);solve('mine-v2-hard');wait("document.querySelector('.mine-flying-star')")
                click('.auth-logout');wait("!document.querySelector('.auth-open').classList.contains('hidden') && !document.querySelector('.mine-star-collection')")
                click('.auth-open');login('星数验收乙');wait("document.querySelector('.player-stars strong').textContent==='0'")
                assert ev("document.getElementById('mine-play').hidden && !document.querySelector('.mine-star-collection')")
                checks.append('飞行期间退出/换号清理动画，旧成长不写回新账号')
                with sessions() as db:
                    summary=db.scalars(select(PlayerProgression).order_by(PlayerProgression.user_id)).first()
                    assert (summary.total_stars,summary.xp)==(10,29)
        finally:
            server.should_exit=True;worker.join(timeout=10);listener.close();qa.api.app.dependency_overrides.clear();engine.dispose()
    print(json.dumps({'checks_passed':len(checks),'checks':checks,'uncaught_errors':0},ensure_ascii=False))


if __name__=='__main__':
    main()
