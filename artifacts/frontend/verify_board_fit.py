"""作用：在隔离SQLite和独立Chrome中验证扫雷/照明整盘适配、旋转及缩放后点击。

只操作临时测试账号；截图与日志保存在artifacts/frontend，不访问业务数据库。
"""
import base64
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from sqlalchemy import select
import verify_ranking as qa
from verify_progress import browser
from verify_sudoku import environment
from backend.app.common.game_catalog import AKARI_LEVELS
from backend.app.models.entities.progression import PlayerEnergy
from backend.app.services import progression_service


def main():
    """真实页面逐关进入，在窄屏、横屏和桌面检查棋盘及交互。"""
    checks = 0
    zoom_checks = 0
    with tempfile.TemporaryDirectory(prefix='board-fit-') as temporary:
        engine, sessions = environment(Path(temporary) / 'qa.sqlite')
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        base = f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server = qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app, log_level='error', lifespan='off'))
        worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(.025)
            assert server.started
            with (qa.OUTPUT / 'board-fit-chrome.log').open('w', encoding='utf-8') as log, browser(str(Path(temporary) / 'chrome'), log) as (cmd, ev):
                def wait(expression):
                    """有界等待页面，失败仅报告条件和游戏内提示。"""
                    deadline = time.monotonic() + 12
                    while time.monotonic() < deadline:
                        if ev(f'(()=>{{try{{return Boolean({expression})}}catch{{return false}}}})()'):
                            return
                        time.sleep(.025)
                    raise AssertionError((expression, ev("document.querySelector('#mine-message,#akari-message')?.textContent")))

                def click(selector):
                    """触发产品按钮的真实事件监听器。"""
                    literal = json.dumps(selector)
                    wait(f'document.querySelector({literal})?.getClientRects().length&&!document.querySelector({literal}).disabled')
                    ev(f'document.querySelector({literal}).click()')

                def shot(name):
                    """保存当前视口，供人工检查字形、格线和布局。"""
                    (qa.OUTPUT / name).write_bytes(base64.b64decode(cmd('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})['data']))

                def dimensions(width, height):
                    """模拟设备尺寸，使用手机viewport而非整页截图缩放。"""
                    cmd('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': True})

                cmd('Page.enable')
                cmd('Runtime.enable')
                cmd('Page.addScriptToEvaluateOnNewDocument', {'source': "window.fitErrors=[];addEventListener('error',e=>fitErrors.push(e.message));addEventListener('unhandledrejection',e=>fitErrors.push(String(e.reason)))"})
                dimensions(375, 667)
                cmd('Page.navigate', {'url': base + 'journey.html?game_id=mine'})
                wait("document.querySelector('.auth-open')")
                click('.auth-open')
                ev("document.querySelector('#auth-username').value='棋盘适配验收';document.querySelector('#auth-password').value='board-fit-test';document.querySelector('.auth-submit').click()")
                wait("document.querySelector('#journey-status').textContent==='账号资料已同步。'")
                cases = [('mine', 'mine-v2-tutorial', 'tutorial'), ('mine', 'mine-v2-easy-10', 'easy'), ('mine', 'mine-v2-easy-15', 'easy'), ('mine', 'mine-v2-easy-20', 'easy')]
                cases += [('akari', level['level_id'], None) for level in AKARI_LEVELS]
                current = 'mine'
                for game, level_id, difficulty in cases:
                    progression_service.limiter.clear()
                    # 补充的体力仅属于临时数据库，避免布局验收受次数限制影响。
                    with sessions() as db:
                        energy = db.scalar(select(PlayerEnergy))
                        if energy:
                            energy.current = 10
                            energy.recovery_at = None
                            db.commit()
                    if current != game:
                        assert ev('fitErrors') == []
                        cmd('Page.navigate', {'url': base + 'journey.html?game_id=' + game})
                        wait(f'document.querySelector("#{game}-levels button:not(:disabled)")')
                        current = game
                    if difficulty:
                        click(f'[data-difficulty="{difficulty}"]')
                    click(f'#{game}-journey [data-level="{level_id}"]')
                    click(f'#{game}-enter-confirm')
                    wait(f'!document.querySelector("#{game}-play").hidden&&!document.querySelector("#{game}-restart").disabled')
                    for width, height in [(320, 568), (375, 667), (390, 844), (430, 932), (844, 390), (1440, 1000)]:
                        dimensions(width, height)
                        time.sleep(.07)
                        ev(f'document.querySelector("#{game}-play").scrollIntoView({{block:"start",behavior:"instant"}})')
                        metrics = ev(f'''(()=>{{
                          const b=document.querySelector('#{game}-board'),v=document.querySelector('#{game}-viewport');
                          const r=b.getBoundingClientRect(),a=v.getBoundingClientRect(),cells=b.children;
                          const first=cells[0].getBoundingClientRect(),last=cells[cells.length-1].getBoundingClientRect();
                          return {{width:r.width,height:r.height,top:r.top,bottom:r.bottom,left:r.left,right:r.right,
                            viewportWidth:v.clientWidth,scrollWidth:v.scrollWidth,viewportHeight:v.clientHeight,scrollHeight:v.scrollHeight,
                            cellsInside:first.left>=r.left&&first.top>=r.top&&last.right<=r.right+.1&&last.bottom<=r.bottom+.1,
                            inside:r.left>=a.left&&r.right<=a.right+.1&&r.top>=a.top&&r.bottom<=a.bottom+.1,
                            pageWidth:document.documentElement.scrollWidth,screenWidth:innerWidth,screenHeight:innerHeight}};
                        }})()''')
                        assert metrics['scrollWidth'] <= metrics['viewportWidth'] + 1, (level_id, width, metrics)
                        assert metrics['scrollHeight'] <= metrics['viewportHeight'] + 1, (level_id, width, metrics)
                        assert metrics['inside'] and metrics['cellsInside'], (level_id, width, metrics)
                        assert metrics['pageWidth'] <= metrics['screenWidth'], (level_id, width, metrics)
                        assert metrics['top'] >= -1 and metrics['bottom'] <= metrics['screenHeight'] + 1, (level_id, width, metrics)
                        checks += 1
                        if level_id in ['mine-v2-easy-20', 'akari-v2-tutorial', AKARI_LEVELS[-1]['level_id']] and width in [320, 375, 844]:
                            shot(f'board-fit-{level_id}-{width}.png')
                    dimensions(375, 667)
                    time.sleep(.08)
                    ev(f'document.querySelector("#{game}-play").scrollIntoView({{block:"start",behavior:"instant"}})')
                    # 原生页面缩放会缩小visualViewport，但棋盘CSS尺寸不应抵消用户放大。
                    touch_action = ev(f'getComputedStyle(document.querySelector("#{game}-viewport")).touchAction')
                    assert touch_action in ['auto', 'manipulation'] or 'pinch-zoom' in touch_action, (game, touch_action)
                    baseline = ev(f'document.querySelector("#{game}-board").getBoundingClientRect().width')
                    for factor in [1.5, 2, 3, 2, 1]:
                        cmd('Emulation.setPageScaleFactor', {'pageScaleFactor': factor})
                        time.sleep(.08)
                        actual = ev(f'({{width:document.querySelector("#{game}-board").getBoundingClientRect().width,scale:visualViewport.scale}})')
                        assert abs(actual['scale'] - factor) < .02, (level_id, factor, actual)
                        assert abs(actual['width'] - baseline) <= 1, ('缩放抵消了棋盘尺寸', level_id, factor, baseline, actual)
                        # 缩放时点击触发会话重新渲染，也不能把棋盘再次缩小。
                        if factor == 2:
                            selector = '.mine-square:not(:disabled)' if game == 'mine' else '.akari-cell:not(:disabled)'
                            if ev(f'Boolean(document.querySelector("{selector}"))'):
                                click(selector)
                                wait(f'!document.querySelector("#{game}-restart").disabled')
                                width_after = ev(f'document.querySelector("#{game}-board").getBoundingClientRect().width')
                                assert abs(width_after - baseline) <= 1, ('放大后操作导致棋盘缩小', level_id, baseline, width_after)
                        if factor == 2 and level_id in ['mine-v2-easy-20', AKARI_LEVELS[-1]['level_id']]:
                            shot(f'board-zoom-{level_id}-200.png')
                        zoom_checks += 1
                    if difficulty == 'easy' or (game == 'akari' and level_id != AKARI_LEVELS[0]['level_id']):
                        selector = '.mine-square' if game == 'mine' else '.akari-cell:not(:disabled)'
                        point = ev(f'(()=>{{const r=document.querySelector("{selector}").getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()')
                        cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'button': 'left', 'clickCount': 1, **point})
                        cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'button': 'left', 'clickCount': 1, **point})
                        wait("document.querySelector('.mine-selected')" if game == 'mine' else "document.querySelector('.akari-cell.bulb')")
                        checks += 1
                    if game == 'akari':
                        click('#akari-pause-toggle')
                        wait("!document.querySelector('#akari-pause').hidden")
                        click('#akari-resume')
                        wait("document.querySelector('#akari-pause').hidden")
                    click(f'#{game}-back')
                    click('[data-exit-confirm]')
                    wait(f'document.querySelector("#{game}-play").hidden')
                    assert ev('fitErrors') == [], ev('fitErrors')
                print(json.dumps({'checks': checks, 'zoom_checks': zoom_checks, 'failures': 0, 'boards': len(cases)}, ensure_ascii=False))
        finally:
            server.should_exit = True
            worker.join(10)
            qa.api.app.dependency_overrides.clear()
            engine.dispose()


if __name__ == '__main__':
    main()
