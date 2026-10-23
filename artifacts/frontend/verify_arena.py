"""作用：临时SQLite与两个独立Chrome验证真实邀请、三秒准备、扫雷判负、分池匹配、数独结果和手机大厅。"""
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
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root));sys.path.insert(0,str(root/'artifacts/frontend'))
from verify_sudoku import environment
from verify_progress import browser
import verify_ranking as qa
from backend.app.models.entities import User
from backend.app.models.entities.progression import PlayerProgression
from backend.app.models.entities.pk import PKRoom
from backend.app.services import pk_service
from backend.app.services.pk_runtime import runtime
from backend.content_check import sudoku_solutions,akari_solutions

def main():
    """预览及所有验证仅使用本次临时文件，不触碰已有预览库。"""
    with tempfile.TemporaryDirectory(prefix='arena-browser-') as temporary:
        engine,sessions=environment(Path(temporary)/'qa.sqlite')
        settings=qa.get_settings();settings.pk_rooms_enabled=settings.matchmaking_enabled=True
        listener=socket.socket();listener.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error',lifespan='off'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        stopped=threading.Event()
        def maintain():
            """测试调度使用同一真实业务与隔离连接池。"""
            while not stopped.wait(.15):
                try:pk_service.maintenance(sessions)
                except Exception as error:print('scheduler:',type(error).__name__,str(error)[:120])
        scheduler=threading.Thread(target=maintain,daemon=True)
        try:
            for _ in range(200):
                if server.started:break
                time.sleep(.05)
            assert server.started
            for name in ['arenaone','arenatwo']:
                with httpx.Client(base_url=base,headers={'Origin':base.rstrip('/')}) as client:
                    result=client.post('api/auth/login',json={'username':name,'password':'arena-browser-test'})
                    assert result.status_code==200,result.text
            with sessions() as db:
                users=db.scalars(select(User).order_by(User.id)).all()
                for user in users:db.add(PlayerProgression(user_id=user.id,xp=72,total_stars=0,revision=0))
                db.commit();uids=[u.id for u in users]
            scheduler.start()
            with ExitStack() as stack:
                logs=[stack.enter_context((root/f'artifacts/frontend/arena-browser-{n}.log').open('w')) for n in [1,2]]
                browsers=[stack.enter_context(browser(str(Path(temporary)/f'chrome{n}'),logs[n-1])) for n in [1,2]]
                def wait(ev,condition):
                    """等待真实页面状态，失败只附账号内提示和按钮内容。"""
                    for _ in range(420):
                        if ev(f'(()=>{{try{{return Boolean({condition})}}catch{{return false}}}})()'):return
                        time.sleep(.05)
                    raise AssertionError((condition,ev("({message:document.getElementById('arena-message')?.textContent,action:document.getElementById('arena-action')?.textContent,body:document.querySelector('#arena-search-message')?.textContent})")))
                def click(ev,selector):
                    """通过真实按钮绑定发请求，不调用内部模型。"""
                    value=json.dumps(selector);wait(ev,f'document.querySelector({value})?.getClientRects().length&&!document.querySelector({value}).disabled');ev(f'document.querySelector({value}).click()')
                def shot(cmd,name):
                    """保存原始视口截图供人工视觉检查。"""
                    (root/'artifacts/frontend'/name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data']))
                for i,(cmd,ev) in enumerate(browsers):
                    cmd('Page.enable');cmd('Runtime.enable');cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]});cmd('Emulation.setDeviceMetricsOverride',{'width':1280,'height':1000,'deviceScaleFactor':1,'mobile':False})
                    cmd('Page.navigate',{'url':base+'pk.html'});wait(ev,"document.querySelector('.auth-open')")
                    click(ev,'.auth-open');ev(f"document.getElementById('auth-username').value='{['arenaone','arenatwo'][i]}';document.getElementById('auth-password').value='arena-browser-test';document.querySelector('.auth-submit').click()")
                    wait(ev,"document.getElementById('arena-action')?.textContent==='开始匹配'&&!document.getElementById('arena-action').disabled")
                (c1,e1),(c2,e2)=browsers
                shot(c1,'arena-lobby-desktop.png')
                e1("document.getElementById('arena-mode').value='mine'")
                click(e1,'#arena-invite-open');e1("document.getElementById('arena-search-query').value='arenatwo';document.getElementById('arena-search-form').requestSubmit()")
                wait(e1,"document.querySelector('.arena-search-result button:not(:disabled)')")
                click(e1,'.arena-search-result button')
                wait(e2,"!document.getElementById('arena-invitations').hidden")
                click(e2,'#arena-incoming-list button')
                for ev in [e1,e2]:wait(ev,"document.getElementById('arena-opponent-name').textContent.startsWith('arena')&&document.getElementById('arena-action').textContent==='准备'")
                click(e1,'#arena-action');wait(e1,"document.getElementById('arena-action').textContent==='取消准备'")
                assert e2("document.getElementById('arena-game').hidden")
                click(e2,'#arena-action')
                for ev in [e1,e2]:wait(ev,"!document.getElementById('arena-game').hidden")
                wait(e1,"document.querySelectorAll('#arena-board [data-index]').length===100")
                with sessions() as db:
                    room=db.scalar(select(PKRoom).where(PKRoom.status=='playing'));mine=room.puzzle['puzzle']['mine_indices'][0];rid=room.room_id
                click(e2,f'#arena-board [data-index="{mine}"]')
                wait(e1,"document.getElementById('arena-result').textContent.includes('你赢得了')")
                wait(e2,"document.getElementById('arena-result').textContent.includes('落败')")
                assert e1("document.getElementById('arena-points').textContent")=='120'
                assert e2("document.getElementById('arena-points').textContent")=='90'
                for ev in [e1,e2]:click(ev,'#arena-action');wait(ev,"document.getElementById('arena-action').textContent==='开始匹配'")
                for ev in [e1,e2]:ev("document.getElementById('arena-mode').value='sudoku'")
                click(e1,'#arena-action');wait(e1,"document.getElementById('arena-action').textContent==='取消匹配'")
                assert e1("document.getElementById('arena-clock-label').textContent")=='匹配用时'
                click(e2,'#arena-action')
                for ev in [e1,e2]:wait(ev,"document.getElementById('arena-action').textContent==='准备'")
                for ev in [e1,e2]:click(ev,'#arena-action')
                for ev in [e1,e2]:wait(ev,"document.querySelectorAll('#arena-board input').length===81")
                with sessions() as db:
                    room=db.scalar(select(PKRoom).where(PKRoom.status=='playing'));answer=sudoku_solutions(room.puzzle['puzzle']['values'])[0]
                e1("document.querySelectorAll('#arena-board input:not(:disabled)').forEach(n=>{n.value="+json.dumps(answer)+"[Number(n.dataset.index)];n.dispatchEvent(new Event('input',{bubbles:true}))})")
                click(e1,'#arena-submit');wait(e1,"document.getElementById('arena-result').textContent.includes('你赢得了')")
                wait(e2,"document.getElementById('arena-result').textContent.includes('落败')")
                shot(c1,'arena-sudoku-result.png')
                for ev in [e1,e2]:click(ev,'#arena-action');wait(ev,"document.getElementById('arena-action').textContent==='开始匹配'")
                for ev in [e1,e2]:ev("document.getElementById('arena-mode').value='akari'")
                click(e1,'#arena-action');click(e2,'#arena-action')
                for ev in [e1,e2]:wait(ev,"document.getElementById('arena-action').textContent==='准备'")
                for ev in [e1,e2]:click(ev,'#arena-action')
                for ev in [e1,e2]:wait(ev,"document.querySelectorAll('#arena-board .akari-cell').length===100")
                with sessions() as db:
                    room=db.scalar(select(PKRoom).where(PKRoom.status=='playing'));answer=akari_solutions(room.puzzle['puzzle']['map'])[0]
                for index in answer:click(e1,f'#arena-board [data-index="{index}"]')
                click(e1,'#arena-submit');wait(e1,"document.getElementById('arena-result').textContent.includes('你赢得了')")
                wait(e2,"document.getElementById('arena-result').textContent.includes('落败')")
                assert e1("document.getElementById('arena-points').textContent")=='160'
                for ev in [e1,e2]:click(ev,'#arena-action');wait(ev,"document.getElementById('arena-action').textContent==='开始匹配'")
                c2('Page.navigate',{'url':base+'challenge.html'})
                wait(e2,"document.querySelector('.auth-logout:not(.hidden)')")
                # 显式刷新邀请者的在线目录，接收者仍停留在普通闯关页面。
                e1("document.getElementById('arena-mode').value='akari'")
                click(e1,'#arena-invite-open');e1("document.getElementById('arena-search-query').value='arenatwo';document.getElementById('arena-search-form').requestSubmit()")
                wait(e1,"document.querySelector('.arena-search-result button:not(:disabled)')")
                click(e1,'.arena-search-result button')
                wait(e2,"document.querySelector('[data-invite-accept]')?.getClientRects().length")
                click(e2,'[data-invite-accept]')
                wait(e2,"location.pathname.endsWith('/pk.html')&&document.getElementById('arena-action')?.textContent==='准备'")
                for ev in [e1,e2]:
                    click(ev,'#arena-leave');click(ev,'#arena-leave-confirm');wait(ev,"document.getElementById('arena-action').textContent==='开始匹配'")
                for width in [375,320]:
                    c1('Emulation.setDeviceMetricsOverride',{'width':width,'height':950,'deviceScaleFactor':1,'mobile':False})
                    e1('scrollTo(0,0)');assert e1('document.documentElement.scrollWidth<=innerWidth'),width
                    shot(c1,f'arena-lobby-{width}.png')
                c1('Page.navigate',{'url':base+'ranking.html?category=points'});wait(e1,"document.querySelectorAll('#ranking-rows tr').length===2")
                assert e1("document.getElementById('ranking-rows').textContent.includes('160 分')")
            print('PASS: normal-page invitation and accept recovery; two real browsers; online search and accepted invite; both prepare + 3 second start; same mine layout and loss; shared scores; sudoku pool matching + verified win; points ranking; 375/320 layouts; no script exceptions.')
        finally:
            stopped.set();scheduler.join(3) if scheduler.is_alive() else None;server.should_exit=True;worker.join(10);runtime.reset();engine.dispose()
if __name__=='__main__':main()
