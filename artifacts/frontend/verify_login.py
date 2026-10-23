"""用独立 Chrome 验证真实登录 UI、会话接口与游戏续接，并保存桌面/手机截图。

本脚本将数据库依赖替换为内存测试替身；API、Argon2id 和前端代码均为真实实现。
结果仅证明交互与业务分支，不替代真实 MySQL/Flyway 或生产资源验收。
这是自由选择关卡阶段的历史脚本，未适配后续挑战接口与逐关解锁；
当前可执行浏览器验收请使用同目录 verify_ranking.py。
"""

import base64
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from urllib.request import urlopen
import sys

import uvicorn
import websocket

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app import main as api
from backend.app.common.database import get_db
from backend.app.services import auth_service
from backend.app.services.login_limiter import LoginRateLimiter
from backend.app.models.entities import AuthSession, User

CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
OUTPUT = Path(__file__).resolve().parent


class MemoryDatabase:
    """仅供浏览器验证的数据库测试替身，明确不执行 SQL。"""

    users = {}
    sessions = {}

    def __init__(self):
        self.pending = []

    def scalar(self, statement):
        """按 SQLAlchemy 查询参数定位测试账号或会话。"""
        value = next(iter(statement.compile().params.values()))
        model = statement.column_descriptions[0]["entity"]
        return self.users.get(value) if model is User else self.sessions.get(value)

    def add(self, entity):
        """暂存实体；commit 后才成为可读取的测试数据。"""
        self.pending.append(entity)

    def flush(self):
        """模拟数据库产生自增主键。"""
        for entity in self.pending:
            if isinstance(entity, User):
                entity.id = len(self.users) + 1

    def commit(self):
        """提交实体并连接会话的用户关系。"""
        for entity in self.pending:
            if isinstance(entity, User):
                self.users[entity.username_key] = entity
            else:
                entity.user = next(user for user in self.users.values() if user.id == entity.user_id)
                self.sessions[entity.token_hash] = entity
        self.pending.clear()

    def rollback(self):
        """清理测试事务的暂存值。"""
        self.pending.clear()

    def delete(self, entity):
        """模拟过期会话删除。"""
        self.sessions.pop(entity.token_hash, None)

    def execute(self, statement):
        """模拟 logout 按 token 摘要删除当前会话。"""
        value = next(iter(statement.compile().params.values()))
        self.sessions.pop(value, None)

    def close(self):
        """请求结束后丢弃未提交的测试值。"""
        self.rollback()


def fake_db():
    """每个请求使用独立工作对象，测试数据只保存在脚本进程内。"""
    db = MemoryDatabase()
    try:
        yield db
    finally:
        db.close()


def main():
    """通过真实点击、键盘和跨页导航验证登录，并输出精简结果。"""
    api.app.dependency_overrides[get_db] = fake_db
    auth_service.rate_limiter = LoginRateLimiter(100, 60)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, log_level="critical", access_log=False))
    worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    worker.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(.05)
    assert server.started, "预览 API 未启动"
    checks = []
    errors = []
    try:
        with tempfile.TemporaryDirectory(prefix="login-qa-") as profile:
            with (OUTPUT / "login-browser.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([
                    str(CHROME), "--headless", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                    f"--user-data-dir={profile}", "--remote-debugging-port=0", "about:blank",
                ], stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
                connection = None
                try:
                    port_file = Path(profile) / "DevToolsActivePort"
                    deadline = time.monotonic() + 15
                    while not port_file.exists() and time.monotonic() < deadline:
                        time.sleep(.1)
                    debug_port = port_file.read_text().splitlines()[0]
                    with urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=5) as response:
                        page = next(tab for tab in json.load(response) if tab["type"] == "page")
                    connection = websocket.create_connection(page["webSocketDebuggerUrl"], suppress_origin=True, timeout=15)
                    serial = 0

                    def command(method, params=None):
                        """发送单个 CDP 命令并收集浏览器未处理异常。"""
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
                        """读取页面状态，支持 await 真实 API 请求。"""
                        result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
                        if "exceptionDetails" in result:
                            raise AssertionError(result["exceptionDetails"])
                        return result.get("result", {}).get("value")

                    def wait(expression):
                        """等待 observable UI 状态，超时给出失败条件。"""
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            if evaluate(expression):
                                return
                            time.sleep(.05)
                        raise AssertionError(expression)

                    def click(selector):
                        """调用真实按钮事件。"""
                        evaluate(f"document.querySelector({json.dumps(selector)}).click()")

                    def fill(selector, value):
                        """模拟输入事件，保持密码原始值。"""
                        evaluate(f"(() => {{ const input=document.querySelector({json.dumps(selector)}); input.value={json.dumps(value)}; input.dispatchEvent(new Event('input', {{bubbles:true}})); }})()")

                    def navigate(page="index.html"):
                        """使用同一浏览器 Cookie 在三页间切换。"""
                        command("Page.navigate", {"url": f"http://127.0.0.1:{port}/{page}"})
                        wait("document.readyState === 'complete' && !!document.querySelector('.auth-open')")

                    def submit(name="Player1", password=" Abc12 "):
                        """提交共享登录表单，不直接写登录状态。"""
                        fill("#auth-username", name)
                        fill("#auth-password", password)
                        click(".auth-submit")

                    def shot(name):
                        """保存当前实际渲染的截图。"""
                        value = command("Page.captureScreenshot", {"format": "png"})
                        (OUTPUT / name).write_bytes(base64.b64decode(value["data"]))

                    command("Runtime.enable")
                    command("Network.enable")
                    command("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})
                    navigate()
                    # 第一关取消不进入游戏，焦点返回触发按钮。
                    evaluate("document.querySelector('#start-button').focus()")
                    click("#start-button")
                    wait("document.querySelector('#auth-dialog').open")
                    assert evaluate("document.querySelector('#landing').classList.contains('hidden')") is False
                    shot("login-desktop.png")
                    command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27, "nativeVirtualKeyCode": 27})
                    command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
                    wait("!document.querySelector('#auth-dialog').open")
                    assert evaluate("document.activeElement.id") == "start-button"
                    checks.append("取消不进入关卡及焦点恢复")
                    # 首次自动注册后续接扫雷规则，尚未操作时仍为 00:00。
                    click("#start-button")
                    wait("document.querySelector('#auth-dialog').open")
                    submit()
                    wait("!document.querySelector('#rules-dialog').classList.contains('hidden')")
                    assert evaluate("document.querySelector('#timer').textContent") == "00:00"
                    click("#rules-close")
                    click("#back-button")
                    click(".auth-logout")
                    wait("!document.querySelector('.auth-open').classList.contains('hidden')")
                    checks.append("首次注册、扫雷续接规则且计时未启动、注销")
                    # 第二关：用户名大小写折叠，错误密码不会注册新账号。
                    click("#akari-entry")
                    wait("document.querySelector('#auth-dialog').open")
                    submit("PLAYER1", "wrong1")
                    wait("document.querySelector('#auth-status').textContent.includes('错误')")
                    assert evaluate("document.querySelector('#auth-username').value") == "PLAYER1"
                    assert evaluate("document.querySelector('#landing').classList.contains('hidden')") is False
                    submit("player1")
                    wait("!document.querySelector('#akari-rules-dialog').classList.contains('hidden')")
                    click("#akari-rules-close")
                    click("#akari-back")
                    click(".auth-logout")
                    wait("!document.querySelector('.auth-open').classList.contains('hidden')")
                    checks.append("错误密码、大小写同账号、照明原目标续接")
                    # 第三关也必须先登录，再显示对应规则。
                    click("#sudoku-entry")
                    wait("document.querySelector('#auth-dialog').open")
                    submit()
                    wait("!document.querySelector('#sudoku-rules-dialog').classList.contains('hidden')")
                    click("#sudoku-rules-close")
                    click("#sudoku-back")
                    checks.append("数独拦截与原目标续接")
                    # 三页共用 Cookie，刷新与导航恢复首次显示名。
                    for destination in ["index.html", "ranking.html", "forum.html"]:
                        navigate(destination)
                        wait("document.querySelector('.auth-username').textContent === 'Player1'")
                    checks.append("刷新、三页会话恢复及首次显示名保留")
                    click(".auth-logout")
                    wait("!document.querySelector('.auth-open').classList.contains('hidden')")
                    click(".auth-open")
                    wait("document.querySelector('#auth-dialog').open")
                    submit("bad_name", "short")
                    assert evaluate("document.querySelector('#auth-username-error').textContent.length > 0")
                    assert evaluate("document.querySelector('#auth-password-error').textContent.length > 0")
                    # Tab 边界与移动端截图；无横向溢出，短屏能滚动到底。
                    evaluate("document.querySelector('.auth-close').focus()")
                    command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Tab", "code": "Tab", "modifiers": 8, "windowsVirtualKeyCode": 9})
                    assert evaluate("document.activeElement.classList.contains('auth-submit')")
                    command("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
                    fill("#auth-username", "中文123456789")
                    fill("#auth-password", "")
                    shot("login-mobile.png")
                    assert evaluate("document.documentElement.scrollWidth <= innerWidth")
                    command("Emulation.setDeviceMetricsOverride", {"width": 320, "height": 360, "deviceScaleFactor": 1, "mobile": True})
                    assert evaluate("document.querySelector('#auth-dialog').scrollHeight > document.querySelector('#auth-dialog').clientHeight")
                    evaluate("document.querySelector('.auth-submit').focus()")
                    wait("document.activeElement.getBoundingClientRect().bottom <= innerHeight")
                    checks.append("字段提示、Tab 循环、手机与短屏滚动")
                    # 阻断真实请求，检查网络失败不伪造成功。
                    command("Network.setBlockedURLs", {"urls": ["*/api/auth/login"]})
                    submit()
                    wait("document.querySelector('#auth-status').textContent.includes('连接失败')")
                    assert evaluate("document.querySelector('#auth-dialog').open")
                    command("Network.setBlockedURLs", {"urls": []})
                    submit()
                    wait("!document.querySelector('#auth-dialog').open")
                    assert evaluate("location.pathname") == "/forum.html"
                    checks.append("网络失败保留表单、重试成功、顶部登录停留当前页")
                    assert len(MemoryDatabase.users) == 1, "不应新建同名账号"
                    assert not errors, errors
                    print(json.dumps({"passed": len(checks), "failed": 0, "database": "测试替身，不代表 MySQL/Flyway 验收", "checks": checks}, ensure_ascii=False))
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
        server.should_exit = True
        worker.join(timeout=5)
        listener.close()
        api.app.dependency_overrides.clear()


if __name__ == "__main__":
    main()
