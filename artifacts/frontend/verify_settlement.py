"""用独立无头浏览器验证真实三关通关到结算的交互，并保存桌面/手机截图。

只访问本机临时服务，不修改用户当前棋局。通过点击真实棋盘通关，
仅在验证页面中固定随机数与时钟，使各关用时可以准确断言。
"""

import functools
from http.server import ThreadingHTTPServer
import json
import re
import base64
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
import websocket

from verify_akari_completion import Handler, ROOT, OUTPUT, CHROME


class SettlementHandler(Handler):
    """给临时验证页面注入模拟点击，其余路径仍提供真实项目文件。"""
    def do_GET(self):
        request = urlparse(self.path)
        if request.path != "/__qa/settlement":
            return super().do_GET()
        stage = parse_qs(request.query).get("stage", ["settlement"])[0]
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="/frontend/">')
        # 原页面脚本由验证脚本顺序加载，确保在游戏创建之前设置测试时钟。
        html = re.sub(r'<script type="module" src="\./src/main\.js(?:\?[^"]*)?"></script>', "", html)
        script = r"""
        <script type="module">
          let now = 100000;
          const originalNow = Date.now;
          const originalRandom = Math.random;
          Date.now = () => now;
          Math.random = () => 0;
          await import('/frontend/src/main.js');
          const { SUDOKU_PUZZLE, SUDOKU_SOLUTION } = await import('/frontend/src/sudoku.js');
          const stage = STAGE;
          const $ = id => document.getElementById(id);
          const clickCell = (board, index) => $(board).querySelector(`[data-index="${index}"]`).click();
          const visible = id => !$(id).classList.contains('hidden');
          if (stage !== 'skipped') {
            $('start-button').click();
            now += 50000;
            $('rules-close').click();
            clickCell('board', 0);
            $('flag-button').click();
            now += 65000;
            clickCell('board', 99);
            $('reveal-button').click();
            now += 60000;
            $('result-primary').click();
            $('akari-rules-close').click();
            const bulbs = [0,2,11,19,28,30,36,41,45,48,54,61,66,73,80,89,92,97];
            clickCell('akari-board', bulbs[0]);
            now += 130000;
            for (const index of bulbs.slice(1)) clickCell('akari-board', index);
            now += 60000;
            $('result-primary').click();
          } else {
            $('sudoku-entry').click();
          }
          $('sudoku-rules-close').click();
          let first = true;
          for (let index = 0; index < 81; index++) {
            if (SUDOKU_PUZZLE[index] !== '0') continue;
            clickCell('sudoku-board', index);
            $('sudoku-keypad').querySelector(`[data-digit="${SUDOKU_SOLUTION[index]}"]`).click();
            if (first) { now += 245000; first = false; }
          }
          const congratulation = visible('result-dialog') && $('result-title').textContent.includes('恭喜');
          const delayedSettlement = !visible('settlement-dialog');
          now += 90000;
          if (stage !== 'congratulations') $('result-primary').click();
          const status = {
            stage, congratulation, delayedSettlement,
            settlement: visible('settlement-dialog'),
            times: ['mine','akari','sudoku'].map(name => $('settlement-' + name).textContent),
            total: $('settlement-total').textContent,
            rankingDisabled: $('settlement-ranking').disabled,
            noOverflow: document.documentElement.scrollWidth === document.documentElement.clientWidth,
            viewport: innerWidth,
            cardFits: (() => {
              const card = document.querySelector('#settlement-dialog .dialog-card');
              const bounds = card.getBoundingClientRect();
              return bounds.left >= 0 && bounds.right <= innerWidth && card.scrollWidth <= card.clientWidth;
            })(),
            ordered: ['mine','akari','sudoku'].map(name => $('settlement-' + name).getBoundingClientRect().top)
          };
          Date.now = originalNow;
          Math.random = originalRandom;
          document.body.dataset.qa = JSON.stringify(status);
          document.title = 'Settlement QA complete';
        </script>
        """.replace("STAGE", json.dumps(stage))
        body = html.replace("</body>", script + "</body>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    """验证祝贺先出现、结算顺序/合计、未挑战标记及手机页面不横向溢出。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SettlementHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="settlement-qa-") as profile:
            with (OUTPUT / "settlement-browser.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([
                    str(CHROME), "--headless", "--disable-gpu", "--no-first-run",
                    "--disable-background-networking", f"--user-data-dir={profile}",
                    "--remote-debugging-port=0", "about:blank",
                ], stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
                connection = None
                try:
                    # 浏览器普通窗口有最小宽度，用设备视口覆写才能验证真实手机尺寸。
                    from pathlib import Path
                    port_file = Path(profile) / "DevToolsActivePort"
                    deadline = time.monotonic() + 15
                    while not port_file.exists() and time.monotonic() < deadline:
                        time.sleep(.1)
                    port = port_file.read_text().splitlines()[0]
                    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                        tabs = json.load(response)
                    page = next(tab for tab in tabs if tab["type"] == "page")
                    connection = websocket.create_connection(page["webSocketDebuggerUrl"], suppress_origin=True, timeout=10)
                    serial = 0

                    def command(method, params=None):
                        nonlocal serial
                        serial += 1
                        connection.send(json.dumps({"id": serial, "method": method, "params": params or {}}))
                        while True:
                            reply = json.loads(connection.recv())
                            if reply.get("id") != serial:
                                continue
                            if "error" in reply:
                                raise RuntimeError(reply["error"])
                            return reply.get("result", {})

                    for stage, width in [("congratulations", 1280), ("settlement", 1280), ("settlement", 390), ("skipped", 320)]:
                        command("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 600})
                        command("Page.navigate", {"url": f"http://127.0.0.1:{server.server_port}/__qa/settlement?stage={stage}"})
                        deadline = time.monotonic() + 15
                        status = None
                        while time.monotonic() < deadline:
                            evaluated = command("Runtime.evaluate", {"expression": "document.body?.dataset.qa", "returnByValue": True})
                            value = evaluated.get("result", {}).get("value")
                            if value:
                                candidate = json.loads(value)
                                if candidate["stage"] == stage and candidate["viewport"] == width:
                                    status = candidate
                                    break
                            time.sleep(.05)
                        assert status, f"未取得 {stage} {width}px 的验证结果"
                        assert status["congratulation"] and status["delayedSettlement"], status
                        assert status["noOverflow"] and status["rankingDisabled"], status
                        if stage != "congratulations":
                            assert status["cardFits"] and status["settlement"], status
                            assert status["ordered"] == sorted(set(status["ordered"])), status
                            assert status["times"] == (["未挑战", "未挑战", "04:05"] if stage == "skipped" else ["01:05", "02:10", "04:05"]), status
                            assert status["total"] == ("04:05" if stage == "skipped" else "07:20"), status
                        screenshot = command("Page.captureScreenshot", {"format": "png"})
                        (OUTPUT / f"{stage}-{width}.png").write_bytes(base64.b64decode(screenshot["data"]))
                        print(json.dumps({"width": width, **status}, ensure_ascii=False), flush=True)
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
