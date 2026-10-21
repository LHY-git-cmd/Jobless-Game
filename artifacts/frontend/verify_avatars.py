"""作用：用独立 Chrome、真实 FastAPI 和临时 SQLite 验收预设头像、四榜、音频及手机键盘交互。

所有账号只存在临时目录，不连接本机或服务器 MySQL；不替代 Flyway、InnoDB 和服务器容量验收。
复用项目 CDP 浏览器驱动；截图和完整日志留在 artifacts/frontend，最终只输出验收统计。
"""

import base64
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from uuid import uuid4

import verify_ranking as qa
from verify_progress import browser


def main():
    """真实点击验证头像全流程，并检查刷新/跨浏览器保持、四榜当前头像和手机布局。"""
    checks = []
    with tempfile.TemporaryDirectory(prefix="avatar-qa-") as temporary:
        engine = qa.create_engine("sqlite:///" + (Path(temporary) / "qa.sqlite").as_posix(), connect_args={"check_same_thread": False})
        qa.Base.metadata.create_all(engine)
        sessions = qa.sessionmaker(engine, expire_on_commit=False)

        def test_db():
            """每次请求只使用当前临时数据库，验证真实提交后的读取。"""
            with sessions() as db:
                yield db

        qa.api.app.dependency_overrides[qa.get_db] = test_db
        settings = qa.get_settings()
        previous_secure = settings.cookie_secure
        settings.cookie_secure = False
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app, log_level="error"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started, "临时服务未启动"
        base = f"http://127.0.0.1:{port}/"
        try:
            with (qa.OUTPUT / "avatar-browser.log").open("w", encoding="utf-8") as log:
                with browser(str(Path(temporary) / "chrome"), log) as (command, _):
                    def evaluate(expression):
                        """支持等待页面 fetch，保持浏览器实际 Cookie 与来源行为。"""
                        result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
                        if "exceptionDetails" in result:
                            raise AssertionError(result["exceptionDetails"])
                        return result.get("result", {}).get("value")

                    def wait(expression):
                        """等待界面异步状态，失败只输出条件和相关状态摘要。"""
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            if evaluate(expression):
                                return
                            time.sleep(.05)
                        raise AssertionError((expression, evaluate("({avatar:document.querySelector('.avatar-status')?.textContent,auth:document.querySelector('#auth-status')?.textContent})")))

                    def click(selector):
                        """可信鼠标输入可同时覆盖原生模态和音频手势行为。"""
                        point = evaluate(f"(() => {{const b=document.querySelector({json.dumps(selector)}); b.scrollIntoView({{block:'center',behavior:'instant'}}); const r=b.getBoundingClientRect(); return {{x:r.x+r.width/2,y:r.y+r.height/2}};}})()")
                        for event in ("mousePressed", "mouseReleased"):
                            command("Input.dispatchMouseEvent", {"type": event, **point, "button": "left", "clickCount": 1})

                    def key(name, number):
                        """发送原生按键，检查选择按钮、模态焦点和原有音量滑块。"""
                        for event in ("keyDown", "keyUp"):
                            text = {"text": "\r", "unmodifiedText": "\r"} if name == "Enter" and event == "keyDown" else {}
                            command("Input.dispatchKeyEvent", {"type": event, "key": name, "code": name, "windowsVirtualKeyCode": number, **text})

                    def navigate(name):
                        """使用相同浏览器 Cookie 跨独立 HTML 页面恢复账号。"""
                        command("Page.navigate", {"url": base + name})
                        wait("document.readyState==='complete' && !!document.querySelector('.auth-open')")

                    def shot(name):
                        """保存实际页面截图，供桌面和手机视觉检查。"""
                        result = command("Page.captureScreenshot", {"format": "png"})
                        (qa.OUTPUT / name).write_bytes(base64.b64decode(result["data"]))

                    command("Network.enable")
                    command("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 960, "deviceScaleFactor": 1, "mobile": False})
                    navigate("index.html")
                    click(".auth-open")
                    wait("document.querySelector('#auth-dialog').open")
                    evaluate("document.querySelector('#auth-username').value='头像验收';document.querySelector('#auth-password').value='avatar-secret';")
                    click(".auth-submit")
                    wait("!document.querySelector('.auth-user').classList.contains('hidden')")
                    assert evaluate("document.querySelector('.auth-avatar').getAttribute('src')") == "/assets/avatars/v1/001.webp"
                    assert not evaluate("performance.getEntriesByType('resource').some(r=>r.name.includes('avatars/v1/catalog.json'))")
                    checks.append("真实注册默认头像和选择器清单按需加载")

                    click("#start-button")
                    wait("!document.getElementById('rules-dialog').classList.contains('hidden')")
                    click("#rules-close")
                    click("#back-button")
                    progress_before = evaluate("Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('jobless-progress-v1:')).map(k=>[k,localStorage.getItem(k)]))")
                    assert progress_before, "未生成真实棋局存档"
                    evaluate("window.avatarAuthChanges=0;document.addEventListener('auth-changed',()=>{window.avatarAuthChanges++})")

                    command("Network.setBlockedURLs", {"urls": ["*avatars/v1/catalog.json*"]})
                    click(".auth-user")
                    wait("!document.querySelector('.avatar-retry').hidden")
                    assert evaluate("document.querySelector('.avatar-save').disabled")
                    command("Network.setBlockedURLs", {"urls": []})
                    click(".avatar-retry")
                    wait("document.querySelectorAll('.avatar-option').length===25")
                    wait("[...document.querySelectorAll('.avatar-option img')].every(i=>i.complete&&i.naturalWidth===128)")
                    checks.append("清单失败可重试，25 张硬盘图片均真实解码")
                    shot("avatar-desktop.png")

                    click('[data-avatar-id="17"]')
                    command("Network.setBlockedURLs", {"urls": ["*api/auth/avatar*"]})
                    click(".avatar-save")
                    wait("document.querySelector('.avatar-status').textContent.includes('连接失败')")
                    assert evaluate("document.querySelector('.auth-avatar').getAttribute('src')") == "/assets/avatars/v1/001.webp"
                    command("Network.setBlockedURLs", {"urls": []})
                    click(".avatar-save")
                    wait("document.querySelector('.avatar-status').textContent.includes('已保存')")
                    assert evaluate("document.querySelector('.auth-avatar').getAttribute('src')") == "/assets/avatars/v1/017.webp"
                    checks.append("失败不更换当前头像，重试成功后同步账号入口")
                    assert evaluate("window.avatarAuthChanges") == 0
                    assert evaluate("Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('jobless-progress-v1:')).map(k=>[k,localStorage.getItem(k)]))") == progress_before
                    checks.append("换头像不触发换号事件，真实棋局存档保持不变")

                    click(".avatar-dialog-close"); click(".auth-settings")
                    evaluate("document.getElementById('settings-effects-volume').value='70'; document.getElementById('settings-effects-volume').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('settings-effects-volume').focus();")
                    key("ArrowRight", 39)
                    assert evaluate("document.getElementById('settings-effects-value').textContent") == "71%"
                    assert evaluate("document.querySelector('[data-music=victory]').volume") == .71
                    key("Tab", 9)
                    assert evaluate("document.activeElement.classList.contains('settings-close')")
                    key("Escape", 27)
                    assert evaluate("!document.getElementById('game-settings').open && document.activeElement.classList.contains('auth-settings')")
                    checks.append("音效音量仍即时生效，Tab 循环和 Esc 恢复入口焦点")

                    command("Page.reload")
                    wait("document.querySelector('.auth-avatar')?.getAttribute('src')==='/assets/avatars/v1/017.webp'")
                    with sessions() as db:
                        user = db.query(qa.User).filter_by(username="头像验收").one()
                        for number, category in enumerate(("mine", "akari", "sudoku", "total"), 1):
                            db.add(qa.CompletionRecord(id=number, user_id=user.id, category=category, run_id=str(uuid4()), attempt_id=str(uuid4()),
                                duration_seconds=30, completed_at=qa.utc_now(), mine_seconds=10 if category == "total" else None,
                                akari_seconds=10 if category == "total" else None, sudoku_seconds=10 if category == "total" else None))
                            db.flush()
                            db.add(qa.LeaderboardEntry(user_id=user.id, category=category, best_record_id=number, best_duration_seconds=30, achieved_at=qa.utc_now()))
                        db.commit()
                    navigate("forum.html")
                    wait("document.querySelector('.auth-avatar')?.getAttribute('src')==='/assets/avatars/v1/017.webp'")
                    for filename in ("ranking.html", "ranking-mine.html", "ranking-akari.html", "ranking-sudoku.html"):
                        navigate(filename)
                        wait("document.querySelector('.ranking-identity img')?.getAttribute('src')==='/assets/avatars/v1/017.webp'")
                        assert evaluate("document.querySelector('.ranking-player').textContent") == "头像验收"
                    checks.append("刷新保持且四个排行榜均显示当前账号头像")

                    click(".auth-user")
                    wait("document.querySelectorAll('.avatar-option').length===25")
                    click('[data-avatar-id="25"]'); click(".avatar-save")
                    wait("document.querySelector('.ranking-identity img').getAttribute('src')==='/assets/avatars/v1/025.webp'")
                    assert evaluate("document.querySelector('.ranking-position').textContent") == "1"
                    checks.append("榜单同页换头像立即更新，原名次和成绩保持")

                    evaluate("document.querySelector('[data-avatar-id=\"18\"]').focus()")
                    key("Enter", 13)
                    assert evaluate("document.querySelector('[data-avatar-id=\"18\"]').getAttribute('aria-pressed')") == "true", evaluate("({active:document.activeElement.outerHTML, selected:[...document.querySelectorAll('.avatar-option[aria-pressed=true]')].map(b=>b.dataset.avatarId), status:document.querySelector('.avatar-status').textContent})")
                    assert evaluate("document.querySelector('.auth-avatar').getAttribute('src')") == "/assets/avatars/v1/025.webp"
                    click(".avatar-dialog-close"); click(".auth-user")
                    assert evaluate("document.querySelector('.avatar-preview img').getAttribute('src')") == "/assets/avatars/v1/025.webp"
                    checks.append("键盘选择与未保存预览，关闭重开恢复当前头像")

                    for width in (390, 320):
                        command("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": False})
                        evaluate("document.getElementById('avatar-dialog').scrollTop=0")
                        assert evaluate("document.documentElement.scrollWidth<=innerWidth")
                        assert evaluate("(()=>{const d=document.getElementById('avatar-dialog');return d.scrollWidth<=d.clientWidth && d.getBoundingClientRect().right<=innerWidth;})()")
                        assert evaluate("(()=>{const g=document.querySelector('.avatar-grid');return g.scrollWidth<=g.clientWidth;})()"), f"{width}px 头像网格内部横向溢出"
                        assert evaluate("[...document.querySelectorAll('.avatar-option')].every(b=>b.getBoundingClientRect().width>=44)")
                        shot(f"avatar-mobile-{width}.png")
                    click(".avatar-dialog-close")
                    shot("avatar-ranking-mobile.png")
                    checks.append("390px/320px 设置与榜单不横向溢出，选择按钮至少44px")

                    click(".auth-user")
                    evaluate("document.querySelector('.auth-avatar').src='/assets/avatars/v1/not-found.webp'")
                    wait("document.querySelector('.auth-avatar').getAttribute('src')==='/assets/avatars/v1/001.webp'")
                    click(".avatar-dialog-close")
                    click(".auth-logout")
                    wait("document.querySelector('.auth-user').classList.contains('hidden')")
                    assert evaluate("document.querySelector('.avatar-preview img').getAttribute('src')") == "/assets/avatars/v1/001.webp"
                    checks.append("图片失败回退默认图，退出立即清理账号预览")

                with browser(str(Path(temporary) / "second-browser"), log) as (command, evaluate):
                    command("Page.navigate", {"url": base + "index.html"})
                    deadline = time.monotonic() + 10
                    while not evaluate("!!document.querySelector('.auth-open')") and time.monotonic() < deadline:
                        time.sleep(.05)
                    evaluate("document.querySelector('.auth-open').click()")
                    evaluate("document.querySelector('#auth-username').value='头像验收';document.querySelector('#auth-password').value='avatar-secret';document.querySelector('.auth-submit').click()")
                    deadline = time.monotonic() + 10
                    while not evaluate("document.querySelector('.auth-avatar')?.getAttribute('src')==='/assets/avatars/v1/025.webp'") and time.monotonic() < deadline:
                        time.sleep(.05)
                    assert evaluate("document.querySelector('.auth-avatar').getAttribute('src')") == "/assets/avatars/v1/025.webp"
                    checks.append("独立浏览器重新登录恢复服务器保存的头像")
            print(f"浏览器头像验收：{len(checks)} 项通过，0 失败，0 未处理页面异常。")
        finally:
            settings.cookie_secure = previous_secure
            qa.api.app.dependency_overrides.clear()
            server.should_exit = True
            worker.join(timeout=10)
            listener.close()
            engine.dispose()


if __name__ == "__main__":
    main()
