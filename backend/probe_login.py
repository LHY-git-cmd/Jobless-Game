"""对获授权的服务执行小规模登录探测，统计延迟、吞吐和过载；不输出密码或 Cookie。

从开发机运行，仅使用专门准备的测试账号；密码交互输入，最多 100 次请求。
此脚本不测量目标机器内存，也不代表生产容量承诺。
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import getpass
import json
import math
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main():
    """登录探测有明确数量、并发和超时上限，429/503 单独统计。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("username")
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 5, 10], default=1)
    parser.add_argument("--requests", type=int, choices=range(1, 101), default=20, metavar="1..100")
    args = parser.parse_args()
    base = urlparse(args.base_url)
    if base.scheme not in {"http", "https"} or not base.netloc or base.username or base.password:
        parser.error("base_url 必须为不含凭据的 HTTP/HTTPS 站点地址")
    origin = f"{base.scheme}://{base.netloc}"
    password = getpass.getpass("测试账号密码（不写入输出）: ")
    body = json.dumps({"username": args.username, "password": password}, ensure_ascii=False).encode()

    def request_once(_):
        """只返回状态和耗时，不输出响应内容或敏感请求值。"""
        start = perf_counter()
        request = Request(origin + "/api/auth/login", data=body, headers={"Content-Type": "application/json", "Origin": origin})
        try:
            with urlopen(request, timeout=15) as response:
                code = response.status
        except HTTPError as error:
            code = error.code
        except (URLError, TimeoutError):
            code = "network_error"
        return code, perf_counter() - start

    start = perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(request_once, range(args.requests)))
    elapsed = perf_counter() - start
    durations = sorted(duration for _, duration in results)
    successful = sorted(duration for code, duration in results if code == 200)
    statuses = Counter(str(code) for code, _ in results)
    def percentile(values, proportion):
        """成功与所有响应分别报告，避免快速拒绝掩盖成功登录耗时。"""
        return round(values[math.ceil(len(values) * proportion) - 1] * 1000, 2) if values else None
    print(json.dumps({
        "concurrency": args.concurrency, "requests": args.requests,
        "statuses": dict(statuses), "overload_rejections": statuses["429"] + statuses["503"],
        "error_rate": sum(code != 200 for code, _ in results) / len(results),
        "p50_ms_all": percentile(durations, .5), "p95_ms_all": percentile(durations, .95),
        "p50_ms_success": percentile(successful, .5), "p95_ms_success": percentile(successful, .95),
        "requests_per_second": round(len(results) / elapsed, 3),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
