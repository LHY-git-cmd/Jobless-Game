"""用独立 Chrome 配置和本机模拟接口验证三关刷新、浏览器重启与离开期间计时。

只访问临时本机服务器，不连接真实账号或数据库；游戏脚本与浏览器存储使用真实实现。
"""

from contextlib import contextmanager
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import uuid4

import websocket

ROOT = Path(__file__).resolve().parents[2]
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
STATE = None
STARTS = 0


class Handler(SimpleHTTPRequestHandler):
    """提供真实静态前端和固定测试账号的最小挑战接口。"""

    def respond(self, data):
        """返回 JSON，禁止缓存模拟的账号和轮次信息。"""
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """读取测试账号、开关或现有轮次，其余请求使用原始静态文件。"""
        path = urlparse(self.path).path
        if path == "/api/auth/me":
            return self.respond({"id": 1, "username": "恢复测试"})
        if path == "/api/challenges/config":
            return self.respond({"quick_complete_enabled": True})
        if path == "/api/records/me":
            return self.respond({"category": "total", "best": None, "recent": []})
        if STATE and path == f"/api/challenges/{STATE['run_id']}":
            return self.respond(STATE)
        return super().do_GET()

    def do_POST(self):
        """模拟服务端建轮、逐关保存和重开，不替换前端游戏或计时逻辑。"""
        global STATE, STARTS
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        path = urlparse(self.path).path
        if path == "/api/challenges/start":
            STARTS += 1
            STATE = {"run_id": str(uuid4()), "revision": 0, "total_recorded": False,
                     "levels": [{"attempt_id": str(uuid4()), "seconds": None} for _ in range(3)]}
        elif path.endswith("/complete"):
            index = ["mine", "akari", "sudoku"].index(body["category"])
            STATE["levels"][index]["seconds"] = body["duration_seconds"]
            STATE["total_recorded"] = all(level["seconds"] is not None for level in STATE["levels"])
        elif path.endswith("/restart"):
            index = ["mine", "akari", "sudoku"].index(body["category"])
            STATE["revision"] += 1
            STATE["levels"][index:] = [{"attempt_id": str(uuid4()), "seconds": None} for _ in range(3 - index)]
        else:
            raise AssertionError(path)
        self.respond(STATE)

    def log_message(self, *_):
        """省略常规 HTTP 访问日志，只输出验收结果。"""


@contextmanager
def browser(profile, log):
    """启动独立无头浏览器，允许同一配置目录被关闭后重新打开。"""
    port_file = Path(profile) / "DevToolsActivePort"
    port_file.unlink(missing_ok=True)
    process = subprocess.Popen([
        str(CHROME), "--headless", "--disable-gpu", "--no-first-run", "--disable-background-networking",
        f"--user-data-dir={profile}", "--remote-debugging-port=0", "about:blank",
    ], stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    connection = None
    try:
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
            """发送 CDP 命令并记录真实页面未捕获的脚本异常。"""
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
            """运行页面断言，不修改时间或直接写入棋局存档。"""
            result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
            if "exceptionDetails" in result:
                raise RuntimeError(result["exceptionDetails"])
            return result.get("result", {}).get("value")

        command("Runtime.enable")
        yield command, evaluate
        assert not errors, errors
    finally:
        if connection:
            # 正常关闭浏览器会刷新存储进程的磁盘缓冲，模拟玩家误关浏览器窗口。
            try:
                command("Browser.close")
            except (OSError, websocket.WebSocketException):
                pass
            connection.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)


def wait_for(evaluate, expression):
    """等待真实页面完成登录恢复或异步成绩保存，超时只报告条件。"""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError((expression, evaluate("({status: document.getElementById('challenge-message')?.textContent, user: document.querySelector('.auth-user')?.textContent, storage: Object.keys(localStorage).map(k => [k, JSON.parse(localStorage.getItem(k)).atHome])})")))


def main():
    """验收真实刷新、返回首页、进程退出重启及三关计时恢复。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/frontend/index.html"
    try:
        with tempfile.TemporaryDirectory(prefix="progress-qa-") as profile, (ROOT / "artifacts/frontend/progress-browser.log").open("w") as log:
            with browser(profile, log) as (command, evaluate):
                command("Page.navigate", {"url": url})
                wait_for(evaluate, "document.querySelector('.auth-user')?.textContent === '恢复测试'")
                evaluate("document.getElementById('start-button').click()")
                wait_for(evaluate, "document.querySelectorAll('#board button').length === 100")
                evaluate("document.getElementById('rules-close').click(); document.querySelector('#board button').click(); document.getElementById('flag-button').click()")
                before = evaluate("[...document.querySelectorAll('#board button')].map(c => c.getAttribute('aria-label'))")
                time.sleep(1.1)
                command("Page.reload")
                wait_for(evaluate, "document.querySelectorAll('#board button').length === 100")
                assert evaluate("[...document.querySelectorAll('#board button')].map(c => c.getAttribute('aria-label'))") == before
                evaluate("document.getElementById('back-button').click()")
                command("Page.reload")
                wait_for(evaluate, "document.querySelector('.auth-user')?.textContent === '恢复测试'")
                assert evaluate("!document.getElementById('landing').classList.contains('hidden')")
                evaluate("document.getElementById('start-button').click()")
                wait_for(evaluate, "document.querySelectorAll('#board button').length === 100")
            time.sleep(2)
            with browser(profile, log) as (command, evaluate):
                command("Page.navigate", {"url": url})
                wait_for(evaluate, "document.querySelectorAll('#board button').length === 100")
                assert evaluate("[...document.querySelectorAll('#board button')].map(c => c.getAttribute('aria-label'))") == before
                assert evaluate("document.getElementById('timer').textContent") >= "00:03"
                assert STARTS == 1, "续玩不能创建新轮次"
                for quick, screen, action, board, timer in [
                    ("mine-quick", "akari-screen", "document.querySelector('#akari-board button').click()", "akari-board", "akari-timer"),
                    ("akari-quick", "sudoku-screen", "document.querySelector('#sudoku-board [data-index=\"0\"]').click(); document.querySelector('#sudoku-keypad [data-digit=\"5\"]').click()", "sudoku-board", "sudoku-timer"),
                ]:
                    wait_for(evaluate, f"!document.getElementById('{quick}').disabled")
                    evaluate(f"document.getElementById('{quick}').click()")
                    wait_for(evaluate, "!document.getElementById('result-dialog').classList.contains('hidden') && !document.getElementById('result-primary').disabled")
                    evaluate("document.getElementById('result-primary').click()")
                    wait_for(evaluate, f"!document.getElementById('{screen}').classList.contains('hidden')")
                    evaluate("['rules-close','akari-rules-close','sudoku-rules-close'].forEach(id => document.getElementById(id).click())")
                    evaluate(action)
                    cells = evaluate(f"document.getElementById('{board}').innerHTML")
                    time.sleep(1.1)
                    command("Page.reload")
                    wait_for(evaluate, f"document.querySelectorAll('#{board} button').length > 0")
                    assert evaluate(f"document.getElementById('{board}').innerHTML") == cells
                    assert evaluate(f"document.getElementById('{timer}').textContent") != "00:00"
                assert STARTS == 1
        print("浏览器验收：三关刷新、返回首页续玩、浏览器重启及离开计时均通过。")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
