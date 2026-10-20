"""作用：用真实 Chrome/FastAPI 和临时 SQLite 验证模块化后的缓存、续玩与卸载。

账号和游戏记录仅写入临时数据库；不连接 MySQL、目标服务器或修改正式存档。
复用现有无头浏览器/CDP 夹具，只输出验收统计，完整日志由调用方重定向。
"""

import json
from pathlib import Path
import socket
import tempfile
import threading
import time

import httpx
import verify_ranking as qa
from verify_progress import browser, wait_for


def main():
    """真实操作界面并重启浏览器；恢复、时间和动画均使用生产模块。"""
    checks = []
    with tempfile.TemporaryDirectory(prefix='refactor-qa-') as temporary:
        engine = qa.create_engine('sqlite:///' + (Path(temporary) / 'qa.sqlite').as_posix(), connect_args={'check_same_thread': False})
        qa.Base.metadata.create_all(engine)
        sessions = qa.sessionmaker(engine, expire_on_commit=False)

        def dependency():
            """每个请求使用独立临时会话，覆盖真实刷新后的数据库读取。"""
            with sessions() as db:
                yield db

        qa.api.app.dependency_overrides[qa.get_db] = dependency
        settings = qa.get_settings()
        previous = settings.cookie_secure, settings.dev_quick_complete_enabled
        settings.cookie_secure = False
        settings.dev_quick_complete_enabled = True
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        base = f'http://127.0.0.1:{listener.getsockname()[1]}/'
        server = qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app, log_level='error'))
        worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(.05)
            assert server.started
            with httpx.Client(base_url=base, trust_env=False) as client:
                for path in ('', 'forum.html', 'src/main.js', 'styles.css'):
                    response = client.get(path)
                    assert response.status_code == 200 and response.headers['cache-control'] == 'no-cache'
                    cached = client.get(path, headers={'If-None-Match': response.headers['etag']})
                    assert cached.status_code == 304 and cached.headers['cache-control'] == 'no-cache'
                checks.append('真实 HTTP 的 HTML/JS/CSS 每次验证，ETag/304 保持有效')
                audio = client.get('assets/audio/explosion.wav', headers={'Range': 'bytes=0-63'})
                assert audio.status_code == 206 and 'max-age=604800' in audio.headers['cache-control']
                assert client.get('api/nonexistent-refactor-probe').headers['cache-control'] == 'no-store'
                checks.append('音频缓存及分段读取保持，API 不受静态缓存策略覆盖')

            profile = str(Path(temporary) / 'chrome')
            with (qa.OUTPUT / 'refactor-browser-chrome.log').open('w', encoding='utf-8') as log:
                with browser(profile, log) as (command, evaluate):
                    command('Page.navigate', {'url': base})
                    wait_for(evaluate, "!!document.querySelector('.auth-open')")
                    evaluate("document.getElementById('sudoku-entry').click()")
                    wait_for(evaluate, "document.getElementById('auth-dialog').open")
                    evaluate("document.getElementById('auth-username').value='重构验收';document.getElementById('auth-password').value='refactor-secret';document.querySelector('.auth-submit').click()")
                    wait_for(evaluate, "!document.getElementById('sudoku-rules-dialog').classList.contains('hidden')")
                    assert evaluate("!document.getElementById('akari-entry').disabled && !document.getElementById('start-button').disabled")
                    time.sleep(1.1)
                    command('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Escape', 'windowsVirtualKeyCode': 27})
                    assert evaluate("!document.getElementById('sudoku-rules-dialog').classList.contains('hidden') && document.getElementById('sudoku-timer').textContent==='00:00'")
                    checks.append('任意选关及真实 Cookie 登录，首次规则和 Esc 不提前计时')
                    evaluate("document.getElementById('sudoku-rules-close').click()")
                    wait_for(evaluate, "document.getElementById('sudoku-timer').textContent!=='00:00'")
                    evaluate("document.getElementById('sudoku-rules').click()")
                    before = evaluate("document.getElementById('sudoku-timer').textContent")
                    wait_for(evaluate, f"document.getElementById('sudoku-timer').textContent>{json.dumps(before)}")
                    command('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Escape', 'windowsVirtualKeyCode': 27})
                    assert evaluate("document.getElementById('sudoku-rules-dialog').classList.contains('hidden') && document.activeElement.id==='sudoku-rules'")
                    checks.append('无需棋盘操作也计时，重看规则继续累计并恢复键盘焦点')

                    evaluate("document.getElementById('sudoku-notes-toggle').click();document.querySelector('#sudoku-board [data-index=\"0\"]').click()")
                    for digit in ('2', '5', '9'):
                        command('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': digit, 'code': f'Digit{digit}', 'windowsVirtualKeyCode': 48 + int(digit)})
                    assert evaluate("document.querySelector('#sudoku-board [data-index=\"0\"]').getAttribute('aria-label')").endswith('候选数 2、5、9')
                    cells = evaluate("document.getElementById('sudoku-board').innerHTML")
                    command('Page.reload')
                    wait_for(evaluate, "document.getElementById('sudoku-notes-toggle')?.getAttribute('aria-pressed')==='true'")
                    assert evaluate("document.getElementById('sudoku-board').innerHTML") == cells
                    checks.append('数独候选笔记、键盘输入和整个棋盘刷新后恢复')

                    command('Page.navigate', {'url': base + 'forum.html'})
                    wait_for(evaluate, "document.querySelector('.auth-username')?.textContent==='重构验收'")
                    wait_for(evaluate, "document.getElementById('forum-status')?.textContent.includes('还没有')")
                    command('Page.navigate', {'url': base})
                    wait_for(evaluate, "document.querySelectorAll('#sudoku-board button').length===81")
                    assert evaluate("document.getElementById('sudoku-board').innerHTML") == cells
                    before_restart = evaluate("document.getElementById('sudoku-timer').textContent")
                    checks.append('真实跨页论坛保留登录，返回游戏恢复原棋盘')
                time.sleep(2)
                with browser(profile, log) as (command, evaluate):
                    command('Page.navigate', {'url': base})
                    wait_for(evaluate, "document.querySelectorAll('#sudoku-board button').length===81")
                    assert evaluate("document.getElementById('sudoku-board').innerHTML") == cells
                    assert evaluate("document.getElementById('sudoku-timer').textContent") > before_restart
                    checks.append('关闭并重启浏览器后 Cookie/棋盘/笔记恢复，离开时间继续累计')
                    evaluate("document.getElementById('sudoku-back').click();document.getElementById('akari-entry').click()")
                    wait_for(evaluate, "!document.getElementById('akari-rules-dialog').classList.contains('hidden')")
                    evaluate("document.getElementById('akari-rules-close').click();document.querySelector('#akari-board [data-index=\"0\"]').click()")
                    akari_cells = evaluate("document.getElementById('akari-board').innerHTML")
                    evaluate("document.getElementById('akari-back').click();document.getElementById('sudoku-entry').click()")
                    wait_for(evaluate, "!document.getElementById('sudoku-screen').classList.contains('hidden')")
                    assert evaluate("document.getElementById('sudoku-board').innerHTML") == cells
                    evaluate("document.getElementById('sudoku-back').click();document.getElementById('akari-entry').click()")
                    wait_for(evaluate, "!document.getElementById('akari-screen').classList.contains('hidden')")
                    assert evaluate("document.getElementById('akari-board').innerHTML") == akari_cells
                    checks.append('切换数独和照明保留各自棋盘及笔记')
                    evaluate("document.getElementById('akari-back').click();document.getElementById('start-button').click()")
                    wait_for(evaluate, "!document.getElementById('rules-dialog').classList.contains('hidden')")
                    evaluate("document.getElementById('rules-close').click()")
                    # 只读取真实保存的雷位置以稳定触发失败，所有操作仍经真实棋盘按钮。
                    evaluate("(()=>{const key=Object.keys(localStorage).find(k=>k.startsWith('jobless-progress-v1:')),g=JSON.parse(localStorage.getItem(key)).game,i=g.cells.findIndex(c=>!c.mine);document.querySelector(`#board [data-index='${i}']`).click();document.getElementById('reveal-button').click();})()")
                    evaluate("(()=>{const key=Object.keys(localStorage).find(k=>k.startsWith('jobless-progress-v1:')),g=JSON.parse(localStorage.getItem(key)).game,i=g.cells.findIndex(c=>c.mine);document.querySelector(`#board [data-index='${i}']`).click();document.getElementById('reveal-button').click();})()")
                    evaluate("import('/src/main.js').then(({app})=>{app.destroy();window.refactorDisposed=true;})")
                    wait_for(evaluate, 'window.refactorDisposed===true')
                    after_destroy = evaluate("document.getElementById('board').innerHTML")
                    frozen_time = evaluate("document.getElementById('timer').textContent")
                    time.sleep(2.5)
                    assert evaluate("document.getElementById('board').innerHTML") == after_destroy
                    assert evaluate("document.getElementById('result-dialog').classList.contains('hidden')")
                    assert evaluate("document.getElementById('timer').textContent") == frozen_time
                    checks.append('爆炸途中卸载实例停止动画、定时器及结果回调')
                    command('Page.reload')
                    wait_for(evaluate, "document.getElementById('result-title')?.textContent==='游戏失败'")
                    assert evaluate("document.querySelectorAll('#board .cell-mine').length") == 10
                    assert evaluate("document.getElementById('timer').textContent") == frozen_time
                    checks.append('失败存档刷新直接恢复十颗地雷终盘，时间冻结且不重播爆炸')
            print(json.dumps({'checks_passed': len(checks), 'uncaught_errors': 0, 'checks': checks}, ensure_ascii=False))
        finally:
            settings.cookie_secure, settings.dev_quick_complete_enabled = previous
            qa.api.app.dependency_overrides.pop(qa.get_db, None)
            server.should_exit = True
            worker.join(timeout=10)
            listener.close()
            engine.dispose()


if __name__ == '__main__':
    main()
