"""作用：两个独立Chrome与临时SQLite验收成长、三游戏正式资格、主题、房间/SSE及匹配。

不连接现有站点数据库；第二账号仅在隔离夹具内授资格以专测双人流程，产品无开发通关入口。
截图、详细日志只存artifacts；最终输出统计，不代替MySQL或目标机容量证据。
"""
import base64
from contextlib import ExitStack
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from uuid import uuid4
import verify_ranking as qa
from verify_progress import browser
from backend.app.common.game_catalog import LEVELS, QUALIFICATIONS
from backend.app.common.security import utc_now
from backend.app.models.entities.progression import GameLevel, GameLevelVersion, GameAttempt, PlayerQualification
from backend.app.services import pk_lifecycle
from backend.content_check import akari_solutions, sudoku_solutions
from backend.app.models.entities.pk import PKRoom


def main():
    """浏览器均使用真实页面按钮及API；只在测试机读取题目解以稳定覆盖结算。"""
    checks = []
    with tempfile.TemporaryDirectory(prefix='progression-browser-') as temporary:
        engine = qa.create_engine('sqlite:///' + (Path(temporary)/'qa.sqlite').as_posix(), connect_args={'check_same_thread': False, 'timeout': 10})
        qa.Base.metadata.create_all(engine)
        sessions = qa.sessionmaker(engine, expire_on_commit=False)
        with sessions() as db:
            for item in LEVELS.values():
                db.add(GameLevel(level_id=item['level_id'], game_id=item['game_id'], order_index=item['order']))
                db.add(GameLevelVersion(level_id=item['level_id'], level_version=1, definition=item))
            db.commit()
        def dependency():
            """每请求独立临时会话，所有线上凭据和数据保持隔离。"""
            with sessions() as db:
                yield db
        qa.api.app.dependency_overrides[qa.get_db] = dependency
        pk_lifecycle.SessionLocal = sessions
        settings = qa.get_settings()
        for key in ('progression_enabled', 'cosmetics_enabled', 'pk_rooms_enabled', 'matchmaking_enabled'):
            setattr(settings, key, True)
        settings.cookie_secure = False
        listener = socket.socket(); listener.bind(('127.0.0.1', 0)); base = f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server = qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app, log_level='error'))
        worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True); worker.start()
        try:
            deadline = time.monotonic()+10
            while not server.started and time.monotonic() < deadline:
                time.sleep(.05)
            assert server.started, '临时API未启动'
            with ExitStack() as stack:
                log = stack.enter_context((qa.OUTPUT/'progression-chrome.log').open('w', encoding='utf-8'))
                command, evaluate = stack.enter_context(browser(str(Path(temporary)/'chrome-one'), log))
                command2, evaluate2 = stack.enter_context(browser(str(Path(temporary)/'chrome-two'), log))
                def wait(expression, ev=evaluate, seconds=15):
                    """有界等待只在失败时返回条件与可见状态摘要。"""
                    until = time.monotonic()+seconds
                    while time.monotonic() < until:
                        if ev(f'(() => {{ try {{ return Boolean({expression}); }} catch {{ return false; }} }})()'):
                            return
                        time.sleep(.08)
                    raise AssertionError((expression, ev("({journey:document.getElementById('journey-status')?.textContent, formal:document.getElementById('formal-message')?.textContent, pk:document.getElementById('pk-message')?.textContent, room:document.getElementById('pk-room-status')?.textContent})")))
                def click(selector, ev=evaluate):
                    """DOM点击遵守按钮disabled及真实事件监听。"""
                    wait(f"(() => {{ const x=document.querySelector({json.dumps(selector)});return x && !x.disabled && x.getClientRects().length>0; }})()", ev)
                    ev(f'document.querySelector({json.dumps(selector)}).click()')
                def login(name, ev=evaluate):
                    """真实登录，测试密码只属于临时库。"""
                    wait("!document.querySelector('.auth-open').classList.contains('hidden')", ev)
                    click('.auth-open', ev)
                    ev(f"document.getElementById('auth-username').value={json.dumps(name)};document.getElementById('auth-password').value='progression-browser-secret';document.querySelector('.auth-submit').click()")
                    wait(f'document.querySelector(".auth-username")?.textContent==={json.dumps(name)}', ev)
                def shot(name, cmd=command):
                    """保存实际渲染截图，交付前做视觉核验。"""
                    png = cmd('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True})['data']
                    (qa.OUTPUT/name).write_bytes(base64.b64decode(png))
                def choose(level):
                    """通过正式目录确认规则，再由服务器创建尝试。"""
                    click(f'[data-level="{level}"]')
                    wait("document.getElementById('journey-rules').open")
                    click('#journey-rules-start')
                    wait("!document.getElementById('journey-rules').open && !document.getElementById('formal-play').hidden && !document.getElementById('formal-submit').disabled")
                def solve_akari(level):
                    """标准解仅在离线夹具求得；产品棋盘逐灯点击再正式提交。"""
                    solution = akari_solutions(LEVELS[level]['puzzle']['map'])[0]
                    for index in evaluate("Array.from(document.querySelectorAll('#formal-board [aria-pressed=true]')).map(x=>Number(x.dataset.index))"):
                        click(f'#formal-board [data-index="{index}"]')
                    for index in solution:
                        click(f'#formal-board [data-index="{index}"]')
                    click('#formal-submit'); wait("!document.getElementById('formal-result').hidden")
                    wait("!document.getElementById('formal-submit').textContent.includes('重试')")

                if '--pk-only' not in sys.argv:
                    command('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
                    command('Page.navigate', {'url': base+'journey.html'})
                    wait("document.querySelectorAll('.journey-level-card').length===10")
                    login('旅程甲')
                    wait("document.querySelector('[data-level=\"akari-004\"]').disabled")
                    checks.append('登录后十关按服务器锁定分组显示')
                    shot('progression-desktop.png')
                    click('[data-level="akari-001"]'); wait("document.getElementById('journey-rules').open")
                    with sessions() as db:
                        assert len(db.scalars(qa.select(GameAttempt)).all()) == 0
                    click('#journey-rules-start'); wait("document.querySelectorAll('#formal-board [data-index]').length===25")
                    click('#formal-board [data-index="0"]')
                    command('Page.reload'); wait("document.querySelectorAll('#formal-board [data-index]').length===25")
                    wait("document.getElementById('formal-timer').textContent!=='00:00'")
                    with sessions() as db:
                        assert len(db.scalars(qa.select(GameAttempt)).all()) == 1
                    checks.append('首次规则不创建尝试；刷新恢复原尝试并持续计时')
                    solution = akari_solutions(LEVELS['akari-001']['puzzle']['map'])[0]
                    for index in evaluate("Array.from(document.querySelectorAll('#formal-board [aria-pressed=true]')).map(x=>Number(x.dataset.index))"):
                        click(f'#formal-board [data-index="{index}"]')
                    for index in solution:
                        click(f'#formal-board [data-index="{index}"]')
                    command('Network.enable')
                    command('Network.emulateNetworkConditions', {'offline': True, 'latency': 0, 'downloadThroughput': -1, 'uploadThroughput': -1})
                    click('#formal-submit'); wait("document.getElementById('formal-submit').textContent.includes('重试')")
                    command('Network.emulateNetworkConditions', {'offline': False, 'latency': 0, 'downloadThroughput': -1, 'uploadThroughput': -1})
                    click('#formal-submit'); wait("!document.getElementById('formal-result').hidden")
                    wait("document.getElementById('journey-summary').textContent.includes('80 经验')")
                    checks.append('断网提交冻结原终盘，恢复后只领取一次80经验')
                    for level in ('akari-002', 'akari-003', 'akari-004'):
                        choose(level); solve_akari(level)
                        wait("document.getElementById('journey-status').textContent.includes('旅程已同步')")
                    wait("document.getElementById('journey-summary').textContent.includes('12 颗星')")
                    evaluate("Array.from(document.querySelectorAll('#journey-cosmetics button')).find(x=>x.textContent.includes('星光')).click()")
                    wait("document.getElementById('theme-message').textContent.includes('已保存')")
                    command('Page.reload'); wait("document.documentElement.dataset.theme==='starlight'")
                    checks.append('关卡推进升级解锁、累计12星后装备主题并跨刷新保存')
                    choose('mine-beginner-001')
                    with sessions() as db:
                        attempt = db.scalar(qa.select(GameAttempt).where(GameAttempt.level_id == 'mine-beginner-001', GameAttempt.status == 'active'))
                        safe = sorted(set(range(100))-set(attempt.board['mine_indices']))
                    for index in safe:
                        if evaluate(f"!document.querySelector('#formal-board [data-index=\"{index}\"]').disabled"):
                            click(f'#formal-board [data-index="{index}"]')
                            wait("!document.getElementById('formal-submit').disabled")
                    click('#formal-submit'); wait("!document.getElementById('formal-result').hidden")
                    choose('sudoku-beginner-001')
                    answer = sudoku_solutions(LEVELS['sudoku-beginner-001']['puzzle']['values'])[0]
                    evaluate(f"({json.dumps(answer)}).forEach((v,i)=>{{const x=document.querySelector('#formal-board [data-index=\"'+i+'\"]');if(!x.disabled){{x.value=v;x.dispatchEvent(new Event('input',{{bubbles:true}}))}}}})")
                    click('#formal-submit'); wait("!document.getElementById('formal-result').hidden")
                    wait("Array.from(document.querySelectorAll('#journey-qualifications a')).every(x=>x.textContent.includes('已通过'))")
                    checks.append('扫雷权威揭格与数独初级均经真实UI完成正式资格')
                    command('Emulation.setDeviceMetricsOverride', {'width': 375, 'height': 812, 'deviceScaleFactor': 1, 'mobile': True})
                    command('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
                    assert evaluate('document.documentElement.scrollWidth<=innerWidth'), '页面横向溢出'
                    shot('progression-mobile.png')
                    command('Emulation.setDeviceMetricsOverride', {'width': 812, 'height': 375, 'deviceScaleFactor': 1, 'mobile': True})
                    assert evaluate('document.documentElement.scrollWidth<=innerWidth')
                    checks.append('375px及横屏无页面横向溢出，棋盘在局部区域滚动')

                    (qa.OUTPUT/'progression-browser-checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
                else:
                    command('Page.navigate', {'url': base+'pk.html'}); login('旅程甲')
                    with sessions() as db:
                        first = db.scalar(qa.select(qa.User).where(qa.User.username == '旅程甲'))
                        for key in QUALIFICATIONS:
                            db.add(PlayerQualification(user_id=first.id, requirement_id=key, level_version=1, attempt_id=str(uuid4()), completed_at=utc_now()))
                        db.commit()
                command2('Page.navigate', {'url': base+'pk.html'}); login('旅程乙', evaluate2)
                wait("!document.getElementById('pk-locked').hidden", evaluate2)
                with sessions() as db:
                    user = db.scalar(qa.select(qa.User).where(qa.User.username == '旅程乙'))
                    for key in QUALIFICATIONS:
                        db.add(PlayerQualification(user_id=user.id, requirement_id=key, level_version=1, attempt_id=str(uuid4()), completed_at=utc_now()))
                    db.commit()
                click('#pk-refresh', evaluate2); wait("!document.getElementById('pk-lobby').hidden", evaluate2)
                command('Page.navigate', {'url': base+'pk.html'}); wait("!document.getElementById('pk-lobby').hidden")
                click('#pk-create'); wait("!document.getElementById('pk-room').hidden")
                code = evaluate("document.getElementById('pk-room-code').textContent")
                evaluate2(f"document.getElementById('pk-code').value={json.dumps(code)};document.getElementById('pk-join-form').requestSubmit()")
                wait("document.querySelectorAll('.pk-member').length===2", evaluate2)
                wait("document.querySelectorAll('.pk-member').length===2")
                assert evaluate("document.querySelectorAll('#pk-board [data-index]').length===0")
                click('#pk-ready'); click('#pk-ready', evaluate2)
                wait("document.getElementById('pk-room-status').textContent.includes('进行中')", seconds=20)
                wait("document.querySelectorAll('#pk-board [data-index]').length>0", evaluate2)
                with sessions() as db:
                    current_room = db.scalar(qa.select(PKRoom).where(PKRoom.room_code == code))
                    bulbs = akari_solutions(current_room.puzzle['puzzle']['map'])[0]
                for index in bulbs:
                    click(f'#pk-board [data-index="{index}"]'); click(f'#pk-board [data-index="{index}"]', evaluate2)
                click('#pk-submit'); click('#pk-submit', evaluate2)
                wait("!document.getElementById('pk-result').hidden")
                wait("!document.getElementById('pk-result').hidden", evaluate2)
                assert '平局' in evaluate("document.getElementById('pk-result').textContent")
                checks.append('两独立浏览器房间加入/准备/受控发题/SSE同步/平局结算')
                shot('pk-mobile-result.png')
                click('#pk-leave'); click('#pk-leave', evaluate2)
                click('#pk-match'); wait("!document.getElementById('pk-waiting').hidden")
                command('Page.reload'); wait("!document.getElementById('pk-waiting').hidden")
                click('#pk-cancel'); wait("document.getElementById('pk-waiting').hidden")
                click('#pk-match'); click('#pk-match', evaluate2)
                wait("!document.getElementById('pk-room').hidden")
                wait("!document.getElementById('pk-room').hidden", evaluate2)
                assert evaluate("document.getElementById('pk-room-code').textContent") == evaluate2("document.getElementById('pk-room-code').textContent")
                checks.append('排队跨刷新恢复、取消、再次匹配原子进入同一房间')
                click('.auth-logout'); wait("document.getElementById('pk-room').hidden && !document.querySelector('.auth-open').classList.contains('hidden')")
                checks.append('退出账号立即销毁旧棋盘和事件订阅')
        finally:
            server.should_exit = True; worker.join(timeout=10)
            qa.api.app.dependency_overrides.clear(); engine.dispose()
    (qa.OUTPUT/'pk-browser-checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Browser checks: {len(checks)} passed')


if __name__ == '__main__':
    # select只用于隔离验收夹具，不向页面暴露数据库查询。
    from sqlalchemy import select
    qa.select = select
    main()
