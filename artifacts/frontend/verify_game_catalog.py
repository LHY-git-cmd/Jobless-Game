"""作用：临时静态站点验证三卡独立选关、旧关卡下线、成长数据、导航动画及窄屏，不访问数据库。"""
import base64
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root/'artifacts/frontend'))
from verify_progress import browser


class Handler(SimpleHTTPRequestHandler):
    """只提供隔离的读取夹具，记录所有写请求和题目访问以断言首页不再开局。"""
    writes, reads = [], []
    progression_enabled = True
    def log_message(self, *_):
        """不输出常规静态访问日志。"""
        pass
    def json(self, data, status=200):
        """小体积测试响应，数据只属于此临时站点。"""
        encoded = json.dumps(data).encode()
        self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
    def do_GET(self):
        """成长读取使用固定样例，未知API明确404，不模拟实际关卡。"""
        path = urlparse(self.path).path
        if path.startswith('/api/'):
            Handler.reads.append(path)
        if path == '/api/auth/me':
            return self.json({'id':1,'username':'选关测试','avatar_id':17})
        if path == '/api/v1/features':
            return self.json({'progression':self.progression_enabled,'cosmetics':False,'pk_rooms':False,'matchmaking':False})
        if path == '/api/v1/me/progression':
            return self.json({'xp':160,'level':2,'total_stars':6,'next_level_xp':180})
        if path == '/api/v1/me/pk-eligibility':
            return self.json({'eligible':False,'requirements':[{'level_id':key,'name':name,'completed':i<2} for i,(key,name) in enumerate([('mine-beginner-001','扫雷初级'),('akari-001','照明第1关'),('sudoku-beginner-001','数独初级')])]})
        if path == '/api/records/me':
            return self.json({'category':'mine','best':None,'recent':[]})
        if path == '/api/forum/notifications/unread-count':
            return self.json({'count':0,'latest_id':0})
        if path.startswith('/api/'):
            return self.json({'detail':'test fixture unavailable'},404)
        return super().do_GET()
    def do_POST(self):
        """本轮页面不应创建任何尝试或旧挑战。"""
        Handler.writes.append(self.path); self.json({},405)
    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


server = ThreadingHTTPServer(('127.0.0.1',0), functools.partial(Handler,directory=str(root/'frontend')))
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix='game-catalog-') as temp, (root/'artifacts/frontend/game-catalog-chrome.log').open('w') as log:
        with browser(temp,log) as (cmd,ev):
            cmd('Page.enable')
            cmd('Page.addScriptToEvaluateOnNewDocument',{'source':"window.addEventListener('pagereveal',e=>{const v=e.viewTransition;window.catalogAnimated=!!v;window.catalogDone=!v;if(v){v.ready.catch(()=>{});v.finished.then(()=>window.catalogDone=true).catch(()=>{})}})"})
            def wait(expression):
                """以页面条件等待，失败仅返回可见标题/状态。"""
                for _ in range(120):
                    if ev(f'(() => {{try{{return Boolean({expression});}}catch{{return false;}}}})()'):
                        return
                    time.sleep(.05)
                raise AssertionError((expression,ev("({path:location.href,title:document.title,status:document.getElementById('journey-status')?.textContent})")))
            def shot(name):
                """截取实际视口以核对空目录和窄屏布局。"""
                (root/'artifacts/frontend'/name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data']))
            base = f'http://127.0.0.1:{server.server_port}/'
            cmd('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
            cmd('Page.navigate',{'url':base+'index.html'})
            wait("document.querySelectorAll('.level-card[data-game]').length===3 && document.querySelector('.auth-username')?.textContent==='选关测试'")
            assert ev("!document.querySelector('#game-screen,#akari-screen,#sudoku-screen,#rules-dialog,#result-dialog')")
            assert not ev("performance.getEntriesByType('resource').some(r=>r.name.includes('/game/game-controller.js'))")
            ev("localStorage.setItem('jobless-progress-v1:1','legacy-snapshot-kept')")
            shot('home-new-catalog.png')
            for game, name in [('mine','扫雷'),('akari','照明'),('sudoku','数独')]:
                ev(f"document.querySelector('.level-card[data-game=\"{game}\"]').click()")
                wait(f"document.body.dataset.game==='{game}' && document.getElementById('catalog-empty-title').textContent.includes('{name}') && window.catalogDone")
                assert ev('window.catalogAnimated===true')
                wait("document.getElementById('journey-summary').textContent.includes('160 经验')")
                assert ev("!document.querySelector('#formal-board,#journey-levels,[data-level]')")
                assert ev("localStorage.getItem('jobless-progress-v1:1')==='legacy-snapshot-kept'")
                if game == 'mine':
                    shot('mine-new-catalog.png')
                    cmd('Page.reload'); wait("document.body.dataset.game==='mine' && document.getElementById('journey-level').textContent==='Lv.2'")
                ev("document.querySelector('a[href=\"./index.html\"]').click()")
                wait("location.pathname==='/index.html' && window.catalogDone && document.querySelectorAll('.level-card').length===3")
            cmd('Page.navigate',{'url':base+'journey.html?level=sudoku-beginner-001'})
            wait("document.body.dataset.game==='sudoku'")
            assert ev("!document.querySelector('#formal-board')")
            cmd('Page.navigate',{'url':base+'mine-practice.html'})
            wait("location.pathname==='/journey.html' && document.body.dataset.game==='mine'")
            for width in (375,320,812):
                cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':812 if width<800 else 375,'deviceScaleFactor':1,'mobile':True})
                assert ev('document.documentElement.scrollWidth<=innerWidth'), f'{width}px选关页横向溢出'
                if width == 375:
                    shot('catalog-mobile.png')
            cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
            ev("document.querySelector('#catalog-games [data-game=\"akari\"]').click()")
            wait("document.body.dataset.game==='akari' && window.catalogDone")
            assert ev('window.catalogAnimated===false')
            Handler.progression_enabled = False
            cmd('Page.reload')
            wait("document.body.dataset.game==='akari' && document.getElementById('journey-summary').textContent==='经验与星数暂不可用'")
            assert ev("document.getElementById('catalog-empty').getClientRects().length>0")
            assert not Handler.writes, Handler.writes
            assert not any('/attempts' in path or path.endswith('/levels') or path.startswith('/api/challenges/') for path in Handler.reads), Handler.reads
            print('Game catalog browser: 3 routes/refresh/return/legacy offline/growth/zero game writes/native motion/320-375-812px PASS')
finally:
    server.shutdown(); server.server_close()
