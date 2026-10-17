"""用独立无头浏览器复现用户截图、通关弹窗和查看结果，不修改用户当前棋局。

临时 HTTP 服务只绑定本机；验证页加载真实前端代码并通过按钮点击还原三种状态。
输出状态摘要与截图，临时浏览器配置放在系统临时目录并自动清理。
"""

import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


class Handler(SimpleHTTPRequestHandler):
    """正常提供项目文件，仅在验证路径注入真实点击操作和断言。"""
    def do_GET(self):
        request = urlparse(self.path)
        if request.path != "/__qa/akari":
            return super().do_GET()
        stage = parse_qs(request.query).get("stage", ["incomplete"])[0]
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="/frontend/">')
        script = r"""
        <script type="module">
          await import('/frontend/src/main.js');
          const stage = STAGE;
          const $ = id => document.getElementById(id);
          $('akari-entry').click();
          $('akari-rules-close').click();
          const positions = stage === 'incomplete'
            ? [0,2,9,11,15,28,30,36,41,48,54,61,65,73,80,86,89,92,98]
            : [0,2,11,19,28,30,36,41,45,48,54,61,66,73,80,89,92,97];
          for (const index of positions) $('akari-board').children[index].click();
          if(stage === 'result') $('result-secondary').click();
          const visible = id => !$ (id).classList.contains('hidden');
          const status = {
            stage, status: $('akari-status').textContent,
            message: $('akari-message').textContent,
            dialog: visible('result-dialog'), next: visible('akari-next'),
            errorAt56: $('akari-board').children[56].classList.contains('error'),
            title: $('result-title').textContent
          };
          document.body.dataset.qa = JSON.stringify(status);
          document.title = 'QA complete';
        </script>
        """.replace("STAGE", json.dumps(stage))
        html = html.replace("</body>", script + "</body>")
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    """对截图中未通关状态和完整通关交互做浏览器断言并保存截图。"""
    from html import unescape
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for stage in ["incomplete", "dialog", "result"]:
            with tempfile.TemporaryDirectory(prefix="backuplab-akari-qa-") as profile:
                result = subprocess.run([
                    str(CHROME), "--headless", "--disable-gpu", "--no-first-run",
                    "--disable-background-networking", f"--user-data-dir={profile}",
                    "--window-size=1280,1150", "--virtual-time-budget=2500",
                    f"--screenshot={OUTPUT / ('akari-' + stage + '.png')}", "--dump-dom",
                    f"http://127.0.0.1:{server.server_port}/__qa/akari?stage={stage}",
                ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                match = re.search(r'data-qa="([^"]+)"', result.stdout)
                if result.returncode or not match:
                    raise RuntimeError(f"浏览器验证失败：{stage}，退出码 {result.returncode}\n{result.stderr[-1200:]}\n{result.stdout[-400:]}")
                status = json.loads(unescape(match[1]))
                assert status["dialog"] == (stage == "dialog"), status
                assert status["next"] == (stage == "result"), status
                if stage == "incomplete":
                    assert status["errorAt56"] and "第 6 行第 7 列" in status["message"], status
                else:
                    assert status["title"] == "第二关通关成功", status
                print(json.dumps(status, ensure_ascii=False))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
