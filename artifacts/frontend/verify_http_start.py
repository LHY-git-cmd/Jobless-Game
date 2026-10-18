"""作用：在真正非安全的 HTTP 域名页面验证登录、开局失败重试及重新开始。

Chrome 仅将 jobless-http.test 解析到独立本机测试服务，不修改可信来源设置。
测试库为临时 SQLite，不连接服务器或本机 MySQL；只输出统计及必要失败信息。
"""

import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from urllib.request import urlopen
from uuid import uuid4

import verify_ranking as qa


def main():
    """保留浏览器原生 HTTP 限制，通过实际页面操作验证 UUID 兼容分支。"""
    checks, errors, responses = [], [], []
    with tempfile.TemporaryDirectory(prefix="http-start-qa-") as temporary:
        engine = qa.create_engine("sqlite:///" + (Path(temporary) / "qa.sqlite").as_posix(),
                                  connect_args={"check_same_thread": False})
        qa.Base.metadata.create_all(engine)
        sessions = qa.sessionmaker(engine, expire_on_commit=False)

        def test_db():
            """所有浏览器请求只连接本次临时数据库。"""
            with sessions() as db:
                yield db

        qa.api.app.dependency_overrides[qa.get_db] = test_db
        settings = qa.get_settings()
        previous = settings.dev_quick_complete_enabled, settings.cookie_secure
        settings.dev_quick_complete_enabled = settings.cookie_secure = False
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = qa.uvicorn.Server(qa.uvicorn.Config(qa.api.app, log_level="error"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        process = connection = None
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(.05)
            assert server.started, "临时服务未启动"
            with (qa.OUTPUT / "http-start-browser.log").open("w", encoding="utf-8") as log:
                profile = Path(temporary) / "chrome"
                process = subprocess.Popen([
                    str(qa.CHROME), "--headless", "--disable-gpu", "--no-first-run",
                    "--disable-background-networking", "--no-proxy-server",
                    "--host-resolver-rules=MAP jobless-http.test 127.0.0.1",
                    f"--user-data-dir={profile}", "--remote-debugging-port=0", "about:blank",
                ], stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                port_file = profile / "DevToolsActivePort"
                deadline = time.monotonic() + 15
                while not port_file.exists() and time.monotonic() < deadline:
                    time.sleep(.1)
                debug_port = port_file.read_text().splitlines()[0]
                with urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=5) as result:
                    tab = next(item for item in json.load(result) if item["type"] == "page")
                connection = qa.websocket.create_connection(tab["webSocketDebuggerUrl"], suppress_origin=True, timeout=15)
                serial = 0

                def command(method, params=None):
                    """执行 CDP 命令，同时记录页面异常和挑战接口状态，不记录凭据。"""
                    nonlocal serial
                    serial += 1
                    connection.send(json.dumps({"id": serial, "method": method, "params": params or {}}))
                    while True:
                        reply = json.loads(connection.recv())
                        if reply.get("method") == "Runtime.exceptionThrown":
                            errors.append(reply["params"])
                        if reply.get("method") == "Network.responseReceived":
                            response = reply["params"]["response"]
                            if "/api/challenges/" in response["url"]:
                                responses.append((response["url"], response["status"]))
                        if reply.get("id") == serial:
                            assert "error" not in reply, reply.get("error")
                            return reply.get("result", {})

                def evaluate(expression):
                    """在实际页面执行表达式，并等待异步结果。"""
                    result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                           "awaitPromise": True, "userGesture": True})
                    assert "exceptionDetails" not in result, result.get("exceptionDetails")
                    return result.get("result", {}).get("value")

                def wait(expression):
                    """等待页面的实际状态，超时只报告控件提示。"""
                    deadline = time.monotonic() + 12
                    while time.monotonic() < deadline:
                        if evaluate(expression):
                            return
                        time.sleep(.05)
                    raise AssertionError("等待失败：" + expression + "；提示：" + str(evaluate(
                        "document.querySelector('#challenge-message')?.textContent")))

                command("Runtime.enable")
                command("Network.enable")
                command("Page.navigate", {"url": f"http://jobless-http.test:{port}/index.html"})
                wait("document.readyState==='complete' && !!document.querySelector('.auth-open')")
                assert evaluate("isSecureContext") is False
                assert evaluate("typeof crypto.randomUUID") == "undefined"
                assert evaluate("typeof crypto.getRandomValues") == "function"
                checks.append("原生非安全 HTTP 环境且 randomUUID 不可用")
                command("Network.setBlockedURLs", {"urls": ["*/api/challenges/start"]})
                evaluate("document.querySelector('#start-button').click()")
                wait("document.querySelector('#auth-dialog').open")
                name = "qa" + uuid4().hex[:8]
                evaluate("document.querySelector('#auth-username').value=" + json.dumps(name) +
                         ";document.querySelector('#auth-password').value='qa-http-password';document.querySelector('.auth-submit').click()")
                wait("!document.querySelector('#start-button').disabled && document.querySelector('#challenge-message').textContent.includes('连接失败')")
                assert "randomUUID" not in evaluate("document.querySelector('#challenge-message').textContent")
                command("Network.setBlockedURLs", {"urls": []})
                evaluate("document.querySelector('#start-button').click()")
                wait("!document.querySelector('#rules-dialog').classList.contains('hidden')")
                assert any(url.endswith("/start") and status == 200 for url, status in responses)
                checks.append("真实登录、开局失败提示及重试后进入扫雷规则")
                evaluate("document.querySelector('#rules-close').click();document.querySelector('#restart-button').click()")
                wait("document.querySelector('#challenge-status').classList.contains('hidden') && document.querySelector('#board').children.length===100")
                assert any(url.endswith("/restart") and status == 200 for url, status in responses)
                checks.append("重新开始通过实际 API 并显示 100 格棋盘")
                assert not errors, "页面存在未处理异常"
                checks.append("无未处理页面异常")
        finally:
            if connection:
                connection.close()
            if process:
                process.terminate()
                process.wait(timeout=10)
            server.should_exit = True
            worker.join(timeout=10)
            listener.close()
            qa.api.app.dependency_overrides.clear()
            settings.dev_quick_complete_enabled, settings.cookie_secure = previous
            engine.dispose()
    print(json.dumps({"checks_passed": len(checks), "checks": checks, "uncaught_errors": len(errors)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
