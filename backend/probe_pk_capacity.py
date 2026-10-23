"""作用：从开发机观测专用验收站点的HTTP/SSE共存，不修改账号成长或自动创建对局。

sessions文件为最多16个专用测试账号的Cookie值JSON数组；禁止使用真实玩家会话或提交该文件。
先由验收人员准备2/4/8人房间和8人排队，每阶段运行至少1800秒，再做重连/结束循环。
本工具只记录客户端延迟/状态/连接，目标机CPU、RSS、MemAvailable、MySQL锁和OOM须另行记录。
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event, Lock
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def percentile(values, fraction):
    """有限窗口样本采用最近秩，记录客户端看到的请求延迟。"""
    return round(sorted(values)[min(len(values)-1, int(len(values)*fraction))], 2) if values else None


def probe(base_url, tokens, cookie_name, duration):
    """最多16流、4个普通查询线程；心跳只读，重连间隔至少3秒。"""
    stop, guard = Event(), Lock()
    connections, stats, latency = set(), Counter(), []
    started = time.monotonic()

    def headers(token):
        """会话只进入HTTP Cookie，不写日志或结果文件。"""
        return {'Cookie': f'{cookie_name}={token}', 'Cache-Control': 'no-cache'}

    def stream(token):
        """SSE与普通JSON的短超时独立，20秒无数据才判读超时。"""
        while not stop.is_set():
            response = None
            try:
                response = urlopen(Request(base_url+'/api/v1/me/events', headers=headers(token)), timeout=20)
                with guard:
                    connections.add(response); stats['stream_opens'] += 1
                    stats['stream_peak'] = max(stats['stream_peak'], len(connections))
                while not stop.is_set():
                    line = response.readline()
                    if not line:
                        break
                    if line.startswith(b'event:'):
                        with guard:
                            stats['event_messages'] += 1
            except HTTPError as exc:
                with guard:
                    stats[f'stream_http_{exc.code}'] += 1
            except (OSError, URLError, ValueError):
                if not stop.is_set():
                    with guard:
                        stats['stream_disconnects'] += 1
            finally:
                if response:
                    with guard:
                        connections.discard(response)
                    response.close()
            stop.wait(3)

    def query(path, token=None):
        """只读有界资源；不读取/记录响应正文中的账号数据。"""
        before, status = time.monotonic(), 0
        try:
            with urlopen(Request(base_url+path, headers=headers(token) if token else {}), timeout=12) as response:
                response.read(65536); status = response.status
        except HTTPError as exc:
            status = exc.code
        except (OSError, URLError):
            status = 0
        with guard:
            stats[f'http_{status}'] += 1
            # 最大7200秒×17请求/秒，样本数本身有界。
            latency.append((time.monotonic()-before)*1000)

    with ThreadPoolExecutor(max_workers=len(tokens)) as streams, ThreadPoolExecutor(max_workers=4) as queries:
        jobs = [streams.submit(stream, token) for token in tokens]
        try:
            while time.monotonic()-started < duration:
                query('/api/rankings/mine?page_size=1')
                batch = [queries.submit(query, '/api/v1/me/progression', token) for token in tokens]
                for job in batch:
                    job.result()
                stop.wait(1)
        finally:
            stop.set()
            with guard:
                opened = list(connections)
            for response in opened:
                response.close()
            for job in jobs:
                job.result()
    return {'observed_seconds': round(time.monotonic()-started, 2), 'counts': dict(stats),
            'http_latency_ms': {'p50': percentile(latency, .5), 'p95': percentile(latency, .95), 'p99': percentile(latency, .99)},
            'target_machine_capacity_accepted': False,
            'note': '需合并目标机本底/资源/锁/OOM证据后人工核对门槛，不能仅凭本报告判定容量通过。'}


def main():
    """显式指定验收站点与本地私密会话文件，默认观察30分钟。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--sessions-file', type=Path, required=True)
    parser.add_argument('--cookie-name', default='jobless_session')
    parser.add_argument('--seconds', type=int, default=1800, choices=range(5, 7201), metavar='5..7200')
    parser.add_argument('--output', type=Path, default=Path('artifacts/backend/pk-capacity.local.json'))
    args = parser.parse_args()
    tokens = json.loads(args.sessions_file.read_text(encoding='utf-8'))
    if not isinstance(tokens, list) or not 1 <= len(tokens) <= 16 or any(not isinstance(t, str) or not t or '\n' in t or '\r' in t for t in tokens):
        raise SystemExit('需要1～16个专用会话值，不可包含换行')
    report = probe(args.base_url.rstrip('/'), tokens, args.cookie_name, args.seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f"Capacity observation saved: {args.output}; peak streams={report['counts'].get('stream_peak', 0)}; P95={report['http_latency_ms']['p95']}ms")


if __name__ == '__main__':
    main()
