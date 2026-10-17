"""验证真实前端计时器随时间刷新，不替换 Date.now、不注入假用时。

使用独立浏览器和本机临时静态服务检查照明、数独与扫雷；
输出两秒后的计时，并保存照明截图。用户正在玩的页面不会被修改。
"""

import base64
import functools
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from urllib.request import urlopen
import websocket

from verify_akari_completion import Handler, ROOT, OUTPUT, CHROME


def main():
    """通过真实按钮启动计时并等待，核对自动刷新、重开和通关后冻结。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="live-timer-qa-") as profile:
            with (OUTPUT / "live-timers-browser.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([
                    str(CHROME), "--headless", "--disable-gpu", "--no-first-run",
                    "--disable-background-networking", f"--user-data-dir={profile}",
                    "--remote-debugging-port=0", "about:blank",
                ], stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
                connection = None
                try:
                    port_file = Path(profile) / "DevToolsActivePort"
                    deadline = time.monotonic() + 15
                    while not port_file.exists() and time.monotonic() < deadline:
                        time.sleep(.1)
                    port = port_file.read_text().splitlines()[0]
                    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                        page = next(tab for tab in json.load(response) if tab["type"] == "page")
                    connection = websocket.create_connection(page["webSocketDebuggerUrl"], suppress_origin=True, timeout=10)
                    serial = 0
                    errors = []

                    def command(method, params=None):
                        nonlocal serial
                        serial += 1
                        connection.send(json.dumps({"id": serial, "method": method, "params": params or {}}))
                        while True:
                            reply = json.loads(connection.recv())
                            if reply.get("method") == "Runtime.exceptionThrown":
                                errors.append(reply["params"])
                            if reply.get("id") == serial:
                                if "error" in reply:
                                    raise RuntimeError(reply["error"])
                                return reply.get("result", {})

                    def evaluate(expression):
                        result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                        if "exceptionDetails" in result:
                            raise RuntimeError(result["exceptionDetails"])
                        return result.get("result", {}).get("value")

                    def click(selector):
                        evaluate(f"document.querySelector({json.dumps(selector)}).click()")

                    def timer(selector):
                        return evaluate(f"document.querySelector({json.dumps(selector)}).textContent")

                    def assert_ticks(selector):
                        before = timer(selector)
                        deadline = time.monotonic() + 4
                        while time.monotonic() < deadline:
                            time.sleep(.2)
                            after = timer(selector)
                            if after not in [before, "00:01"]:
                                break
                        assert after != before and after != "00:00", (selector, before, after, errors)
                        print(json.dumps({"timer": selector, "before": before, "after": after}, ensure_ascii=False), flush=True)

                    command("Runtime.enable")
                    command("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 1100, "deviceScaleFactor": 1, "mobile": False})
                    command("Page.navigate", {"url": f"http://127.0.0.1:{server.server_port}/frontend/index.html"})
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        if evaluate("document.readyState === 'complete'"):
                            break
                        time.sleep(.1)
                    click("#akari-entry")
                    click("#akari-rules-close")
                    time.sleep(1.2)
                    assert timer("#akari-timer") == "00:00", "未操作前不应计时"
                    click('#akari-board [data-index="0"]')
                    assert_ticks("#akari-timer")
                    shot = command("Page.captureScreenshot", {"format": "png"})
                    (OUTPUT / "akari-live-timer.png").write_bytes(base64.b64decode(shot["data"]))
                    # 通关立即冻结，再等待一秒也不应继续累加。
                    for index in [2, 11, 19, 28, 30, 36, 41, 45, 48, 54, 61, 66, 73, 80, 89, 92, 97]:
                        click(f'#akari-board [data-index="{index}"]')
                    frozen = timer("#akari-timer")
                    time.sleep(1.2)
                    assert timer("#akari-timer") == frozen, "通关后计时应冻结"
                    click("#result-secondary")
                    click("#akari-restart")
                    assert timer("#akari-timer") == "00:00", "重开应归零"
                    click("#akari-back")
                    click("#sudoku-entry")
                    click("#sudoku-rules-close")
                    click('#sudoku-board [data-index="0"]')
                    click('#sudoku-keypad [data-digit="5"]')
                    assert_ticks("#sudoku-timer")
                    click("#sudoku-back")
                    click("#start-button")
                    click("#rules-close")
                    click('#board [data-index="0"]')
                    click("#flag-button")
                    assert_ticks("#timer")
                    assert not errors, errors
                    print("真实计时刷新、通关冻结、重开归零：全部通过", flush=True)
                    command("Browser.close")
                finally:
                    if connection:
                        connection.close()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=5)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
