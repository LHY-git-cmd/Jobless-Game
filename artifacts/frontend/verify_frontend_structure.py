"""作用：目录整改前后真实浏览器同状态截图比较及当前页面/资源/分榜入口验收。

只用两个临时只读静态站点和固定API夹具，不连接业务库；旧版本从已确认Git提交归档。
"""
import base64
import functools
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse,parse_qs
import zipfile
from PIL import Image,ImageChops

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.app.common.game_catalog import MINE_LEVELS,metadata
from verify_progress import browser


class Handler(SimpleHTTPRequestHandler):
    """与数据无关的账号/榜单/选关样例用于比较页面，不创建正式尝试。"""
    def log_message(self,*_):
        """不输出静态访问日志。"""
        pass
    def json(self,value,status=200):
        """两站点返回完全相同的固定数据。"""
        body=json.dumps(value).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        """仅GET夹具；未知API返回404，不能掩盖漏接入口。"""
        path=urlparse(self.path).path;query=parse_qs(urlparse(self.path).query)
        if path=='/api/auth/me':return self.json({'id':1,'username':'结构验收','avatar_id':17})
        if path=='/api/v1/features':return self.json({'progression':False,'cosmetics':False,'pk_rooms':False,'matchmaking':False})
        if path=='/api/v1/me/progression':return self.json({'xp':160,'level':2,'total_stars':6,'next_level_xp':180})
        if path=='/api/v1/levels':return self.json({'items':[metadata(level) for level in MINE_LEVELS]})
        if path=='/api/records/me':return self.json({'category':query.get('category',['mine'])[0],'best':None,'recent':[]})
        if path=='/api/forum/notifications/unread-count':return self.json({'count':0,'latest_id':0})
        if path.startswith('/api/rankings/'):
            page=int(query.get('page',['1'])[0]);category=path.split('/')[-1]
            return self.json({'category':category,'page':page,'page_size':20,'total':21,'entries':[
                {'rank':1 if page==1 else 21,'user_id':1 if page==1 else 2,'username':'结构验收' if page==1 else '第二页玩家',
                 'avatar_id':17,'duration_seconds':60 if page==1 else 120,'completed_at':'2026-10-22T00:00:00Z'}]})
        if path.startswith('/api/'):return self.json({'detail':'未配置的只读夹具'},404)
        return super().do_GET()


def main():
    """固定读取数据和视口比较CSS移动前后渲染，并验证新模块HTTP没有断链。"""
    checks=[];servers=[]
    with tempfile.TemporaryDirectory(prefix='frontend-structure-') as temporary:
        folder=Path(temporary);archive=folder/'baseline.zip'
        subprocess.run(['git','archive','--format=zip','-o',str(archive),'26bb1aa','frontend'],cwd=ROOT,check=True)
        with zipfile.ZipFile(archive) as bundle:bundle.extractall(folder/'baseline')
        roots=[folder/'baseline/frontend',ROOT/'frontend']
        for root in roots:
            server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(root)))
            threading.Thread(target=server.serve_forever,daemon=True).start();servers.append(server)
        try:
            with (ROOT/'artifacts/frontend/structure-visual-chrome.log').open('w',encoding='utf-8') as log,browser(str(folder/'chrome'),log) as (cmd,ev):
                cmd('Page.enable');cmd('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
                def wait(expression):
                    """等待真实模块及素材，失败只报告条件和页面标题。"""
                    until=time.monotonic()+15
                    while time.monotonic()<until:
                        if ev(f'(()=>{{try{{return Boolean({expression});}}catch{{return false;}}}})()'):return
                        time.sleep(.04)
                    raise AssertionError((expression,ev('document.title')))
                def shot():
                    """编码截图后按像素比较，记录差异数量而不是只比文件大小。"""
                    return base64.b64decode(cmd('Page.captureScreenshot',{'format':'png'})['data'])
                cases=[('index.html',"document.querySelector('.auth-username')?.textContent==='结构验收' && document.querySelectorAll('.level-card').length===3"),
                       ('journey.html?game_id=mine',"document.querySelectorAll('.mine-spec').length===3"),
                       ('ranking-mine.html',"document.querySelector('#ranking-rows')?.textContent.includes('结构验收')")]
                for width,height in ((1440,1100),(375,812),(320,812)):
                    cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<700})
                    for route,condition in cases:
                        images=[]
                        for server in servers:
                            cmd('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/{route}'})
                            wait(condition);wait("Array.from(document.images).every(image=>image.complete&&image.naturalWidth>0)")
                            wait("document.querySelector('.auth-username')?.textContent==='结构验收'")
                            if not route.startswith('ranking-'):
                                wait("document.querySelector('.player-level').textContent==='Lv.2'")
                            time.sleep(.15);images.append(shot())
                        before,after=[Image.open(io.BytesIO(value)).convert('RGB') for value in images]
                        difference=ImageChops.difference(before,after)
                        changed=sum(pixel!=(0,0,0) for pixel in (difference.get_flattened_data() if hasattr(difference,'get_flattened_data') else difference.getdata()))
                        ratio=changed/(width*height)
                        assert ratio<.001,(route,width,changed)
                        (ROOT/'artifacts/frontend'/f'structure-{route.split(".")[0]}-{width}.png').write_bytes(images[1])
                        checks.append(f'{route} {width}px 像素差异{changed}')
                for category in ('mine','akari','sudoku'):
                    cmd('Page.navigate',{'url':f'http://127.0.0.1:{servers[1].server_port}/ranking-{category}.html'})
                    wait("document.querySelector('#ranking-rows').textContent.includes('结构验收')")
                    ev("document.getElementById('ranking-next').click()")
                    wait("document.querySelector('#ranking-rows').textContent.includes('第二页玩家')")
                    assert ev("document.getElementById('ranking-page').textContent==='2 / 2'")
                    assert not ev("performance.getEntriesByType('resource').some(r=>r.responseStatus>=400)")
                checks.append('三个独立分榜新入口与真实按钮分页正常、资源无404')
                for game in ('akari','sudoku'):
                    cmd('Page.navigate',{'url':f'http://127.0.0.1:{servers[1].server_port}/journey.html?game_id={game}'})
                    wait(f"document.body.dataset.game==='{game}' && document.querySelector('.player-level').textContent==='Lv.2'")
                    assert ev("!document.getElementById('catalog-empty').hidden")
                    assert not ev("performance.getEntriesByType('resource').some(r=>r.responseStatus>=400)")
                checks.append('照明/数独入口占位与共享账号模块正常')
                cmd('Page.navigate',{'url':f'http://127.0.0.1:{servers[1].server_port}/mine-practice.html'})
                wait("location.pathname==='/journey.html' && document.body.dataset.game==='mine'")
                checks.append('历史练习URL继续跳转当前扫雷')
        finally:
            for server in servers:server.shutdown();server.server_close()
    print(json.dumps({'checks_passed':len(checks),'checks':checks,'uncaught_errors':0},ensure_ascii=False))


if __name__=='__main__':main()
