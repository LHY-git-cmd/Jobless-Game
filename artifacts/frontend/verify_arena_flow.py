"""作用：两个独立Chrome和临时SQLite验收竞技跨页、三棋盘、结算与原对手续局。
只创建本次临时账号和数据库，不访问业务数据；答案仅测试端离线读取，操作经真实页面。
"""
import argparse
import base64
from contextlib import ExitStack
from datetime import timedelta
import httpx
import json
from pathlib import Path
import socket
import secrets
import subprocess
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
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gzip',action='store_true',help='通过真实Nginx JSON压缩验证弱ETag与准备')
    parser.add_argument('--ready-only',action='store_true',help='只复验准备/取消、开局跳转和手机首屏布局')
    parser.add_argument('--pool-rounds',type=int,default=0,help='仅验收每种游戏连续2～8局原题去重和近期记录')
    args=parser.parse_args()
    if args.pool_rounds and not 2<=args.pool_rounds<=8:parser.error('--pool-rounds范围为2～8')
    checks=[];proxy_name=None
    with tempfile.TemporaryDirectory(prefix='arena-flow-browser-') as temporary:
        engine,sessions=environment(Path(temporary)/'qa.sqlite')
        settings=qa.get_settings();settings.pk_rooms_enabled=settings.matchmaking_enabled=True
        listener=socket.socket();listener.bind(('0.0.0.0' if args.gzip else '127.0.0.1',0));api_port=listener.getsockname()[1];base=f'http://127.0.0.1:{api_port}/'
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
            if args.gzip:
                # 真实代理只连接本轮临时API，开启JSON gzip改写响应ETag；不连接服务器。
                config=Path(temporary)/'nginx.conf'
                config.write_text('''# 作用：隔离竞技验收代理，复现宝塔JSON gzip产生弱ETag。
events { worker_connections 128; }
http {
  access_log off;
  gzip on;
  gzip_types application/json;
  gzip_min_length 1;
  gzip_proxied any;
  server {
    listen 80;
    location / {
      proxy_pass http://host.docker.internal:API_PORT;
      proxy_set_header Host $http_host;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_http_version 1.1;
      proxy_buffering off;
      proxy_read_timeout 75s;
    }
  }
}
'''.replace('API_PORT',str(api_port)),encoding='utf-8')
                proxy_name='jobless-arena-ready-qa-'+secrets.token_hex(4)
                with (ROOT/'artifacts/frontend/arena-ready-nginx.log').open('w') as proxy_log:
                    subprocess.run(['docker','run','-d','--name',proxy_name,'--add-host','host.docker.internal:host-gateway',
                        '-p','127.0.0.1::80','-v',str(config)+':/etc/nginx/nginx.conf:ro','nginx:1.28-alpine'],check=True,stdout=proxy_log,stderr=proxy_log,creationflags=subprocess.CREATE_NO_WINDOW)
                port=subprocess.check_output(['docker','port',proxy_name,'80/tcp'],text=True).strip().rsplit(':',1)[1]
                base='http://127.0.0.1:'+port+'/'
                for _ in range(100):
                    try:
                        if httpx.get(base+'api/v1/features',timeout=2).status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
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
                clients=[stack.enter_context(browser(str(Path(temporary)/f'chrome{i}'),logs[i-1],command_timeout=30 if args.gzip else 10)) for i in (1,2)]
                def wait(ev,expression,seconds=None):
                    """失败只附当前地址和页面提示，不输出Cookie或整个HTML。"""
                    # 压缩代理额外叠加页面恢复与有界读取重试，等待预算覆盖12秒请求超时。
                    deadline=time.monotonic()+(seconds if seconds is not None else 45 if args.gzip else 18)
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
                    clients[0][0]('Emulation.setDeviceMetricsOverride',{'width':375,'height':667,'deviceScaleFactor':1,'mobile':False})
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
                    for width,height in ((375,667),(320,568),(390,664)):
                        cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':False})
                        ev('scrollTo(0,0)');time.sleep(.12)
                        shot(cmd,f'arena-flow-{game}-{width}.png')
                        assert ev("!document.querySelector('.landing-header,.site-nav,[data-player-profile],.arena-heading,#arena-submit')"),'对局不再显示公共顶部或手动提交'
                        assert ev("Boolean(document.getElementById('arena-clock').closest('#arena-game .section-heading'))"),'计时放在原双方同题位置'
                        assert ev('document.documentElement.scrollWidth<=innerWidth'),(game,width,ev("[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth+1).slice(-12).map(n=>({tag:n.tagName,id:n.id,cls:n.className,width:n.getBoundingClientRect().width,right:n.getBoundingClientRect().right}))"))
                        assert ev("(()=>{const b=document.querySelector('#arena-board [role=group]').getBoundingClientRect();return b.left>=0&&b.right<=innerWidth&&b.top>=0&&b.bottom<=innerHeight})()"),(game,width,'整盘首次可见')
                        if game=='sudoku':
                            assert ev("document.querySelector('#arena-board .sudoku-board').getBoundingClientRect().width>=180"),'小屏数独保留可读棋盘'
                        shot(cmd,f'arena-flow-{game}-{width}.png')
                    cmd('Emulation.setDeviceMetricsOverride',{'width':1280,'height':1000,'deviceScaleFactor':1,'mobile':False})

                for i,(cmd,ev) in enumerate(clients):
                    cmd('Page.enable');cmd('Runtime.enable');cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
                    cmd('Emulation.setDeviceMetricsOverride',{'width':1280,'height':1000,'deviceScaleFactor':1,'mobile':False})
                    cmd('Page.navigate',{'url':base+'pk.html'});wait(ev,"document.querySelector('.auth-open')")
                    click(ev,'.auth-open');ev(f"document.getElementById('auth-username').value='{['flowone','flowtwo'][i]}';document.getElementById('auth-password').value='arena-flow-test';document.querySelector('.auth-submit').click()")
                    wait(ev,"document.getElementById('arena-action')?.textContent==='开始匹配'&&!document.getElementById('arena-action').disabled")
                (c1,e1),(c2,e2)=clients
                if args.pool_rounds:
                    from backend.app.models.entities.arena import ArenaPuzzleHistory
                    for game in ('akari','sudoku'):
                        previous=[];start(game)
                        for round_index in range(args.pool_rounds):
                            rid,puzzle=playing()
                            with sessions() as db:
                                row=db.get(PKRoom,rid);identity=row.puzzle['base_puzzle_id']
                                assert identity not in previous[-4:],(game,'repeated original')
                                previous.append(identity)
                                for user in db.scalars(select(User)).all():
                                    history=db.get(ArenaPuzzleHistory,(user.id,game))
                                    assert [item['base_puzzle_id'] for item in history.recent]==previous[-4:]
                            snapshots=[]
                            for cmd,ev in clients:
                                cmd('Runtime.evaluate',{'expression':"fetch('/api/v1/rooms/'+new URLSearchParams(location.search).get('room')).then(r=>r.json()).then(v=>{window.qaPoolRoom=v})",'awaitPromise':True})
                                wait(ev,'Boolean(window.qaPoolRoom?.base_puzzle_id)')
                                snapshots.append(ev('window.qaPoolRoom'))
                            assert snapshots[0]['base_puzzle_id']==snapshots[1]['base_puzzle_id']==identity
                            assert snapshots[0]['puzzle']==snapshots[1]['puzzle']==puzzle
                            # 推进隔离测试局截止时间，经真实唯一调度器结算，不自报玩家胜者。
                            with runtime.lock,sessions() as db:
                                row=db.get(PKRoom,rid);row.ends_at=utc_now()-timedelta(seconds=1);row.starts_at=row.ends_at-timedelta(minutes=10);db.commit()
                            for _,ev in clients:wait(ev,"document.getElementById('arena-result-dialog')?.open")
                            if round_index+1<args.pool_rounds:
                                for _,ev in clients:click(ev,'#arena-rematch')
                                for _,ev in clients:wait(ev,"location.pathname.endsWith('/pk-game.html')&&new URLSearchParams(location.search).get('room')!=="+json.dumps(rid)+"&&document.querySelectorAll('#arena-board [data-index]').length>0")
                        leave_results()
                    print(f'PASS: two real browsers; {args.pool_rounds} rounds per game; same original and puzzle for both; last-four exclusion and bounded persistent histories; rematches freeze new originals.')
                    return
                # 先用定向邀请走扫雷开局，验证原大厅流程仍然可用。
                e1("document.getElementById('arena-mode').value='mine'");click(e1,'#arena-invite-open')
                e1("document.getElementById('arena-search-query').value='flowtwo';document.getElementById('arena-search-form').requestSubmit()")
                click(e1,'.arena-search-result button');click(e2,'#arena-incoming-list button')
                for _,ev in clients:wait(ev,"document.getElementById('arena-action')?.textContent==='准备'")
                # 首次开局前就使用手机尺寸，验证进入时无需额外缩放或旋转即可整盘可见。
                c1('Emulation.setDeviceMetricsOverride',{'width':390,'height':664,'deviceScaleFactor':1,'mobile':False})
                if args.gzip:
                    # 以浏览器自己的Accept-Encoding读取真实代理，验证确实命中弱标签路径。
                    c1('Runtime.evaluate',{'expression':"fetch('/api/v1/me/arena/state').then(r=>r.json()).then(v=>fetch(v.room.links.self)).then(r=>{window.qaRoomTag=r.headers.get('ETag')})",'awaitPromise':True})
                    wait(e1,"typeof window.qaRoomTag==='string'&&window.qaRoomTag.startsWith('W/')")
                    # 明确验证后端仍拒绝原样弱If-Match，修复只作用于核验后的前端条件写。
                    c1('Runtime.evaluate',{'expression':"fetch('/api/v1/me/arena/state').then(r=>r.json()).then(v=>fetch(v.room.links.readiness,{method:'PUT',headers:{'Content-Type':'application/json','If-Match':window.qaRoomTag},body:JSON.stringify({ready:true})})).then(r=>{window.qaWeakReadyStatus=r.status})",'awaitPromise':True})
                    assert e1('window.qaWeakReadyStatus')==412
                click(e1,'#arena-action');assert e2("location.pathname.endsWith('/pk.html')")
                if args.gzip:
                    wait(e1,"document.getElementById('arena-action')?.textContent==='取消准备'")
                    click(e1,'#arena-action')
                    wait(e1,"document.getElementById('arena-action')?.textContent==='准备'")
                    click(e1,'#arena-action')
                    wait(e1,"document.getElementById('arena-action')?.textContent==='取消准备'")
                click(e2,'#arena-action');assert e1("location.pathname.endsWith('/pk.html')")
                for _,ev in clients:wait(ev,"location.pathname.endsWith('/pk-game.html')&&document.querySelectorAll('.mine-square').length===100")
                rid,puzzle=playing();first_mines=puzzle['mine_indices'];mine=first_mines[0]
                mobile(c1,e1,'mine');shot(c1,'arena-flow-mine-desktop.png')
                if args.ready_only:
                    print('PASS: ready/cancel + both-player countdown + game navigation + compact first mobile board.'+(' Real Nginx gzip weak ETag validated; raw weak If-Match rejected.' if args.gzip else ''))
                    return
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
                # 无提交按钮时，首次发送失败必须自动重试相同终盘，不能要求玩家再点击提交。
                e1("window.qaSubmitBodies=[];window.qaFetch=window.fetch;window.fetch=(url,options)=>{if(String(url).endsWith('/submissions/me')){window.qaSubmitBodies.push(options.body);if(window.qaSubmitBodies.length===1)return Promise.reject(new TypeError('isolated network interruption'));}return window.qaFetch(url,options)}")
                for index,value in enumerate(puzzle['values']):
                    if not value:
                        click(e1,f'#arena-board [data-index="{index}"]');click(e1,f'[data-digit="{answer[index]}"]')
                wait(e1,"document.getElementById('arena-result-dialog')?.open");wait(e2,"document.getElementById('arena-result-dialog')?.open")
                assert e1("document.getElementById('arena-result-title').textContent")=='本局胜利'
                assert e1('window.qaSubmitBodies.length===2&&window.qaSubmitBodies[0]===window.qaSubmitBodies[1]')
                leave_results();checks.append('sudoku keypad + notes + undo + reload + automatic completion and network retry')
                start('akari');rid,puzzle=playing();mobile(c1,e1,'akari');answer=akari_solutions(puzzle['map'])[0]
                # 首次提交故障后刷新，页面从同局草稿自动恢复终盘并提交。
                e1("window.qaFetch=window.fetch;window.qaSubmitFailed=false;window.fetch=(url,options)=>{if(String(url).endsWith('/submissions/me')){window.qaSubmitFailed=true;return Promise.reject(new TypeError('isolated reload recovery'));}return window.qaFetch(url,options)}")
                for index in answer:click(e1,f'#arena-board [data-index="{index}"]')
                wait(e1,'window.qaSubmitFailed');c1('Page.reload')
                wait(e1,"document.getElementById('arena-result-dialog')?.open");wait(e2,"document.getElementById('arena-result-dialog')?.open")
                assert e1("document.getElementById('arena-result-title').textContent")=='本局胜利'
                leave_results();checks.append('akari complete draft reload + constraint feedback + automatic verified completion')
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
            print('PASS: '+str(len(checks))+' browser scenarios; 320/375 and desktop; no uncaught script exceptions.'+(' Real Nginx gzip + weak ETag + ready/cancel + weak If-Match rejection.' if args.gzip else ''))
            for item in checks:print('PASS: '+item)
        finally:
            stopped.set()
            if scheduler.is_alive():scheduler.join(3)
            server.should_exit=True;worker.join(10);runtime.reset();engine.dispose()
            if proxy_name:
                # 仅删除本次随机命名验收容器，不触碰已有Nginx或数据库。
                subprocess.run(['docker','rm','-f',proxy_name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)


if __name__=='__main__':main()
