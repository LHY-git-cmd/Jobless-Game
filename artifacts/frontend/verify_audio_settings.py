"""通过独立 Chrome 与本机模拟账号验证游戏设置、真实媒体音量和跨页偏好恢复。

复用本项目浏览器驱动；不连接真实账号或数据库，鼠标与键盘使用浏览器原生输入事件。
"""
import base64
import functools
from http.server import ThreadingHTTPServer
import tempfile
import threading
from urllib.parse import urlparse

from verify_progress import Handler as ProgressHandler, ROOT, browser, wait_for


class Handler(ProgressHandler):
    """补充空排行榜，其他账号、挑战及静态资源复用原验证服务器。"""

    def do_GET(self):
        """排行榜页可正常装配共享账号、音频与游戏设置入口。"""
        path = urlparse(self.path).path
        if path.startswith("/api/rankings/"):
            return self.respond({"category": path.rsplit("/", 1)[-1], "page": 1, "page_size": 20, "total": 0, "entries": []})
        try:
            return super().do_GET()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # 刷新或换页会主动取消尚在传输的音频文件，不属于页面脚本错误。
            pass


def main():
    """核对默认开启、独立开关/音量、键盘滑块、刷新/跨页及手机弹窗。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/frontend/"
    try:
        with tempfile.TemporaryDirectory(prefix="audio-settings-qa-") as profile, (ROOT / "artifacts/frontend/audio-settings-browser.log").open("w") as log:
            with browser(profile, log) as (command, evaluate):
                def click(selector):
                    """可信鼠标手势允许真实浏览器授权音频播放。"""
                    point = evaluate(f"(() => {{ const b=document.querySelector({selector!r}); b.scrollIntoView({{block:'center',behavior:'instant'}}); const r=b.getBoundingClientRect(); return {{x:r.x+r.width/2,y:r.y+r.height/2}}; }})()")
                    for event in ["mousePressed", "mouseReleased"]:
                        command("Input.dispatchMouseEvent", {"type": event, **point, "button": "left", "clickCount": 1})

                def key(name, code, number):
                    """以原生键盘输入测试滑块和原生模态窗口。"""
                    for event in ["keyDown", "keyUp"]:
                        command("Input.dispatchKeyEvent", {"type": event, "key": name, "code": code, "windowsVirtualKeyCode": number})

                def volume(name, value):
                    """通过实际滑块 input 事件进入应用处理流程，不直接修改媒体或存档。"""
                    evaluate(f"(() => {{const r=document.getElementById('settings-{name}-volume'); r.value={value!r}; r.dispatchEvent(new Event('input',{{bubbles:true}})); }})()")

                command("Page.navigate", {"url": base + "index.html"})
                wait_for(evaluate, "document.querySelector('.auth-user')?.textContent === '恢复测试'")
                assert evaluate("document.querySelector('.auth-user').tagName") == "BUTTON"
                assert evaluate("document.getElementById('global-music') === null")
                click(".auth-user")
                assert evaluate("document.getElementById('game-settings').open")
                assert evaluate("document.getElementById('settings-music-enabled').getAttribute('aria-checked')") == "true"
                assert evaluate("document.getElementById('settings-effects-enabled').getAttribute('aria-checked')") == "true"
                assert evaluate("document.querySelector('[data-music=background]').volume") == .28
                assert evaluate("document.querySelector('[data-music=victory]').volume") == .65
                wait_for(evaluate, "!document.querySelector('[data-music=background]').paused")
                volume("music", "40")
                volume("effects", "70")
                evaluate("document.getElementById('settings-effects-volume').focus()")
                key("ArrowRight", "ArrowRight", 39)
                assert evaluate("document.getElementById('settings-effects-value').textContent") == "71%"
                assert evaluate("document.querySelector('[data-music=background]').volume") == .4
                assert evaluate("document.querySelector('[data-music=victory]').volume") == .71
                key("Tab", "Tab", 9)
                assert evaluate("document.activeElement.classList.contains('settings-close')")
                click("#settings-music-enabled")
                assert evaluate("document.querySelector('[data-music=background]').paused")
                evaluate("document.dispatchEvent(new CustomEvent('settlement-opened',{detail:{runId:'settings-effects-only'}}))")
                wait_for(evaluate, "!document.querySelector('[data-music=victory]').paused")
                click("#settings-effects-enabled")
                assert evaluate("document.querySelector('[data-music=victory]').paused")
                assert evaluate("document.querySelector('[data-music=background]').paused")
                click("#settings-music-enabled")
                wait_for(evaluate, "!document.querySelector('[data-music=background]').paused")
                click("#settings-music-enabled")
                key("Escape", "Escape", 27)
                assert evaluate("!document.getElementById('game-settings').open")
                assert evaluate("document.activeElement.classList.contains('auth-user')")
                command("Page.reload")
                wait_for(evaluate, "document.querySelector('.auth-user')?.textContent === '恢复测试'")
                click(".auth-user")
                assert evaluate("document.getElementById('settings-music-enabled').getAttribute('aria-checked')") == "false"
                assert evaluate("document.getElementById('settings-effects-enabled').getAttribute('aria-checked')") == "false"
                assert evaluate("document.getElementById('settings-music-value').textContent") == "40%"
                assert evaluate("document.getElementById('settings-effects-value').textContent") == "71%"
                key("Escape", "Escape", 27)
                click("#start-button")
                wait_for(evaluate, "document.querySelectorAll('#board button').length === 100")
                click("#rules-close")
                assert evaluate("document.getElementById('mine-sound').textContent") == "音效：关"
                click("#mine-sound")
                click("#back-button")
                click(".auth-user")
                assert evaluate("document.getElementById('settings-effects-enabled').getAttribute('aria-checked')") == "true"
                for width, height, suffix in [(1280, 1000, "desktop"), (375, 812, "mobile"), (812, 375, "landscape")]:
                    command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 900})
                    evaluate("document.querySelector('.settings-close').focus()")
                    assert evaluate("(() => {const r=document.getElementById('game-settings').getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight})()")
                    png = command("Page.captureScreenshot", {"format": "png"})["data"]
                    (ROOT / f"artifacts/frontend/audio-settings-{suffix}.png").write_bytes(base64.b64decode(png))
                command("Page.navigate", {"url": base + "ranking.html"})
                wait_for(evaluate, "document.querySelector('.auth-user')?.textContent === '恢复测试'")
                click(".auth-user")
                assert evaluate("document.getElementById('settings-music-value').textContent") == "40%"
                assert evaluate("document.getElementById('settings-effects-value').textContent") == "71%"
                assert evaluate("document.getElementById('global-music') === null")
        print("浏览器验收：用户名设置入口、默认开启、背景/音效独立控制、实际音量、刷新跨页、键盘与手机布局均通过。")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
