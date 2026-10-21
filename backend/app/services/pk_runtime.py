"""单进程PK运行态：有限SSE队列、提交入口追踪和短事务互斥，无数据库长连接。"""
import asyncio
from dataclasses import dataclass
import json
from threading import Lock, RLock
from uuid import uuid4
from ..common.security import hash_session_token
from .progression_service import fail


@dataclass
class Subscription:
    """一个账号一条流，Queue最多16条且每条≤2KiB。"""
    uid: int
    token_hash: str
    loop: object
    queue: object
    closed: bool = False


class PKRuntime:
    """不缓存无限对局历史；数据库持久结果始终是权威。"""

    def __init__(self):
        """业务锁与入口/事件锁分离，入口登记不等待数据库锁。"""
        self.lock, self.guard = RLock(), Lock()
        self.streams, self.pending = {}, {}
        self.sequence, self.waiting_ids = 0, []

    def reset(self):
        """仅用于服务停机和隔离测试清理有限运行态。"""
        with self.guard:
            for sub in self.streams.values():
                sub.closed = True
            self.streams.clear()
            self.pending.clear()
            self.waiting_ids.clear()
            self.sequence = 0

    def receive(self, room_id, received_at):
        """在HTTP入口注册，调度器结算前核对平局窗口内未处理请求。"""
        with self.guard:
            if len(self.pending) >= 32:
                fail(503, 'submission_capacity', '提交服务暂时繁忙。', headers={'Retry-After': '1'})
            key = str(uuid4())
            self.pending[key] = (room_id, received_at)
            return key

    def processed(self, key):
        """成功、校验失败、取消均移除入口登记，避免残留阻止结算。"""
        with self.guard:
            self.pending.pop(key, None)

    def has_pending(self, room_id, deadline):
        """只核对该房间已接收且时间落在窗口内的有界任务。"""
        with self.guard:
            return any(rid == room_id and at <= deadline for rid, at in self.pending.values())

    def subscribe(self, uid, token, maximum):
        """鉴权完成并释放DB后才申请流槽，不把Session交给生成器。"""
        with self.guard:
            if uid in self.streams:
                fail(409, 'event_stream_exists', '此账号已有事件连接。')
            if len(self.streams) >= maximum:
                fail(503, 'event_stream_capacity', '实时连接暂满，请稍后重试。', headers={'Retry-After': '3'})
            sub = Subscription(uid, hash_session_token(token), asyncio.get_running_loop(), asyncio.Queue(maxsize=16))
            self.streams[uid] = sub
            return sub

    def unsubscribe(self, sub):
        """身份校验避免旧流的finally删除新建立的连接。"""
        with self.guard:
            if self.streams.get(sub.uid) is sub:
                self.streams.pop(sub.uid)
            sub.closed = True

    def online(self, uid):
        """在线状态只读有限内存，不做数据库心跳。"""
        with self.guard:
            return uid in self.streams and not self.streams[uid].closed

    def publish(self, uid, resource, revision=0):
        """事务提交后通知资源修订；不包含棋盘或对手终盘。"""
        with self.guard:
            sub = self.streams.get(uid)
            self.sequence += 1
            event = {'id': self.sequence, 'resource': resource, 'revision': revision}
        if sub and not sub.closed:
            try:
                sub.loop.call_soon_threadsafe(self._enqueue, sub, event)
            except RuntimeError:
                self.unsubscribe(sub)

    def _enqueue(self, sub, event):
        """慢客户端队列满后关闭，重连resync而非累积历史。"""
        if sub.closed:
            return
        if sub.queue.full() or len(json.dumps(event).encode()) > 2048:
            sub.closed = True
            return
        sub.queue.put_nowait(event)

    def revoke(self, token):
        """注销立即撤销该会话的本进程流，最长15秒唤醒后退出。"""
        if not token:
            return
        fingerprint = hash_session_token(token)
        with self.guard:
            for sub in self.streams.values():
                if sub.token_hash == fingerprint:
                    sub.closed = True
                    try:
                        sub.loop.call_soon_threadsafe(self._wake_closed, sub)
                    except RuntimeError:
                        pass

    def _wake_closed(self, sub):
        """注销即时唤醒生成器，不必等下一次心跳才能释放连接。"""
        if sub.queue.full():
            sub.queue.get_nowait()
        sub.queue.put_nowait(None)


runtime = PKRuntime()
