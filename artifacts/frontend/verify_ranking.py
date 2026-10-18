"""用独立无头 Chrome 和临时 SQLite 验证真实 API/UI、逐关开发验收及手机榜单。

所有账号与成绩仅存在临时数据库，不连接项目 MySQL；不替代真实 Flyway/InnoDB 验收。
截图写入 artifacts/frontend，完整日志由调用方重定向；依赖 requirements-browser.txt。
"""

import base64
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen
from uuid import uuid4

import uvicorn
import websocket
from sqlalchemy import create_engine
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app import main as api
from backend.app.common.config import get_settings
from backend.app.common.database import Base, get_db
from backend.app.common.security import utc_now
from backend.app.models.entities import User
from backend.app.models.entities.ranking import CompletionRecord, LeaderboardEntry

OUTPUT = Path(__file__).resolve().parent
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@compiles(BIGINT, "sqlite")
def sqlite_test_bigint(element, compiler, **kwargs):
    """仅测试进程将 MySQL 会话自增类型映射成 SQLite 的 INTEGER 主键。"""
    return "INTEGER"


def main():
    """启动隔离服务，完成真实浏览器交互，最终只输出验收统计。"""
    checks, errors = [], []
    with tempfile.TemporaryDirectory(prefix="ranking-qa-") as temporary:
        engine = create_engine("sqlite:///" + (Path(temporary) / "qa.sqlite").as_posix(), connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        sessions = sessionmaker(engine, expire_on_commit=False)

        def test_db():
            """每个真实请求独立使用临时数据库会话。"""
            with sessions() as db:
                yield db

        api.app.dependency_overrides[get_db] = test_db
        settings = get_settings()
        previous_dev = settings.dev_quick_complete_enabled
        settings.dev_quick_complete_enabled = True
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(api.app, log_level="error"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        if not server.started:
            raise AssertionError("临时后端未启动")
        process, connection = None, None
        try:
            with (OUTPUT / "ranking-browser.log").open("w", encoding="utf-8") as log:
                profile = Path(temporary) / "chrome"
                process = subprocess.Popen([str(CHROME), "--headless", "--disable-gpu", "--no-first-run",
                    "--disable-background-networking", f"--user-data-dir={profile}", "--remote-debugging-port=0", "about:blank"],
                    stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                deadline = time.monotonic() + 15
                port_file = profile / "DevToolsActivePort"
                while not port_file.exists() and time.monotonic() < deadline:
                    time.sleep(.1)
                debug_port = port_file.read_text().splitlines()[0]
                with urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=5) as response:
                    tab = next(item for item in json.load(response) if item["type"] == "page")
                connection = websocket.create_connection(tab["webSocketDebuggerUrl"], suppress_origin=True, timeout=15)
                serial = 0

                def command(method, params=None):
                    """执行 CDP 命令并收集未处理的页面异常。"""
                    nonlocal serial
                    serial += 1
                    connection.send(json.dumps({"id": serial, "method": method, "params": params or {}}))
                    while True:
                        reply = json.loads(connection.recv())
                        if reply.get("method") == "Runtime.exceptionThrown":
                            errors.append(reply["params"])
                        if reply.get("id") == serial:
                            if "error" in reply:
                                raise AssertionError(reply["error"])
                            return reply.get("result", {})

                def evaluate(expression):
                    """执行真实页面表达式，支持等待网络请求。"""
                    result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
                    if "exceptionDetails" in result:
                        raise AssertionError(result["exceptionDetails"])
                    return result.get("result", {}).get("value")

                def wait(expression):
                    """等待可观察的交互结果，不依赖固定页面加载延迟。"""
                    deadline = time.monotonic() + 12
                    while time.monotonic() < deadline:
                        if evaluate(expression):
                            return
                        time.sleep(.05)
                    details = evaluate("JSON.stringify({auth:document.querySelector('#auth-status')?.textContent,challenge:document.querySelector('#challenge-message')?.textContent})")
                    raise AssertionError("等待失败：" + expression + "；状态：" + str(details))

                def click(selector):
                    """点击页面真实控件，保持 disabled 行为。"""
                    evaluate(f"document.querySelector({json.dumps(selector)}).click()")

                def navigate(filename):
                    """保留同一浏览器会话跨独立页面导航。"""
                    command("Page.navigate", {"url": f"http://127.0.0.1:{port}/{filename}"})
                    wait("document.readyState==='complete' && !!document.querySelector('.auth-open')")

                def shot(name):
                    """保存实际渲染截图供视觉核验。"""
                    result = command("Page.captureScreenshot", {"format": "png"})
                    (OUTPUT / name).write_bytes(base64.b64decode(result["data"]))

                command("Runtime.enable")
                command("Network.enable")
                command("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 960, "deviceScaleFactor": 1, "mobile": False})
                navigate("ranking.html")
                wait("document.querySelector('#ranking-status').textContent.includes('没有记录')")
                assert evaluate("document.querySelector('#ranking-rows').children.length") == 0
                checks.append("未登录空榜与四榜导航")
                navigate("index.html")
                assert evaluate("document.querySelector('#akari-entry').disabled && document.querySelector('#sudoku-entry').disabled")
                click("#start-button")
                wait("document.querySelector('#auth-dialog').open")
                evaluate("document.querySelector('#auth-username').value='验收玩家'; document.querySelector('#auth-password').value='test-secret';")
                click(".auth-submit")
                wait("!document.querySelector('#rules-dialog').classList.contains('hidden')")
                click("#rules-close")
                command("Network.setBlockedURLs", {"urls": ["*api/challenges/*/complete*"]})
                click("#mine-quick")
                wait("!document.querySelector('#save-retry').classList.contains('hidden')")
                assert evaluate("document.querySelector('#result-primary').disabled")
                command("Network.setBlockedURLs", {"urls": []})
                click("#save-retry")
                wait("!document.querySelector('#result-primary').disabled")
                assert evaluate("document.querySelector('#akari-screen').classList.contains('hidden')")
                checks.append("真实注册登录、逐关锁定、通关保存失败重试")
                shot("ranking-dev-completion.png")
                click("#result-primary")
                click("#akari-rules-close")
                click("#akari-quick")
                wait("!document.querySelector('#result-primary').disabled")
                assert evaluate("document.querySelector('#sudoku-screen').classList.contains('hidden')")
                click("#result-primary")
                click("#sudoku-rules-close")
                click("#sudoku-quick")
                wait("!document.querySelector('#result-primary').disabled")
                click("#result-primary")
                wait("!document.querySelector('#settlement-dialog').classList.contains('hidden')")
                assert evaluate("document.querySelector('#settlement-ranking').disabled") is False
                assert evaluate("document.querySelector('#settlement-note').textContent.includes('已保存')")
                shot("ranking-settlement.png")
                checks.append("开发按钮只完成当前关及完整三关结算")
                with sessions() as db:
                    for index in range(25):
                        user = User(username="测试玩家" + str(index), username_key="seed" + str(index), password_hash="not-a-login-account", created_at=utc_now())
                        db.add(user)
                        db.flush()
                        record = CompletionRecord(user_id=user.id, category="total", run_id=str(uuid4()), attempt_id=str(uuid4()), duration_seconds=90 + index,
                                                  mine_seconds=20, akari_seconds=30, sudoku_seconds=40 + index, completed_at=utc_now())
                        db.add(record)
                        db.flush()
                        db.add(LeaderboardEntry(user_id=user.id, category="total", best_record_id=record.id, best_duration_seconds=record.duration_seconds, achieved_at=record.completed_at))
                    db.commit()
                click("#settlement-ranking")
                wait("!!document.querySelector('#ranking-rows') && document.querySelector('#ranking-rows').children.length===20")
                click("#ranking-rows details summary")
                shot("ranking-desktop.png")
                click("#ranking-next")
                wait("document.querySelector('#ranking-page').textContent==='2 / 2'")
                assert evaluate("document.querySelector('#ranking-rows').children.length") == 6
                assert evaluate("document.querySelector('#ranking-rows tr td').textContent") == "21"
                checks.append("总榜快照展开、20人分页与跨页名次")
                command("Emulation.setDeviceMetricsOverride", {"width": 375, "height": 900, "deviceScaleFactor": 1, "mobile": True})
                navigate("ranking.html")
                wait("document.querySelector('#ranking-rows').children.length===20")
                click("#ranking-rows details summary")
                assert evaluate("document.documentElement.scrollWidth <= innerWidth")
                shot("ranking-mobile.png")
                for filename in ["ranking-mine.html", "ranking-akari.html", "ranking-sudoku.html"]:
                    navigate(filename)
                    wait("document.querySelector('#ranking-rows').children.length===1")
                    assert evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert evaluate("document.querySelector('.ranking-tabs [aria-current=page]').getAttribute('href')") == "./" + filename
                shot("ranking-single-mobile.png")
                checks.append("三个独立单项页、登录跨页恢复、375px无横向溢出")
                command("Network.setBlockedURLs", {"urls": ["*api/rankings/*"]})
                navigate("ranking.html")
                wait("!document.querySelector('#ranking-retry').classList.contains('hidden')")
                command("Network.setBlockedURLs", {"urls": []})
                click("#ranking-retry")
                wait("document.querySelector('#ranking-rows').children.length===20")
                checks.append("榜单加载失败与重新加载")
                settings.dev_quick_complete_enabled = False
                navigate("index.html")
                wait("!document.querySelector('.auth-user').classList.contains('hidden')")
                click("#start-button")
                wait("!document.querySelector('#rules-dialog').classList.contains('hidden')")
                assert evaluate("document.querySelector('#mine-quick').classList.contains('hidden')")
                checks.append("开发开关关闭后正常挑战可用且按钮隐藏")
                assert not errors, "页面有未处理异常"
        finally:
            if connection:
                connection.close()
            if process:
                process.terminate()
                process.wait(timeout=10)
            server.should_exit = True
            worker.join(timeout=10)
            listener.close()
            api.app.dependency_overrides.clear()
            settings.dev_quick_complete_enabled = previous_dev
            engine.dispose()
    print(json.dumps({"checks_passed": len(checks), "checks": checks, "uncaught_errors": len(errors)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
