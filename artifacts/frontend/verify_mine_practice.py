"""作用：独立 Chrome/临时 SQLite 验证三种尺寸九个扫雷关卡、身份隔离及移动布局。

所有账号与存档仅用于临时浏览器和数据库；记录挑战写请求以确认练习不污染正式榜单。
只输出最终统计或失败摘要，浏览器日志与截图存入 artifacts/frontend。
"""
import base64
import json
from pathlib import Path
import socket
import tempfile
import threading
import time

import verify_ranking as qa
from verify_progress import browser, wait_for


def main():
    """真实页面操作覆盖三个练习档位、刷新/换号恢复与正式存档保护。"""
    checks=[]
    with tempfile.TemporaryDirectory(prefix='mine-mvp-qa-') as temporary:
        engine=qa.create_engine('sqlite:///'+(Path(temporary)/'qa.sqlite').as_posix(),connect_args={'check_same_thread':False})
        qa.Base.metadata.create_all(engine)
        sessions=qa.sessionmaker(engine,expire_on_commit=False)

        def dependency():
            """测试会话使用临时数据库，绝不连接项目 MySQL。"""
            with sessions() as db:
                yield db

        writes=[]

        async def observe(request,call_next):
            """记录写接口路径而不记录凭据、请求体或会话内容。"""
            if request.method in ('POST','PUT','DELETE'):
                writes.append(request.url.path)
            return await call_next(request)

        # 在启动前安装观测中间件；此脚本独占一个隔离 Python 进程。
        qa.api.app.middleware('http')(observe)
        qa.api.app.dependency_overrides[qa.get_db]=dependency
        config=qa.get_settings();previous=config.cookie_secure;config.cookie_secure=False
        listener=socket.socket();listener.bind(('127.0.0.1',0))
        base=f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        try:
            deadline=time.monotonic()+10
            while not server.started and time.monotonic()<deadline:time.sleep(.05)
            assert server.started
            with (qa.OUTPUT/'mine-mvp-browser-chrome.log').open('w',encoding='utf-8') as log:
                with browser(str(Path(temporary)/'chrome'),log) as (command,evaluate):
                    def wait(expression):
                        """异步页面条件使用有界等待，断言不依赖固定加载延迟。"""
                        wait_for(evaluate,expression)

                    def click(selector):
                        """点击真实页面按钮，保留浏览器 disabled/原生 dialog 语义。"""
                        evaluate(f'document.querySelector({json.dumps(selector)}).click()')

                    def entry(level,namespace='guest'):
                        """读取测试浏览器自己的快照，仅用于比对和稳定触发真实棋盘操作。"""
                        return evaluate(f"JSON.parse(localStorage.getItem('jobless-mine-practice-v1:{namespace}')).entries[{json.dumps(level)}]")

                    def select(level):
                        """通过关卡卡片切换，确认展示状态与关卡身份一致。"""
                        size=level.split('-')[1] if level.split('-')[1].isdigit() else '10'
                        click(f'button.practice-size[data-size="{size}"]')
                        assert evaluate(f'!document.querySelector(\'[data-level="{level}"]\').hidden')
                        click(f'[data-level="{level}"]')
                        wait(f'document.querySelector(\'[data-level="{level}"]\').getAttribute("aria-pressed")==="true"')

                    def shot(name):
                        """保存当前实际渲染画面供视觉检查。"""
                        data=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True})['data']
                        (qa.OUTPUT/name).write_bytes(base64.b64decode(data))

                    def login(name):
                        """真实登录用于验证游客/不同账号的练习快照分离。"""
                        click('.auth-open');wait("document.getElementById('auth-dialog').open")
                        evaluate(f"document.getElementById('auth-username').value={json.dumps(name)};document.getElementById('auth-password').value='mine-mvp-secret';document.querySelector('.auth-submit').click()")
                        wait(f'document.querySelector(".auth-username")?.textContent==={json.dumps(name)}')

                    command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':1000,'deviceScaleFactor':1,'mobile':False})
                    command('Page.navigate',{'url':base+'mine-practice.html'})
                    wait("document.querySelectorAll('[data-level]').length===9")
                    assert evaluate("document.querySelectorAll('[data-level]:not([hidden])').length===3 && document.querySelectorAll('button.practice-size').length===3")
                    assert evaluate("!document.getElementById('practice-empty').hidden && document.getElementById('practice-owner').textContent.includes('游客')")
                    evaluate("localStorage.setItem('jobless-progress-v1:1','original-official-progress')")
                    checks.append('游客无需登录可选九关，按尺寸分组三个难度，初始引导可见')
                    shot('mine-mvp-desktop-selection.png')
                    for level,count in [('mine-easy',10),('mine-normal',15),('mine-hard',20)]:
                        select(level)
                        assert entry(level)['game']['level']['mineCount']==count
                        assert sum(cell['mine'] for cell in entry(level)['game']['cells'])==count
                        assert evaluate("document.querySelectorAll('#practice-board button').length") == 100
                        assert str(count) in evaluate("document.getElementById('practice-rules-description').textContent")
                        click('#practice-start')
                    checks.append('三档准确布置10/15/20颗雷，规则和棋盘复用同一控制器')

                    select('mine-easy')
                    safe=next(i for i,cell in enumerate(entry('mine-easy')['game']['cells']) if not cell['mine'])
                    click(f'#practice-board [data-index="{safe}"]');click('#practice-flag')
                    easy_before=entry('mine-easy')['game']
                    select('mine-normal')
                    normal_start=entry('mine-normal')['game']['startedAt']
                    select('mine-easy')
                    assert entry('mine-easy')['game']==easy_before
                    assert evaluate(f'document.querySelector(\'#practice-board [data-index="{safe}"]\').classList.contains("cell-flagged")')
                    checks.append('切换关卡保留原棋盘、选中格与标记')
                    command('Page.reload');wait("document.querySelectorAll('#practice-board button').length===100")
                    assert evaluate("document.querySelector('[data-level=\"mine-easy\"]').getAttribute('aria-pressed')==='true'")
                    assert entry('mine-easy')['game']==easy_before
                    checks.append('刷新恢复上次所选关卡、原始棋盘和标记')
                    wait("document.getElementById('practice-timer').textContent!=='00:00'")
                    before=evaluate("document.getElementById('practice-timer').textContent")
                    click('#practice-rules')
                    wait(f'document.getElementById("practice-timer").textContent>{json.dumps(before)}')
                    command('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','windowsVirtualKeyCode':27})
                    command('Input.dispatchKeyEvent',{'type':'keyUp','key':'Escape','windowsVirtualKeyCode':27})
                    assert evaluate("!document.getElementById('practice-rules-dialog').open")
                    checks.append('确认后计时，重看规则继续累计，已开始后Esc返回棋盘')
                    select('mine-hard');click('#practice-restart')
                    assert evaluate("document.getElementById('practice-timer').textContent==='00:00' && document.getElementById('practice-rules-dialog').open")
                    command('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','windowsVirtualKeyCode':27})
                    command('Input.dispatchKeyEvent',{'type':'keyUp','key':'Escape','windowsVirtualKeyCode':27})
                    assert evaluate("document.getElementById('practice-rules-dialog').open"),entry('mine-hard')['game']['startedAt']
                    click('#practice-start')
                    assert entry('mine-normal')['game']['startedAt']==normal_start
                    assert entry('mine-easy')['game']==easy_before
                    checks.append('首次规则Esc不能提前开始，重开只清空本关')

                    # 稳定地点击本局全部安全格，胜负判定仍使用生产规则和真实按钮。
                    select('mine-normal')
                    safe_cells=[i for i,cell in enumerate(entry('mine-normal')['game']['cells']) if not cell['mine']]
                    for index in safe_cells:
                        click(f'#practice-board [data-index="{index}"]');click('#practice-reveal')
                    wait("!document.getElementById('practice-outcome').hidden")
                    assert entry('mine-normal')['game']['status']=='won'
                    assert '85' in evaluate("document.getElementById('practice-outcome-description').textContent")
                    frozen=evaluate("document.getElementById('practice-timer').textContent")
                    time.sleep(1.2)
                    assert evaluate("document.getElementById('practice-timer').textContent")==frozen
                    checks.append('15雷关排开85个安全格通关，显示本地结果且时间冻结')
                    command('Page.reload');wait("!document.getElementById('practice-outcome').hidden")
                    assert evaluate("document.getElementById('practice-timer').textContent")==frozen
                    checks.append('通关终盘与冻结用时刷新后仍保留')

                    select('mine-hard')
                    mine_index=next(i for i,cell in enumerate(entry('mine-hard')['game']['cells']) if cell['mine'])
                    click(f'#practice-board [data-index="{mine_index}"]');click('#practice-reveal')
                    assert evaluate("document.getElementById('practice-rules').disabled")
                    select('mine-easy');select('mine-hard')
                    assert evaluate("document.querySelectorAll('#practice-board .cell-mine').length")==20
                    assert entry('mine-hard')['game']['status']=='lost'
                    assert '20 颗地雷' in evaluate("document.getElementById('practice-outcome-description').textContent")
                    checks.append('20雷失败动画可切关取消，返回恢复完整终盘且提示雷数正确')
                    select('mine-normal')

                    for width in (375,320):
                        command('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':True})
                        evaluate('window.scrollTo(0,0)')
                        assert evaluate(f'document.documentElement.scrollWidth<={width}')
                        assert evaluate("[...document.querySelectorAll('[data-level]:not([hidden])')].every(n=>{const r=n.getBoundingClientRect();return r.width>=44&&r.height>=44&&r.right<=innerWidth})")
                        shot(f'mine-mvp-mobile-{width}-selection.png')
                        evaluate("document.getElementById('practice-game').scrollIntoView({block:'start',behavior:'instant'})")
                        viewport=evaluate("(()=>{const v=document.getElementById('practice-viewport');v.scrollLeft=v.scrollWidth;return {scrollLeft:v.scrollLeft,scrollWidth:v.scrollWidth,clientWidth:v.clientWidth,right:v.getBoundingClientRect().right,width:innerWidth}})()")
                        assert viewport['scrollLeft']>0 and viewport['right']<=viewport['width'],viewport
                        shot(f'mine-mvp-mobile-{width}-board.png')
                        click('#practice-change')
                        assert evaluate("document.activeElement.dataset.level==='mine-normal'")
                    checks.append('375/320px选关和控件无页面溢出，棋盘可在容器内滑动')
                    command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':1000,'deviceScaleFactor':1,'mobile':False})
                    evaluate("document.getElementById('practice-game').scrollIntoView({block:'start',behavior:'instant'})")
                    shot('mine-mvp-desktop-board.png')

                    # 新棋盘沿用真实规则/按钮；逐关核对配置、网格行列与右下角读屏坐标。
                    for size,counts in [(15,[23,34,45]),(20,[40,60,80])]:
                        for difficulty,count in zip(['easy','normal','hard'],counts):
                            level=f'mine-{size}-{difficulty}'
                            select(level)
                            state=entry(level)['game']
                            assert len(state['cells'])==size*size
                            assert sum(cell['mine'] for cell in state['cells'])==count
                            assert evaluate("getComputedStyle(document.getElementById('practice-board')).gridTemplateColumns.split(' ').length")==size
                            assert evaluate("getComputedStyle(document.getElementById('practice-board')).gridTemplateRows.split(' ').length")==size
                            assert f'{size} × {size}' in evaluate("document.getElementById('practice-rules-description').textContent")
                            click('#practice-start')
                            last=size*size-1
                            click(f'#practice-board [data-index="{last}"]');click('#practice-flag')
                            assert evaluate(f'document.querySelector(\'#practice-board [data-index="{last}"]\').getAttribute("aria-label")')==f'第 {size} 行第 {size} 列，已标记'
                            assert entry(level)['game']['flaggedCount']==1
                        checks.append(f'{size}×{size}三个难度布雷正确，网格尺寸和右下角格子操作/坐标准确')
                    large_before=entry('mine-20-hard')['game']
                    command('Page.reload');wait("document.querySelectorAll('#practice-board button').length===400")
                    assert evaluate("document.querySelector('button.practice-size[data-size=\"20\"]').getAttribute('aria-pressed')==='true'")
                    assert entry('mine-20-hard')['game']==large_before
                    assert entry('mine-easy')['game']==easy_before
                    assert entry('mine-normal')['game']['status']=='won'
                    checks.append('20×20刷新恢复尺寸分组和原棋盘，10×10旧进度与通关保持')
                    for width in (1280,375,320):
                        command('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':width<600})
                        evaluate("document.getElementById('practice-game').scrollIntoView({block:'start',behavior:'instant'})")
                        assert evaluate(f'document.documentElement.scrollWidth<={width}')
                        viewport=evaluate("(()=>{const v=document.getElementById('practice-viewport');v.scrollLeft=v.scrollWidth;v.scrollTop=v.scrollHeight;const c=document.querySelector('#practice-board [data-index=\"399\"]').getBoundingClientRect(),r=v.getBoundingClientRect();return {left:v.scrollLeft,top:v.scrollTop,lastVisible:c.right<=r.right+1&&c.bottom<=r.bottom+1};})()")
                        assert viewport['left']>0 and viewport['top']>0 and viewport['lastVisible'],viewport
                        shot(f'mine-large-{width}-board.png')
                    checks.append('20×20在桌面/375/320px均不撑宽整页，可双向滑到最右下角')
                    click('#practice-restart')
                    assert entry('mine-20-hard')['game']['flaggedCount']==0
                    assert entry('mine-easy')['game']==easy_before
                    assert entry('mine-normal')['game']['status']=='won'
                    click('#practice-start');select('mine-normal')
                    checks.append('重开20×20只清空当前关，其他尺寸棋盘/成绩保留')
                    command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':1000,'deviceScaleFactor':1,'mobile':False})

                    login('练习甲')
                    wait("document.getElementById('practice-empty').hidden===false")
                    assert evaluate("!document.querySelector('[data-level=\"mine-normal\"]').textContent.includes('已通关')")
                    select('mine-easy');click('#practice-start')
                    account_id=evaluate("Object.keys(localStorage).find(k=>k.startsWith('jobless-mine-practice-v1:')&&!k.endsWith('guest')).split(':').at(-1)")
                    assert account_id
                    click('.auth-logout')
                    wait("document.getElementById('practice-owner').textContent.includes('游客')")
                    assert evaluate("document.querySelector('[data-level=\"mine-normal\"]').getAttribute('aria-pressed')==='true'")
                    assert entry('mine-normal')['game']['status']=='won'
                    login('练习乙');wait("!document.getElementById('practice-empty').hidden")
                    checks.append('登录不混入游客进度，退出恢复游客原关卡，第二账号独立')
                    assert evaluate("localStorage.getItem('jobless-progress-v1:1')")=='original-official-progress'
                    assert not any(path.startswith('/api/challenges/') for path in writes),writes
                    checks.append('正式存档原文未改写，整个练习无挑战/排行榜写请求')
            print(json.dumps({'checks_passed':len(checks),'uncaught_errors':0,'checks':checks},ensure_ascii=False))
        finally:
            config.cookie_secure=previous
            qa.api.app.dependency_overrides.pop(qa.get_db,None)
            server.should_exit=True;worker.join(timeout=10);listener.close();engine.dispose()


if __name__=='__main__':
    main()
