"""作用：隔离Nginx开启gzip，真实浏览器验证数独退出与强版本保护；不连接业务MySQL。

使用两个随机命名临时容器及私有网络，结束仅清理本轮容器；原有本机服务和服务器不受影响。
"""
import argparse
import json
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import httpx
from verify_progress import browser

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'artifacts/frontend'


def main():
    """真实gzip代理重现弱ETag，同时保留后端对弱If-Match及过期版本的拒绝。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-failure',action='store_true')
    args=parser.parse_args()
    name='jobless-exit-qa-'+secrets.token_hex(4)
    with tempfile.TemporaryDirectory(prefix='exit-gzip-') as temporary, (OUTPUT/'exit-gzip-docker.log').open('w',encoding='utf-8') as log:
        folder=Path(temporary)
        bootstrap='''"""作用：只在/tmp临时SQLite创建游戏测试数据，替代默认数据库依赖。"""
import sys
sys.path.insert(0,'/app')
from sqlalchemy import create_engine
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
import uvicorn
from backend.app import main
from backend.app.common.database import Base,get_db
from backend.app.common.config import get_settings
from backend.app.common.game_catalog import LEVELS,LEVEL_VERSIONS
from backend.app.models.entities.progression import GameLevel,GameLevelVersion
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse
@compiles(BIGINT,'sqlite')
def qa_bigint(element,compiler,**kwargs):
    """仅隔离SQLite使用INTEGER主键自增，正式MySQL映射不变。"""
    return 'INTEGER'
engine=create_engine('sqlite:////tmp/exit-qa.sqlite',connect_args={'check_same_thread':False})
Base.metadata.create_all(engine)
sessions=sessionmaker(engine,expire_on_commit=False,autoflush=False)
with sessions() as db:
    for item in LEVELS.values():db.add(GameLevel(level_id=item['level_id'],game_id=item['game_id'],order_index=item['order']))
    for item in LEVEL_VERSIONS.values():db.add(GameLevelVersion(level_id=item['level_id'],level_version=item['level_version'],definition=item))
    db.commit()
def dependency():
    """每个请求使用独立隔离库连接，不访问默认MySQL。"""
    with sessions() as db:yield db
main.app.dependency_overrides[get_db]=dependency
async def qa_error(request,error):
    """隔离库诊断只输出底层错误类型，不打印SQL参数或任何凭据。"""
    print(type(error).__name__,str(getattr(error,'orig',type(error).__name__)),flush=True)
    return JSONResponse({'detail':'isolated database error'},status_code=503)
main.app.add_exception_handler(SQLAlchemyError,qa_error)
settings=get_settings()
settings.progression_enabled=True
settings.cookie_secure=False
uvicorn.run(main.app,host='0.0.0.0',port=8001,log_level='error',lifespan='off')
'''
        (folder/'bootstrap.py').write_bytes(bootstrap.encode('utf-8'))
        config=f'''# 作用：仅本轮临时代理启用JSON压缩，复现宝塔全局gzip对ETag的改写。
events {{ worker_connections 128; }}
http {{
  access_log off;
  gzip on;
  gzip_types application/json;
  gzip_min_length 1;
  gzip_proxied any;
  server {{
    listen 80;
    location / {{
      proxy_pass http://{name}-api:8001;
      proxy_set_header Host $http_host;
      proxy_set_header X-Forwarded-Proto $scheme;
    }}
  }}
}}
'''
        (folder/'nginx.conf').write_bytes(config.encode('utf-8'))
        listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1];listener.close()

        def docker(*arguments,check=True):
            """容器操作日志仅保留本地文件，限定随机测试容器名称。"""
            return subprocess.run(['docker',*arguments],cwd=ROOT,stdout=log,stderr=log,check=check)

        try:
            docker('network','create',name)
            docker('run','-d','--name',name+'-api','--network',name,'--memory','320m','--cpus','1','--read-only','--tmpfs','/tmp:size=32m,mode=1777',
                '-v',str(folder)+':/qa:ro','-v',str(ROOT/'frontend')+':/app/frontend:ro','--entrypoint','python','jobless-game-api:server','/qa/bootstrap.py')
            docker('run','-d','--name',name+'-web','--network',name,'--memory','64m','--cpus','.25',
                '-p',f'127.0.0.1:{port}:80','-v',str(folder/'nginx.conf')+':/etc/nginx/nginx.conf:ro','nginx:1.28-alpine')
            base=f'http://127.0.0.1:{port}'
            with httpx.Client(base_url=base,headers={'Origin':base},timeout=3) as client:
                for _ in range(200):
                    try:
                        if client.get('/api/v1/features').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise AssertionError('隔离服务未启动，查看exit-gzip-docker.log')
                login=client.post('/api/auth/login',json={'username':'gzipqa','password':'exit-gzip-test'})
                assert login.status_code==200,(login.status_code,login.text)
                with (OUTPUT/'exit-gzip-chrome.log').open('w',encoding='utf-8') as chrome_log,browser(str(folder/'chrome'),chrome_log) as (cmd,ev):
                    def wait(expression):
                        """等待真实产品状态，失败只输出退出反馈。"""
                        for _ in range(200):
                            if ev(f'(()=>{{try{{return Boolean({expression})}}catch{{return false}}}})()'):return
                            time.sleep(.04)
                        raise AssertionError((expression,ev("document.querySelector('[data-exit-status]')?.textContent")))

                    def click(selector):
                        """通过实际UI确认退出，不调用内部模型。"""
                        encoded=json.dumps(selector)
                        wait(f'document.querySelector({encoded})?.getClientRects().length&&!document.querySelector({encoded}).disabled')
                        ev(f'document.querySelector({encoded}).click()')

                    cmd('Network.enable')
                    cmd('Network.setCookie',{'name':'jobless_session','value':client.cookies.get('jobless_session'),'url':base+'/','httpOnly':True})
                    cmd('Page.navigate',{'url':base+'/journey.html?game_id=sudoku'})
                    wait("document.querySelector('#journey-status')?.textContent==='账号资料已同步。'")
                    time.sleep(.25)
                    click('[data-level="sudoku-v2-easy-02"]');click('#sudoku-enter-confirm')
                    wait("document.querySelectorAll('#sudoku-board [data-index]').length===81&&!document.querySelector('#sudoku-back').disabled")
                    progress=client.get('/api/v1/me/level-progress?game_id=sudoku&limit=50').json()['items']
                    path=next(item['current_attempt'] for item in progress if item['level_id']=='sudoku-v2-easy-02')
                    latest=client.get(path)
                    assert latest.headers.get('content-encoding')=='gzip'
                    assert latest.headers['etag']==f'W/"{latest.json()["revision"]}"'
                    weak=client.patch(path,json={'status':'abandoned'},headers={'If-Match':latest.headers['etag']})
                    assert weak.status_code==412,'后端必须继续拒绝弱If-Match'
                    click('#sudoku-back');click('[data-exit-confirm]')
                    if args.expect_failure:
                        wait("document.querySelector('[data-exit-status]').textContent.includes('退出失败')")
                        print(json.dumps({'reproduced':True,'GET_ETag':latest.headers['etag'],'Content-Encoding':'gzip','PATCH_status':412},ensure_ascii=False))
                    else:
                        wait("!document.querySelector('#sudoku-selector').hidden&&!document.querySelector('[data-exit-confirmation]').open")
                        result=client.get(path)
                        assert result.json()['status']=='abandoned'
                        assert client.get('/api/v1/me/energy').json()['current']==4
                        assert ev("!localStorage.getItem('jobless-journey-v1:sudoku:1').includes("+json.dumps(path.rsplit('/',1)[-1])+")")
                        print(json.dumps({'checks_passed':5,'gzip_response':True,'weak_IfMatch_rejected':True,'exit_status':'abandoned','energy_preserved':True,'draft_removed':True},ensure_ascii=False))
        finally:
            docker('logs','--tail','40',name+'-api',check=False)
            docker('rm','-f',name+'-web',name+'-api',check=False)
            docker('network','rm',name,check=False)


if __name__=='__main__':
    main()
