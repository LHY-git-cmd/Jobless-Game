"""用独立无头 Chrome 和临时 SQLite 验证真实 API/UI、独立关卡、单关结算及手机榜单。

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
                    result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": True})
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
                assert evaluate("document.body.dataset.ranking==='mine' && document.querySelectorAll('.ranking-tabs a').length===3")
                assert evaluate("document.body.textContent.includes('三关总榜')") is False
                checks.append("原排行榜入口默认扫雷分榜，导航只保留三个单项榜")

                navigate("index.html")
                assert evaluate("!document.querySelector('#akari-entry').disabled && !document.querySelector('#sudoku-entry').disabled")
                click("#sudoku-entry")
                wait("document.querySelector('#auth-dialog').open")
                evaluate("document.querySelector('#auth-username').value='验收玩家'; document.querySelector('#auth-password').value='test-secret';")
                click(".auth-submit")
                wait("!document.querySelector('#sudoku-rules-dialog').classList.contains('hidden')")
                assert evaluate("document.querySelector('#sudoku-timer').textContent") == "00:00"
                click("#sudoku-rules-close")
                click("#sudoku-back")
                click("#akari-entry")
                wait("!document.querySelector('#akari-rules-dialog').classList.contains('hidden')")
                click("#akari-rules-close")
                click("#akari-board button[data-index='0']")
                click("#akari-back")
                checks.append("未登录可任选关卡，登录后直接进入数独和照明")
                click("#start-button")
                wait("!document.querySelector('#rules-dialog').classList.contains('hidden')")
                click("#rules-close")
                click("#restart-button")
                wait("!document.querySelector('#rules-dialog').classList.contains('hidden') && !document.querySelector('#rules-close').disabled")
                click("#rules-close")
                click("#back-button")
                click("#akari-entry")
                wait("!document.querySelector('#akari-screen').classList.contains('hidden')")
                assert evaluate("document.querySelector('#akari-board button[data-index=\"0\"]').classList.contains('bulb')")
                checks.append("重开扫雷保留照明原棋盘")
                click("#akari-back")
                click("#start-button")
                wait("!document.querySelector('#game-screen').classList.contains('hidden')")
                command("Network.setBlockedURLs", {"urls": ["*api/challenges/*/complete*"]})
                click("#mine-quick")
                wait("!document.querySelector('#save-retry').classList.contains('hidden')")
                assert evaluate("document.querySelector('#result-primary').disabled")
                command("Network.setBlockedURLs", {"urls": []})
                click("#save-retry")
                wait("!document.querySelector('#result-dialog').classList.contains('hidden') && !document.querySelector('#result-primary').disabled")
                click("#result-primary")
                wait("!document.querySelector('#settlement-dialog').classList.contains('hidden')")
                assert evaluate("document.querySelector('#settlement-title').textContent") == "扫雷通关结算"
                assert evaluate("document.querySelector('#settlement-total')===null && document.querySelector('#settlement-mine')===null")
                shot("ranking-settlement.png")
                checks.append("保存失败可重试，扫雷独立结算且无整轮汇总")
                click("#settlement-home")
                wait("document.querySelector('#records-best-time').textContent!==''")
                assert evaluate("document.querySelectorAll('.records-tabs button').length") == 3
                click("#sudoku-entry")
                wait("!document.querySelector('#sudoku-screen').classList.contains('hidden')")
                click("#sudoku-quick")
                wait("!document.querySelector('#result-dialog').classList.contains('hidden') && !document.querySelector('#result-primary').disabled")
                click("#result-primary")
                wait("document.querySelector('#settlement-title').textContent==='数独通关结算'")
                click("#settlement-home")
                click("#akari-entry")
                wait("!document.querySelector('#akari-screen').classList.contains('hidden')")
                click("#akari-quick")
                wait("!document.querySelector('#result-dialog').classList.contains('hidden') && !document.querySelector('#result-primary').disabled")
                click("#result-primary")
                wait("document.querySelector('#settlement-title').textContent==='照明通关结算'")
                click("#settlement-home")
                assert evaluate("Array.from(document.querySelectorAll('.level-arrow')).every(el=>el.textContent==='已通关')")
                assert evaluate("document.querySelector('#challenge-action-label').textContent") == "选择你的挑战"
                checks.append("任意顺序通关均单关结算，全部完成后仍保留结果")
                click("#start-button")
                wait("!document.querySelector('#result-dialog').classList.contains('hidden')")
                click("#result-secondary")
                click("#restart-button")
                wait("!document.querySelector('#rules-dialog').classList.contains('hidden')")
                click("#back-button")
                assert evaluate("document.querySelector('#akari-entry-status').textContent==='已通关' && document.querySelector('#sudoku-entry-status').textContent==='已通关'")
                navigate("index.html")
                click("#sudoku-entry")
                wait("!document.querySelector('#result-dialog').classList.contains('hidden')")
                checks.append("全通关后可单关重开，刷新仍保留其他关卡成绩")
                assert evaluate("(async()=>{const r=await fetch('/api/rankings/total');return r.status})()") == 422
                assert evaluate("(async()=>{const r=await fetch('/api/records/me?category=total');return r.status})()") == 422
                with sessions() as db:
                    assert db.query(CompletionRecord).filter_by(category="total").count() == 0
                    assert db.query(LeaderboardEntry).filter_by(category="total").count() == 0
                    # 分页仅写入临时验收库的扫雷记录。
                    for index in range(25):
                        user = User(username="测试玩家" + str(index), username_key="seed" + str(index), password_hash="not-a-login-account", created_at=utc_now())
                        db.add(user)
                        db.flush()
                        record = CompletionRecord(user_id=user.id, category="mine", run_id=str(uuid4()), attempt_id=str(uuid4()), duration_seconds=90 + index, completed_at=utc_now())
                        db.add(record)
                        db.flush()
                        db.add(LeaderboardEntry(user_id=user.id, category="mine", best_record_id=record.id, best_duration_seconds=record.duration_seconds, achieved_at=record.completed_at))
                    db.commit()
                checks.append("总榜和整轮记录接口停用，完成三关不产生总榜数据库记录")
                click("#result-primary")
                click("#settlement-ranking")
                wait("location.pathname.endsWith('ranking-sudoku.html') && document.querySelector('#ranking-rows')?.children.length===1")
                checks.append("单关结算跳转对应分榜")
                navigate("ranking.html")
                wait("document.querySelector('#ranking-rows').children.length===20")
                shot("ranking-desktop.png")
                click("#ranking-next")
                wait("document.querySelector('#ranking-page').textContent==='2 / 2'")
                assert evaluate("document.querySelector('#ranking-rows').children.length") == 6
                assert evaluate("document.querySelector('#ranking-rows tr td').textContent") == "21"
                checks.append("单项榜20人分页和跨页名次")
                for width in [375, 320]:
                    command("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": True})
                    for filename in ["ranking.html", "ranking-mine.html", "ranking-akari.html", "ranking-sudoku.html"]:
                        navigate(filename)
                        wait("document.querySelector('#ranking-rows').children.length>0")
                        assert evaluate("document.documentElement.scrollWidth <= innerWidth")
                        assert evaluate("document.querySelectorAll('.ranking-tabs a').length") == 3
                    if width == 375:
                        shot("ranking-single-mobile.png")
                    navigate("index.html")
                    # 从榜单返回可能恢复数独结果；先返回首页再检查实际可见的个人面板。
                    evaluate("document.querySelector('#sudoku-back').click()")
                    wait("!document.querySelector('#landing').classList.contains('hidden')")
                    wait("document.querySelectorAll('.records-tabs button').length===3")
                    evaluate("document.querySelector('#personal-records').scrollIntoView({block:'start'})")
                    assert evaluate("document.documentElement.scrollWidth <= innerWidth")
                    if width == 375:
                        shot("personal-records-mobile.png")
                checks.append("375/320px三个榜单与个人记录无横向溢出")
                command("Network.setBlockedURLs", {"urls": ["*api/rankings/*"]})
                navigate("ranking.html")
                wait("!document.querySelector('#ranking-retry').classList.contains('hidden')")
                command("Network.setBlockedURLs", {"urls": []})
                click("#ranking-retry")
                wait("document.querySelector('#ranking-rows').children.length===20")
                checks.append("榜单加载失败后可重试")
                navigate("index.html")
                click(".auth-logout")
                wait("!document.querySelector('#records-login').classList.contains('hidden')")
                assert evaluate("document.querySelector('#records-best-time').textContent") == ""
                assert evaluate("document.querySelector('#records-list').children.length") == 0
                checks.append("退出账号立即清空个人记录")
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
