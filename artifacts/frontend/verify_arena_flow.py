"""作用：两个独立Chrome和临时SQLite验收竞技跨页、三棋盘、结算与原对手续局。
只创建本次临时账号和数据库，不访问业务数据；答案仅测试端离线读取，操作经真实页面。
"""
import base64
from contextlib import ExitStack
from datetime import timedelta
import httpx
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from sqlalchemy import select

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'artifacts/frontend'))
from verify_sudoku import environment
from verify_progress import browser
import verify_ranking as qa
from backend.app.models.entities import User
from backend.app.models.entities.progression import PlayerProgression
from backend.app.models.entities.pk import PKRoom
from backend.app.services import pk_service
from backend.app.services.pk_runtime import runtime
from backend.app.common.security import utc_now
from backend.content_check import sudoku_solutions,akari_solutions


def main():
    """所有浏览器与服务进程均有有界等待，并在finally释放临时测试资源。"""
    checks=[]
    with tempfile.TemporaryDirectory(prefix='arena-flow-browser-') as temporary:
        engine,sessions=environment(Path(temporary)/'qa.sqlite')
        settings=qa.get_settings();settings.pk_rooms_enabled=settings.matchmaking_enabled=True
        listener=socket.socket();listener.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error',lifespan='off'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        stopped=threading.Event()
        def maintain():
            """模拟生产唯一调度任务，不改变前端时间或胜负判断。"""
            while not stopped.wait(.15):
                pk_service.maintenance(sessions)
        scheduler=threading.Thread(target=maintain,daemon=True)
        try:
            for _ in range(200):
                if server.started:break
                time.sleep(.05)
            assert server.started
            for name in ['flowone','flowtwo']:
                with httpx.Client(base_url=base,headers={'Origin':base.rstrip('/')}) as client:
                    response=client.post('api/auth/login',json={'username':name,'password':'arena-flow-test'})
                    assert response.status_code==200,response.status_code
            with sessions() as db:
                for user in db.scalars(select(User)).all():
                    db.add(PlayerProgression(user_id=user.id,xp=72,total_stars=0,revision=0))
                db.commit()
            scheduler.start()
            with ExitStack() as stack:
                logs=[stack.enter_context((ROOT/f'artifacts/frontend/arena-flow-chrome-{i}.log').open('w')) for i in (1,2)]
                clients=[stack.enter_context(browser(str(Path(temporary)/f'chrome{i}'),logs[i-1])) for i in (1,2)]
                def wait(ev,expression,seconds=18):
                    """失败只附当前地址和页面提示，不输出Cookie或整个HTML。"""
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:
                        if ev(f'(()=>{{try{{return Boolean({expression})}}catch{{return false}}}})()'):return
                        time.sleep(.04)
                    with sessions() as db:
                        states=[(r.room_id,r.status,r.reason) for r in db.scalars(select(PKRoom)).all()]
                    raise AssertionError((expression,ev("({path:location.pathname,room:location.search,message:document.getElementById('arena-message')?.textContent,connection:document.getElementById('arena-connection')?.textContent,result:document.getElementById('arena-result-message')?.textContent})"),states))
                def click(ev,selector):
                    """仅操作实际可见且可用的控件。"""
                    value=json.dumps(selector);wait(ev,f'document.querySelector({value})?.getClientRects().length&&!document.querySelector({value}).disabled')
                    ev(f'document.querySelector({value}).click()')
                def shot(cmd,name):
                    """存档原始视口截图供视觉核对。"""
                    (ROOT/'artifacts/frontend'/name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data']))
                def playing():
                    """仅从隔离数据库取当前题目，用于测试机离线求解。"""
                    with sessions() as db:
                        row=db.scalar(select(PKRoom).where(PKRoom.status=='playing'))
                        assert row is not None
                        return row.room_id,row.puzzle['puzzle']
                def start(game):
                    """自动匹配仍要求双方准备，倒计时结束才跳转。"""
                    for _,ev in clients:ev(f"document.getElementById('arena-mode').value='{game}'")
                    for _,ev in clients:click(ev,'#arena-action')
                    for _,ev in clients:wait(ev,"document.getElementById('arena-action')?.textContent==='准备'")
                    click(clients[0][1],'#arena-action')
                    assert clients[1][1]("location.pathname.endsWith('/pk.html')")
                    click(clients[1][1],'#arena-action')
                    for _,ev in clients:wait(ev,"location.pathname.endsWith('/pk-game.html')&&document.querySelectorAll('#arena-board [data-index]').length>0")
                def leave_results():
                    """明确退出释放保留席位，供下一场匹配使用。"""
                    for _,ev in clients:
                        wait(ev,"document.getElementById('arena-result-dialog')?.open")
                        click(ev,'#arena-result-leave');click(ev,'#arena-leave-confirm')
                        wait(ev,"document.getElementById('arena-action')?.textContent==='开始匹配'&&!document.getElementById('arena-action').disabled&&document.getElementById('arena-own-id').textContent.includes('ID')")
                def mobile(cmd,ev,game):
                    """检查手机棋盘整体可见和页面无横向溢出，然后恢复桌面尺寸。"""
                    for width in (375,320):
                        cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':950,'deviceScaleFactor':1,'mobile':False})
                        ev('scrollTo(0,0)');time.sleep(.12)
                        shot(cmd,f'arena-flow-{game}-{width}.png')
                        assert ev('document.documentElement.scrollWidth<=innerWidth'),(game,width,ev("[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth+1).slice(-12).map(n=>({tag:n.tagName,id:n.id,cls:n.className,width:n.getBoundingClientRect().width,right:n.getBoundingClientRect().right}))"))
                        assert ev("(()=>{const b=document.querySelector('#arena-board [role=group]').getBoundingClientRect();return b.left>=0&&b.right<=innerWidth})()"),game
                        shot(cmd,f'arena-flow-{game}-{width}.png')
                    cmd('Emulation.setDeviceMetricsOverride',{'width':1280,'height':1000,'deviceScaleFactor':1,'mobile':False})

                for i,(cmd,ev) in enumerate(clients):
                    cmd('Page.enable');cmd('Runtime.enable');cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
                    cmd('Emulation.setDeviceMetricsOverride',{'width':1280,'height':1000,'deviceScaleFactor':1,'mobile':False})
                    cmd('Page.navigate',{'url':base+'pk.html'});wait(ev,"document.querySelector('.auth-open')")
                    click(ev,'.auth-open');ev(f"document.getElementById('auth-username').value='{['flowone','flowtwo'][i]}';document.getElementById('auth-password').value='arena-flow-test';document.querySelector('.auth-submit').click()")
                    wait(ev,"document.getElementById('arena-action')?.textContent==='开始匹配'&&!document.getElementById('arena-action').disabled")
                (c1,e1),(c2,e2)=clients
                # 先用定向邀请走扫雷开局，验证原大厅流程仍然可用。
                e1("document.getElementById('arena-mode').value='mine'");click(e1,'#arena-invite-open')
                e1("document.getElementById('arena-search-query').value='flowtwo';document.getElementById('arena-search-form').requestSubmit()")
                click(e1,'.arena-search-result button');click(e2,'#arena-incoming-list button')
                for _,ev in clients:wait(ev,"document.getElementById('arena-action')?.textContent==='准备'")
                click(e1,'#arena-action');assert e2("location.pathname.endsWith('/pk.html')")
                click(e2,'#arena-action');assert e1("location.pathname.endsWith('/pk.html')")
                for _,ev in clients:wait(ev,"location.pathname.endsWith('/pk-game.html')&&document.querySelectorAll('.mine-square').length===100")
                rid,puzzle=playing();first_mines=puzzle['mine_indices'];mine=first_mines[0]
                mobile(c1,e1,'mine');shot(c1,'arena-flow-mine-desktop.png')
                click(e2,f'#arena-board [data-index="{mine}"]');assert e2("!document.getElementById('arena-result-dialog').open")
                click(e2,'#arena-board [data-action="mark"]');assert e2(f'document.querySelector(\'[data-index="{mine}"]\').classList.contains("mine-flagged")')
                c2('Page.reload');wait(e2,f'document.querySelector(\'[data-index="{mine}"]\')?.classList.contains("mine-flagged")')
                click(e2,'#arena-board [data-action="mark"]');click(e2,'#arena-board [data-action="reveal"]')
                wait(e1,"document.getElementById('arena-result-dialog')?.open");wait(e2,"document.getElementById('arena-result-dialog')?.open")
                assert e1("document.getElementById('arena-result-title').textContent")=='本局胜利'
                assert e2("document.getElementById('arena-result-title').textContent")=='本局落败'
                shot(c1,'arena-flow-result-desktop.png');checks.append('invite + ready + real navigation + mine selection/flag/reload/loss + both results')
                click(e1,'#arena-return');wait(e1,"document.getElementById('arena-action')?.textContent==='准备'")
                assert e2("document.getElementById('arena-result-dialog').open")
                click(e2,'#arena-rematch');wait(e2,"document.getElementById('arena-action')?.textContent==='取消准备'")
                assert e1("document.getElementById('arena-action').textContent")=='准备'
                click(e1,'#arena-action')
                for _,ev in clients:wait(ev,"location.pathname.endsWith('/pk-game.html')&&document.querySelectorAll('.mine-square').length===100")
                next_id,puzzle=playing();assert next_id!=rid and puzzle['mine_indices']!=first_mines
                click(e1,f'#arena-board [data-index="{puzzle["mine_indices"][0]}"]');click(e1,'#arena-board [data-action="reveal"]')
                leave_results();checks.append('one returns while opponent keeps result; original opponent rematch confirms; new puzzle; release seats')
                start('sudoku');rid,puzzle=playing();answer=sudoku_solutions(puzzle['values'])[0];blank=next(i for i,v in enumerate(puzzle['values']) if not v)
                mobile(c1,e1,'sudoku');click(e1,f'#arena-board [data-index="{blank}"]');click(e1,'[data-action="notes"]');click(e1,'[data-digit="3"]')
                assert e1(f'document.querySelector(\'[data-index="{blank}"] .sudoku-notes\')?.textContent.includes("3")')
                c1('Page.reload');wait(e1,f'document.querySelector(\'[data-index="{blank}"] .sudoku-notes\')?.textContent.includes("3")')
                click(e1,'[data-action="notes"]');click(e1,f'[data-digit="{answer[blank]}"]');click(e1,'[data-action="undo"]')
                assert e1(f'document.querySelector(\'[data-index="{blank}"] .sudoku-notes\')?.textContent.includes("3")')
                for index,value in enumerate(puzzle['values']):
                    if not value:
                        click(e1,f'#arena-board [data-index="{index}"]');click(e1,f'[data-digit="{answer[index]}"]')
                wait(e1,"document.getElementById('arena-result-dialog')?.open");wait(e2,"document.getElementById('arena-result-dialog')?.open")
                assert e1("document.getElementById('arena-result-title').textContent")=='本局胜利'
                leave_results();checks.append('sudoku keypad + notes + undo + reload + automatic verified completion')
                start('akari');rid,puzzle=playing();mobile(c1,e1,'akari');answer=akari_solutions(puzzle['map'])[0]
                for index in answer:click(e1,f'#arena-board [data-index="{index}"]')
                wait(e1,"document.getElementById('arena-result-dialog')?.open");wait(e2,"document.getElementById('arena-result-dialog')?.open")
                assert e1("document.getElementById('arena-result-title').textContent")=='本局胜利'
                leave_results();checks.append('akari campaign layout + constraint feedback + automatic verified completion')
                start('sudoku');rid,_=playing()
                # 仅在隔离库推进到真实服务端截止，不让浏览器伪造胜负。
                with runtime.lock,sessions() as db:
                    row=db.get(PKRoom,rid);row.ends_at=utc_now()-timedelta(seconds=1);row.starts_at=row.ends_at-timedelta(minutes=10);db.commit()
                for _,ev in clients:wait(ev,"document.getElementById('arena-result-dialog')?.open")
                assert e1("document.getElementById('arena-result-title').textContent")=='时间结束'
                assert e2("document.getElementById('arena-result-description').textContent.includes('平局')")
                c1('Page.reload');wait(e1,"document.getElementById('arena-result-dialog')?.open")
                c1('Emulation.setDeviceMetricsOverride',{'width':320,'height':800,'deviceScaleFactor':1,'mobile':False});shot(c1,'arena-flow-timeout-320.png')
                leave_results();checks.append('server timeout + draw + result reload + mobile dialog')
            print('PASS: '+str(len(checks))+' browser scenarios; 320/375 and desktop; no uncaught script exceptions.')
            for item in checks:print('PASS: '+item)
        finally:
            stopped.set()
            if scheduler.is_alive():scheduler.join(3)
            server.should_exit=True;worker.join(10);runtime.reset();engine.dispose()


if __name__=='__main__':main()
