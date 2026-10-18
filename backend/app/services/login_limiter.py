"""登录业务专属的有界频率保护，不放入跨模块公共层。"""

from collections import OrderedDict, deque
from time import monotonic


class LoginRateLimiter:
    """进程内滑动窗口限流；生产入口仍应由 Nginx 做第一层限流。"""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        self.max_attempts = max(1, max_attempts)
        self.window_seconds = max(1, window_seconds)
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, client_key: str, now: float | None = None) -> bool:
        """记录一次尝试并在窗口内超过上限时拒绝。"""

        current = monotonic() if now is None else now
        if client_key not in self._attempts and len(self._attempts) >= 2048:
            self._attempts.popitem(last=False)
        attempts = self._attempts.setdefault(client_key, deque())
        self._attempts.move_to_end(client_key)
        while attempts and current - attempts[0] >= self.window_seconds:
            attempts.popleft()
        if len(attempts) >= self.max_attempts:
            return False
        attempts.append(current)
        return True

