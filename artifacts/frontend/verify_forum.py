"""作用：独立 Chrome + 临时 SQLite + 两个真实账号验收论坛与消息；不连接正式库。

验证 UI 发帖/回复/点赞、失败保留、消息已读/定位、移动布局和游戏续玩。
完整输出及截图存入 artifacts/frontend，不替代真实 MySQL/Flyway 或服务器容量验收。
"""

import base64
import json
from pathlib import Path
import socket
import tempfile
import threading
import time

import verify_ranking as qa
from verify_progress import browser
from backend.app.services import auth_service
from backend.app.common.game_catalog import LEVELS
from backend.app.models.entities.progression import GameLevel,GameLevelVersion


def main():
    """仅使用临时数据库启动本机服务，完成实际页面交互后关闭并清理。"""
    checks = []
    with tempfile.TemporaryDirectory(prefix='forum-qa-') as temporary:
        engine = qa.create_engine('sqlite:///'+(Path(temporary)/'qa.sqlite').as_posix(), connect_args={'check_same_thread':False})
        qa.Base.metadata.create_all(engine)
        sessions = qa.sessionmaker(engine, expire_on_commit=False)
        # 当前扫雷使用正式关卡；夹具发布到临时库，禁止回退已下线的旧首页。
        with sessions() as db:
            for item in LEVELS.values():
                db.add(GameLevel(level_id=item['level_id'],game_id=item['game_id'],order_index=item['order']))
                db.add(GameLevelVersion(level_id=item['level_id'],level_version=1,definition=item))
            db.commit()

        def dependency():
            """请求使用独立数据库会话，确认刷新后的真实持久化。"""
            with sessions() as db:
                yield db
        qa.api.app.dependency_overrides[qa.get_db] = dependency
        config = qa.get_settings()
        previous = (config.cookie_secure,config.forum_post_interval_seconds,config.forum_comment_interval_seconds)
        config.progression_enabled=True;config.pk_rooms_enabled=False;config.matchmaking_enabled=False
        previous_limiter=auth_service.rate_limiter
        # 多次切换隔离账号需要更高的测试额度，仅修改本进程并在 finally 恢复。
        auth_service.rate_limiter=auth_service.LoginRateLimiter(50,60)
        config.cookie_secure=False
        config.forum_post_interval_seconds=config.forum_comment_interval_seconds=0
        listener=socket.socket();listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]
        server=qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app,log_level='error'))
        worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline:
            time.sleep(.05)
        assert server.started
        base=f'http://127.0.0.1:{port}/'
        try:
            with (qa.OUTPUT/'forum-browser-chrome.log').open('w',encoding='utf-8') as log:
                with browser(str(Path(temporary)/'chrome'),log) as (command,_):
                    def evaluate(expression):
                        """执行页面脚本并等待真实网络请求，保留浏览器 Cookie。"""
                        result=command('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                        if 'exceptionDetails' in result:
                            raise AssertionError(result['exceptionDetails'])
                        return result.get('result',{}).get('value')

                    def wait(expression):
                        """有限等待界面条件，失败只返回条件和状态摘要。"""
                        deadline=time.monotonic()+12
                        while time.monotonic()<deadline:
                            if evaluate(expression):return
                            time.sleep(.05)
                        shot('forum-failure.png')
                        raise AssertionError((expression,evaluate("({status:[...document.querySelectorAll('[role=status]')].map(n=>n.textContent),likes:[...document.querySelectorAll('.forum-like')].map(n=>[n.textContent,n.disabled]),user:document.querySelector('.auth-username')?.textContent})")))

                    def click(selector):
                        """发送可信鼠标事件，覆盖原生弹窗与标准按钮行为。"""
                        point=evaluate(f"(()=>{{const b=document.querySelector({json.dumps(selector)});if(!b)throw new Error('missing '+{json.dumps(selector)});b.scrollIntoView({{block:'center',behavior:'instant'}});const r=b.getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}};}})()")
                        for event in ('mousePressed','mouseReleased'):
                            command('Input.dispatchMouseEvent',{'type':event,**point,'button':'left','clickCount':1})

                    def navigate(path):
                        """跨独立页面保持真实会话。"""
                        command('Page.navigate',{'url':base+path})
                        wait("document.readyState==='complete' && !!document.querySelector('.auth-open')")

                    def login(name):
                        """使用网站已有登录弹窗创建/恢复真实账号。"""
                        click('.auth-open');wait("document.querySelector('#auth-dialog').open")
                        evaluate(f"document.querySelector('#auth-username').value={json.dumps(name)};document.querySelector('#auth-password').value='forum-secret';")
                        click('.auth-submit');wait("!document.querySelector('.auth-user').classList.contains('hidden')")

                    def shot(name):
                        """保存可供人工查看的实际截图。"""
                        result=command('Page.captureScreenshot',{'format':'png'})
                        (qa.OUTPUT/name).write_bytes(base64.b64decode(result['data']))

                    command('Network.enable')
                    command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':960,'deviceScaleFactor':1,'mobile':False})
                    command('Network.setBlockedURLs',{'urls':['*api/forum/posts']})
                    navigate('forum.html');wait("document.querySelector('#forum-status')?.textContent.includes('连接失败')")
                    command('Network.setBlockedURLs',{'urls':[]});click('#forum-retry')
                    wait("document.querySelector('#forum-status')?.textContent.includes('还没有')")
                    assert evaluate("document.querySelector('.notification-bell').classList.contains('hidden')")
                    click('#forum-compose');wait("document.querySelector('#auth-dialog').open")
                    evaluate("document.querySelector('#auth-username').value='论坛甲';document.querySelector('#auth-password').value='forum-secret';")
                    click('.auth-submit');wait("document.querySelector('#forum-compose-dialog')?.open")
                    assert evaluate("!document.querySelector('#forum-title-input') && document.activeElement.id==='forum-body-input'")
                    evaluate("document.querySelector('#forum-body-input').value='中文与换行\\n<script>window.forumXss=1</script>'; ")
                    command('Network.setBlockedURLs',{'urls':['*api/forum/posts']})
                    click('#forum-submit');wait("document.querySelector('#forum-form-status').textContent.includes('连接失败')")
                    assert evaluate("document.querySelector('#forum-body-input').value.includes('<script>')")
                    command('Network.setBlockedURLs',{'urls':[]})
                    click('#forum-submit');wait("document.querySelectorAll('.forum-post-link').length===1")
                    checks.append('游客登录续接发帖；失败保留输入并幂等重试')
                    post_id=evaluate("Number(document.querySelector('.forum-card').dataset.id)")
                    assert not evaluate('window.forumXss')
                    shot('forum-desktop.png')
                    click('.forum-post-link');wait("!!document.querySelector('#forum-post article')")
                    assert evaluate("document.querySelector('#forum-post .forum-body').textContent.includes('<script>')")
                    evaluate("document.querySelector('#comment-body').value='顶层评论';")
                    click('#comment-submit');wait("document.querySelectorAll('#forum-comments > article').length===1")
                    root_id=evaluate("Number(document.querySelector('#forum-comments > article').dataset.id)")
                    click('.auth-logout');wait("document.querySelector('.auth-user').classList.contains('hidden')")
                    login('论坛乙')
                    wait("!!document.querySelector('#forum-comments > article .forum-reply')")
                    click('#forum-comments > article .forum-reply')
                    evaluate("document.querySelector('#comment-body').value='回复甲的评论';")
                    click('#comment-submit');wait("!!document.querySelector('.forum-replies article')")
                    wait("!document.querySelector('#comment-submit').disabled")
                    reply_id=evaluate("Number(document.querySelector('.forum-replies article').dataset.id)")
                    assert evaluate(f"(()=>{{const c=document.querySelector('#comment-{reply_id}'),n=c.querySelector('.forum-author .forum-identity');return !!n&&n.getAttribute('aria-label')==='论坛乙 回复 论坛甲'&&!c.querySelector(':scope > .forum-reply-label');}})()"), '回复双方应合并到作者行'
                    click('#forum-post .forum-like');wait("document.querySelector('#forum-post .forum-like').getAttribute('aria-pressed')==='true'")
                    click('#forum-comments > article .forum-like');wait("document.querySelector('#forum-comments > article .forum-like').getAttribute('aria-pressed')==='true'")
                    checks.append('两个账号发布根评论及回复，帖子和评论点赞服务端确认')
                    click('.auth-logout');wait("document.querySelector('.auth-user').classList.contains('hidden')")
                    login('论坛甲')
                    wait("document.querySelector('.notification-bell').getAttribute('aria-label').includes('3 条未读')")
                    click('.notification-bell');wait("document.querySelectorAll('.notification-item').length===3")
                    assert evaluate("document.querySelectorAll('.notification-item.is-unread').length") == 3
                    click('.notification-close')
                    assert evaluate("document.activeElement.classList.contains('notification-bell')")
                    click('.notification-bell');wait("!document.querySelector('.notification-retry').disabled")
                    click(f'.notification-item[href*="comment={reply_id}"]')
                    wait(f"!!document.querySelector('#comment-{reply_id}.forum-target')")
                    assert evaluate("document.querySelector('.notification-bell').getAttribute('aria-label').includes('2 条未读')")
                    checks.append('仅查看不已读；点击回复提醒持久已读并直接定位上下文')
                    click(f'#comment-{reply_id} .forum-like')
                    wait(f"document.querySelector('#comment-{reply_id} .forum-like').getAttribute('aria-pressed')==='true'")
                    click(f'#comment-{reply_id} .forum-reply')
                    evaluate("document.querySelector('#comment-body').value='回复已有回复';document.querySelector('#comment-submit').focus();")
                    for event in ('keyDown','keyUp'):
                        command('Input.dispatchKeyEvent',{'type':event,'key':'Enter','code':'Enter','windowsVirtualKeyCode':13,**({'text':'\r'} if event=='keyDown' else {})})
                    wait("document.querySelector('.forum-target .forum-body')?.textContent==='回复已有回复'")
                    checks.append('键盘发布对已有回复的回复，保持两层并明确直接回复对象')
                    click('.notification-bell');wait("!document.querySelector('.notification-read-all').disabled")
                    click('.notification-read-all');wait("document.querySelector('.notification-bell').getAttribute('aria-label').includes('0 条未读')")
                    click('.notification-close')
                    command('Page.reload');wait("document.querySelector('.notification-bell')?.getAttribute('aria-label')?.includes('0 条未读')")
                    checks.append('回复也可点赞；全部已读与刷新保持')
                    for width in (375,320):
                        command('Emulation.setDeviceMetricsOverride',{'width':width,'height':844,'deviceScaleFactor':1,'mobile':False})
                        # 帖子先于评论/通知定位返回，布局断言需等待被测回复也已渲染。
                        wait("!!document.querySelector('#forum-post article') && !!document.querySelector('.forum-replies .forum-identity')")
                        assert evaluate('document.documentElement.scrollWidth<=innerWidth'), f'{width}px 页面溢出'
                        assert evaluate("(()=>{const g=document.querySelector('.forum-replies .forum-identity'),n=[...g.children].map(x=>x.getBoundingClientRect());return n.length===3&&n.every(r=>Math.abs(r.top-n[0].top)<1);})()"), '手机上回复双方也应保持同一行'
                        if width==320:
                            assert evaluate("(()=>{const g=document.querySelector('.forum-replies .forum-identity'),a=g.firstElementChild,b=g.lastElementChild,old=[a.textContent,b.textContent];a.textContent='甲乙丙丁戊己庚辛';b.textContent='壬癸子丑寅卯辰巳';const r=[...g.children].map(x=>x.getBoundingClientRect());const ok=r.every(x=>Math.abs(x.top-r[0].top)<1)&&document.documentElement.scrollWidth<=innerWidth&&(a.scrollWidth>a.clientWidth||b.scrollWidth>b.clientWidth);[a.textContent,b.textContent]=old;return ok;})()"), '长姓名应省略而不是折行或横向溢出'
                        shot(f'forum-post-mobile-{width}.png')
                        click('.notification-bell');wait("document.querySelector('#notification-dialog').open")
                        assert evaluate("(()=>{const d=document.querySelector('#notification-dialog');return d.scrollWidth<=d.clientWidth&&d.getBoundingClientRect().right<=innerWidth;})()")
                        shot(f'forum-messages-mobile-{width}.png');click('.notification-close')
                    checks.append('375px/320px 详情和消息无横向溢出')
                    checks.append('回复双方姓名同排显示，320px长姓名省略且不横向溢出')
                    navigate('forum-post.html?id=999999');wait("document.querySelector('#forum-status')?.textContent.includes('不存在')")
                    navigate('forum-post.html?id=invalid');wait("document.querySelector('#forum-status')?.textContent.includes('无效')")
                    checks.append('不存在和无效帖子有清晰返回入口')
                    navigate('journey.html?game_id=mine');click('#mine-start')
                    wait("document.querySelector('#mine-rules-dialog').open")
                    click('#mine-rules-confirm')
                    wait("document.querySelectorAll('.mine-square').length===100 && !document.querySelector('#mine-restart').disabled")
                    before=evaluate("Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('jobless-journey-v1:')).map(k=>[k,localStorage.getItem(k)]))")
                    assert before
                    click('.notification-bell');wait("document.querySelector('#notification-dialog').open")
                    click('.notification-close')
                    assert evaluate("Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('jobless-journey-v1:')).map(k=>[k,localStorage.getItem(k)]))") == before
                    board_before=evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('jobless-journey-v1:')))).entries")
                    click('#mine-back');navigate('forum.html');navigate('journey.html?game_id=mine')
                    wait("document.querySelectorAll('.mine-square').length===100 && !document.querySelector('#mine-restart').disabled")
                    assert evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('jobless-journey-v1:')))).entries") == board_before
                    checks.append('游戏中可开消息面板且保留真实棋局')
                    navigate('forum.html');wait("document.querySelectorAll('.forum-post-link').length===1")
                    command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':960,'deviceScaleFactor':1,'mobile':False})
                    shot('forum-final-desktop.png')
                    # 通过真实 HTTP 建后续页上下文，验证通知定位不用先翻20条评论。
                    late=evaluate(f"(async()=>{{let root;for(let i=0;i<22;i++){{root=await (await fetch('/api/forum/posts/{post_id}/comments',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{request_id:crypto.randomUUID(),body:'后续评论'+i}})}})).json();}}return root;}})()")
                    navigate(f"forum-post.html?id={post_id}&comment={late['id']}")
                    wait(f"!!document.querySelector('#forum-context #comment-{late['id']}.forum-target')")
                    assert evaluate("document.querySelectorAll('#forum-comments > article').length") == 20
                    click('#comments-more');wait("document.querySelectorAll('#forum-comments > article').length===23")
                    checks.append('后续分页评论直接定位，加载更多保持完整顺序')
                    for width in (375,320):
                        navigate('forum.html');wait("document.querySelectorAll('.forum-post-link').length===1")
                        command('Emulation.setDeviceMetricsOverride',{'width':width,'height':844,'deviceScaleFactor':1,'mobile':False})
                        assert evaluate('document.documentElement.scrollWidth<=innerWidth')
                        click('#forum-compose');wait("document.querySelector('#forum-compose-dialog').open")
                        assert evaluate("(()=>{const d=document.querySelector('#forum-compose-dialog');return d.scrollWidth<=d.clientWidth&&d.getBoundingClientRect().right<=innerWidth;})()")
                        shot(f'forum-compose-mobile-{width}.png');click('#forum-compose-close')
                    checks.append('375px/320px 列表及正文发布弹窗无横向溢出')
                with browser(str(Path(temporary)/'second-browser'),log) as (command,_):
                    command('Network.enable')
                    navigate('forum.html');login('论坛甲')
                    wait("document.querySelector('.notification-bell').getAttribute('aria-label').includes('0 条未读')")
                    click('.notification-bell');wait("document.querySelectorAll('.notification-item').length===3")
                    assert evaluate("document.querySelectorAll('.notification-item.is-unread').length") == 0
                    click('.notification-close');click('.auth-logout');wait("document.querySelector('.auth-user').classList.contains('hidden')")
                    login('论坛乙');wait("document.querySelector('.notification-bell').getAttribute('aria-label').includes('2 条未读')")
                    checks.append('独立浏览器已读持久化，换号后仅显示自己的消息')
                    # 新增列表交互验收：独立帖子不改变上面已确认的历史通知统计。
                    inline=evaluate("(async()=>await(await fetch('/api/forum/posts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID(),body:'列表直接回复验收\\n短一些的卡片间距。'})})).json())()")
                    inline_id=inline['id'];selector=f'.forum-thread[data-post-id="{inline_id}"]'
                    command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':960,'deviceScaleFactor':1,'mobile':False})
                    navigate('forum.html');wait(f"!!document.querySelector('{selector} .forum-count')")
                    click(selector+' .forum-count');wait(f"document.querySelector('{selector} .forum-inline-status').textContent.includes('还没有')")
                    assert evaluate(f"document.querySelector('{selector} .forum-count').getAttribute('aria-expanded')==='true'")
                    wait(f"getComputedStyle(document.querySelector('{selector} .forum-inline-discussion')).opacity==='1'")
                    assert evaluate(f"(()=>{{const t=document.querySelector('{selector}'),p=t.querySelector(':scope > .forum-card').getBoundingClientRect(),c=t.querySelector('.forum-inline-discussion').getBoundingClientRect();return Math.abs(p.bottom-c.top)<1;}})()"), '同帖正文和评论之间不应露出背景间隔'
                    click(selector+' > .forum-card .forum-reply');wait(f"!document.querySelector('{selector} .forum-inline-form').hidden")
                    assert evaluate(f"document.activeElement===document.querySelector('{selector} textarea')")
                    assert evaluate(f"(()=>{{const f=document.querySelector('{selector} .forum-inline-form'),b=f.querySelector('textarea'),s=f.querySelector('.forum-inline-submit'),r=b.getBoundingClientRect(),q=s.getBoundingClientRect();return b.rows===2&&!f.querySelector('output,.forum-form-footer,.forum-inline-cancel,.forum-compose-target')&&!!s.querySelector('svg')&&s.getAttribute('aria-label')==='发送回复'&&r.height<=2*parseFloat(getComputedStyle(b).lineHeight)+20&&q.left>=r.left&&q.right<=r.right&&q.top>=r.top&&q.bottom<=r.bottom;}})()"), '回复框应只保留两行输入和框内纸飞机'
                    evaluate(f"document.querySelector('{selector} textarea').value='不进入详情直接评论';")
                    command('Network.setBlockedURLs',{'urls':[f'*api/forum/posts/{inline_id}/comments']})
                    click(selector+' .forum-inline-submit');wait(f"document.querySelector('{selector} .forum-inline-form-status').textContent.includes('连接失败')")
                    assert evaluate(f"document.querySelector('{selector} textarea').value==='不进入详情直接评论'")
                    evaluate(f"window.inlineDraft=document.querySelector('{selector} textarea');document.dispatchEvent(new CustomEvent('user-profile-updated'))")
                    wait("document.querySelector('#forum-status').textContent===''")
                    assert evaluate(f"window.inlineDraft===document.querySelector('{selector} textarea') && window.inlineDraft.value==='不进入详情直接评论'")
                    other='.forum-thread:not([data-post-id="'+str(inline_id)+'"])'
                    click(other+' > .forum-card .forum-reply');wait(f"!document.querySelector('{other} .forum-inline-form').hidden")
                    assert evaluate("[...document.querySelectorAll('.forum-inline-form')].filter(f=>!f.hidden&&f.getClientRects().length).length===1"), '列表只允许一个可见回复框'
                    click(selector+' > .forum-card .forum-reply');wait(f"!document.querySelector('{selector} .forum-inline-form').hidden")
                    assert evaluate(f"document.querySelector('{selector} textarea').value==='不进入详情直接评论'")
                    assert evaluate("[...document.querySelectorAll('.forum-inline-form')].filter(f=>!f.hidden&&f.getClientRects().length).length===1")
                    command('Network.setBlockedURLs',{'urls':[]});click(selector+' .forum-inline-submit')
                    wait(f"document.querySelector('{selector} .forum-count').textContent==='1 条评论' && !document.querySelector('{selector} .forum-inline-submit').disabled")
                    assert evaluate("location.pathname.endsWith('/forum.html')")
                    checks.append('列表左侧展开评论、右侧图标直接回复及失败重试')
                    click('.auth-logout');wait("document.querySelector('.auth-user').classList.contains('hidden')");login('论坛甲')
                    wait(f"!!document.querySelector('{selector} .forum-count')");click(selector+' .forum-count')
                    wait(f"document.querySelector('{selector} .forum-inline-comments .forum-body')?.textContent==='不进入详情直接评论'")
                    click(selector+' .forum-inline-comments .forum-reply')
                    evaluate(f"document.querySelector('{selector} textarea').value='在列表回复他人评论';")
                    click(selector+' .forum-inline-submit');wait(f"document.querySelector('{selector} .forum-count').textContent==='2 条评论' && !document.querySelector('{selector} .forum-inline-submit').disabled")
                    wait(f"[...document.querySelectorAll('{selector} .forum-replies .forum-body')].some(n=>n.textContent==='在列表回复他人评论')")
                    click(selector+' > .forum-card .forum-like');wait(f"document.querySelector('{selector} > .forum-card .forum-like').getAttribute('aria-pressed')==='true'")
                    assert evaluate(f"getComputedStyle(document.querySelector('{selector} > .forum-card .forum-like')).color==='rgb(255, 107, 107)'")
                    evaluate("scrollTo({top:0,behavior:'instant'})");shot('forum-inline-liked-desktop.png')
                    click(selector+' > .forum-card .forum-like');wait(f"document.querySelector('{selector} > .forum-card .forum-like').getAttribute('aria-pressed')==='false'")
                    checks.append('换号可展开他人评论并回复，拇指点赞变红且可取消')
                    root=evaluate(f"Number(document.querySelector('{selector} .forum-inline-comments > article').dataset.id)")
                    evaluate(f"(async()=>{{for(let i=0;i<34;i++){{const response=await fetch('/api/forum/posts/{inline_id}/comments',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{request_id:crypto.randomUUID(),body:'分页验收'+i,reply_to_comment_id:i<22?null:{root}}})}});if(!response.ok)throw new Error('分页数据写入失败');}}}})()")
                    navigate('forum.html');wait(f"!!document.querySelector('{selector} .forum-count')");click(selector+' .forum-count')
                    wait(f"document.querySelectorAll('{selector} .forum-inline-comments > article').length===20")
                    click(selector+' .forum-inline-more');wait(f"document.querySelectorAll('{selector} .forum-inline-comments > article').length===23")
                    root_selector=selector+f' #comment-{root}'
                    click(root_selector+' .forum-expand');wait(f"document.querySelectorAll('{root_selector} .forum-replies > article').length===10")
                    click(root_selector+' .forum-replies > .forum-load');wait(f"document.querySelectorAll('{root_selector} .forum-replies > article').length===13")
                    reads=evaluate(f"performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/forum/posts/{inline_id}/comments')).length")
                    click(selector+' > .forum-card .forum-count');assert evaluate(f"document.querySelector('{selector} .forum-inline-discussion').hidden")
                    click(selector+' > .forum-card .forum-count');assert evaluate(f"performance.getEntriesByType('resource').filter(r=>r.name.includes('/api/forum/posts/{inline_id}/comments')).length")==reads
                    checks.append('列表评论20条及回复10条有限分页，反复展开不重复请求')
                    assert evaluate(f"(()=>{{const t=document.querySelector('{selector}'),p=t.querySelector(':scope > .forum-card'),c=t.querySelector('.forum-inline-comments > article'),d=t.querySelector('.forum-replies > article'),s=t.querySelector('.forum-inline-scroll');const font=(e,sel)=>parseFloat(getComputedStyle(e.querySelector(sel)).fontSize);return p.querySelector('.avatar-image').width-c.querySelector('.avatar-image').width===4&&font(p,'.forum-author')-font(c,'.forum-author')===3&&font(p,'.forum-excerpt')-font(c,'.forum-body')===3&&s&&s.scrollHeight>s.clientHeight&&t.getBoundingClientRect().height<=722&&parseFloat(getComputedStyle(d).borderTopWidth)===1&&parseFloat(getComputedStyle(d).borderLeftWidth)===0&&getComputedStyle(d).backgroundColor==='rgba(0, 0, 0, 0)'&&getComputedStyle(d).borderRadius==='0px';}})()"), '主帖应较大、评论区有高度边界且深层回复仅用线分隔'
                    checks.append('主帖头像大4px/字体大3px，单帖限高且深层回复使用细分隔线')
                    for width in (1280,375,320):
                        command('Emulation.setDeviceMetricsOverride',{'width':width,'height':960,'deviceScaleFactor':1,'mobile':False})
                        evaluate(f"document.querySelector('{selector}').scrollIntoView({{block:'start'}})")
                        wait(f"getComputedStyle(document.querySelector('{selector} .forum-inline-discussion')).opacity==='1'")
                        assert evaluate('document.documentElement.scrollWidth<=innerWidth')
                        assert evaluate(f"(()=>{{const t=document.querySelector('{selector}'),s=t.querySelector('.forum-inline-scroll');s.scrollTop=s.scrollHeight;return t.getBoundingClientRect().height<=722&&s.scrollTop>0&&s.getAttribute('tabindex')==='0';}})()"), '桌面和手机均应在评论区内滚动而非无限伸长'
                        assert evaluate(f"(()=>{{const c=document.querySelector('{selector} > .forum-card'),n=c.querySelector('.forum-count').getBoundingClientRect(),l=c.querySelector('.forum-like').getBoundingClientRect(),r=c.querySelector('.forum-reply').getBoundingClientRect();return n.left<l.left&&l.left<r.left&&l.height>=44&&r.width>=44&&parseFloat(getComputedStyle(c).paddingLeft)<=16;}})()")
                        shot(f'forum-inline-{width}.png')
                    checks.append('紧凑卡片及左评论右图标布局在桌面/375px/320px可用')
                    click('.auth-logout');wait("document.querySelector('.auth-user').classList.contains('hidden')")
                    wait(f"!!document.querySelector('{selector} .forum-count')");click(selector+' > .forum-card .forum-reply')
                    wait("document.querySelector('#auth-dialog').open")
                    evaluate("document.querySelector('#auth-username').value='论坛乙';document.querySelector('#auth-password').value='forum-secret';")
                    # 换号会先重建列表；等待新表单出现后再检查可见性和焦点。
                    click('.auth-submit');wait(f"document.querySelector('{selector} .forum-inline-form')?.hidden === false && document.activeElement===document.querySelector('{selector} textarea')")
                    checks.append('游客点击列表回复，登录后续接新卡片的正文输入')
                    for width in (1280,375,320):
                        command('Emulation.setDeviceMetricsOverride',{'width':width,'height':844,'deviceScaleFactor':1,'mobile':False})
                        evaluate(f"document.querySelector('{selector} .forum-inline-form').scrollIntoView({{block:'center',behavior:'instant'}})")
                        assert evaluate('document.documentElement.scrollWidth<=innerWidth')
                        assert evaluate(f"(()=>{{const t=document.querySelector('{selector} textarea'),s=document.querySelector('{selector} .forum-inline-submit'),r=t.getBoundingClientRect(),q=s.getBoundingClientRect();return q.right<=r.right&&q.left>=r.left&&q.bottom<=r.bottom&&q.top>=r.top&&r.height<=2*parseFloat(getComputedStyle(t).lineHeight)+20;}})()")
                        shot(f'forum-compact-reply-{width}.png')
                    checks.append('同帖无间隔、单一回复框保留重试内容、两行输入及框内纸飞机')
            print(f'论坛浏览器验收：{len(checks)} 项通过，0 失败。')
        finally:
            config.cookie_secure,config.forum_post_interval_seconds,config.forum_comment_interval_seconds=previous
            auth_service.rate_limiter=previous_limiter
            qa.api.app.dependency_overrides.clear();server.should_exit=True;worker.join(timeout=10);listener.close();engine.dispose()


if __name__=='__main__':
    main()
