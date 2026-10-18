"""单次分批清理过期会话，由宝塔/系统计划任务调用；不启动常驻服务。"""

import argparse

from .app.common.database import engine
from .app.repositories.session_repository import remove_expired_batch


def clean_sessions(batch_size: int = 500, max_batches: int = 10) -> int:
    """利用 expires_at 索引分批提交；每次运行有明确批次数上限。"""
    total = 0
    for _ in range(max_batches):
        with engine.begin() as connection:
            affected = remove_expired_batch(connection, batch_size)
        total += affected
        if affected < batch_size:
            break
    return total


def main():
    """解析维护任务的单次工作量限制，只输出删除数量。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500, choices=range(1, 1001), metavar="1..1000")
    parser.add_argument("--max-batches", type=int, default=10, choices=range(1, 101), metavar="1..100")
    options = parser.parse_args()
    try:
        print(f"Deleted sessions: {clean_sessions(options.batch_size, options.max_batches)}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
