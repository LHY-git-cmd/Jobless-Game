"""作用：验证本机真实 Docker/MySQL 链路，并在重建容器后检查会话与成绩持久化。

仅接受回环地址；创建一个随机验收账号。会话和验收状态写入被 Git 忽略的
artifacts/docker/，不输出密码或 Cookie，不连接其他数据库。
"""

import argparse
from http.cookiejar import LWPCookieJar
import json
from pathlib import Path
import secrets
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4


def main():
    """初次验证全部请求，重建后复用原会话核实数据库中原有成绩。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--phase", choices=["initial", "persisted"], default="initial")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if urlparse(base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("本脚本只允许本机回环地址")
    output = Path(__file__).resolve().parents[3] / "artifacts/docker"
    output.mkdir(parents=True, exist_ok=True)
    state_file = output / "smoke-state.local.json"
    cookies = LWPCookieJar(str(output / "smoke-cookies.local.txt"))
    opener = build_opener(HTTPCookieProcessor(cookies))
    passed = 0

    def check(condition, description):
        """只报告失败项，不在日志中输出账号密码或会话内容。"""
        nonlocal passed
        if not condition:
            raise AssertionError(description)
        passed += 1

    def request(path, body=None, expected=200, headers=None):
        """通过 Nginx 执行真实 HTTP 请求，并验证明确的成功或失败状态。"""
        data = json.dumps(body).encode() if body is not None else None
        request_headers = {"Origin": base, "Content-Type": "application/json"}
        request_headers.update(headers or {})
        req = Request(base + path, data=data, headers=request_headers)
        try:
            response = opener.open(req, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            check(response.status == expected, f"{path}: expected {expected}, got {response.status}")
            value = json.loads(content) if "application/json" in response.headers.get("Content-Type", "") else content
            return value, response.headers

    if args.phase == "initial":
        page, _ = request("/")
        check(b"<html" in page.lower(), "Nginx must serve the game HTML")
        _, headers = request("/assets/audio/background.mp3", expected=206, headers={"Range": "bytes=0-63"})
        check("max-age" in headers.get("Cache-Control", ""), "Audio must support browser caching")
        config, _ = request("/api/challenges/config")
        check(config["quick_complete_enabled"] is False, "Development completion must be disabled")
        request("/api/auth/me", expected=401)
        request("/.env", expected=403)
        request("/backend/.env", expected=403)
        request("/api/challenges/start", {"request_id": str(uuid4())}, expected=403,
                headers={"Origin": "http://untrusted.example"})
        request("/api/auth/login", {"username": "x" * 5000, "password": "unused"}, expected=413)

        name = "qa" + secrets.token_hex(5)
        login, headers = request("/api/auth/login", {"username": name, "password": secrets.token_hex(16)})
        check(login["created"] is True, "A unique local verification account must be created")
        check("HttpOnly" in headers.get("Set-Cookie", ""), "Session must use an HttpOnly cookie")
        current, _ = request("/api/auth/me")
        check(current["username"] == name, "Cookie must restore the correct user")
        state, _ = request("/api/challenges/start", {"request_id": str(uuid4())})
        complete_path = f"/api/challenges/{state['run_id']}/complete"
        # 从数独开始，验证真实数据库链路不再限制逐关通关。
        for index, category, seconds in [(2, "sudoku", 30), (0, "mine", 10), (1, "akari", 20)]:
            payload = {"category": category, "revision": state["revision"],
                       "attempt_id": state["levels"][index]["attempt_id"], "duration_seconds": seconds}
            state, _ = request(complete_path, payload)
            repeated, _ = request(complete_path, payload)
            check(state == repeated, "Repeated completion must be idempotent")
        check(state["total_recorded"] is False, "Independent games must not create a total snapshot")
        cookies.save(ignore_discard=True, ignore_expires=True)
        state_file.write_text(json.dumps({"base": base, "username": name, "user_id": current["id"]}), encoding="utf-8")
    else:
        # 原 Cookie 必须在 API、MySQL、Nginx 容器全部重建后依然有效。
        saved = json.loads(state_file.read_text(encoding="utf-8"))
        check(saved["base"] == base, "Persistence verification must use the original origin")
        cookies.load(ignore_discard=True, ignore_expires=True)
        current, _ = request("/api/auth/me")
        check(current["id"] == saved["user_id"], "The original session must survive container recreation")
        name = saved["username"]

    # 三个单项榜和个人记录必须读取真实 MySQL 中的独立关卡成绩。
    for category, duration in [("mine", 10), ("akari", 20), ("sudoku", 30)]:
        records, _ = request(f"/api/records/me?category={category}")
        check(records["best"]["duration_seconds"] == duration, "Saved best duration must match")
        check(len(records["recent"]) == 1, "Idempotent retries must not add duplicate records")
        ranking, _ = request(f"/api/rankings/{category}")
        check(any(row["username"] == name and row["duration_seconds"] == duration for row in ranking["entries"]),
              "The local verification account must appear on each leaderboard")
    request("/api/rankings/total", expected=422)
    request("/api/records/me?category=total", expected=422)
    print(f"Docker HTTP verification ({args.phase}): {passed} checks passed, 0 failed")


if __name__ == "__main__":
    main()
