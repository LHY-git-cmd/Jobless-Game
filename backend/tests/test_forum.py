"""论坛契约先行测试：隔离 SQLite 验证 HTTP 与事务，真实 InnoDB 另行验收。"""

from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import main
from backend.app.common.config import get_settings
from backend.app.common.database import Base, get_db
from backend.app.common.security import hash_session_token, utc_now
from backend.app.models.entities import AuthSession, User


class ForumTests(TestCase):
    """两个真实 Cookie 身份通过公开接口交互，每例数据库独立。"""

    def setUp(self):
        """仅创建临时数据库，不读取或修改正式业务库。"""
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        with self.sessions() as db:
            for n in (1, 2):
                db.add(User(id=n, username=f'玩家{n}', username_key=f'玩家{n}', password_hash='unchanged', created_at=utc_now()))
            db.flush()
            for n in (1, 2):
                db.add(AuthSession(id=n, user_id=n, token_hash=hash_session_token(f'forum-{n}'), created_at=utc_now(), expires_at=utc_now()+timedelta(days=1)))
            db.commit()

        def dependency():
            """请求会话在线程执行完成后关闭。"""
            with self.sessions() as db:
                yield db
        main.app.dependency_overrides[get_db] = dependency
        self.client = TestClient(main.app, headers={'Origin': 'http://testserver'})
        self.login(1)

    def tearDown(self):
        """释放依赖覆盖及临时数据库连接。"""
        self.client.close()
        main.app.dependency_overrides.clear()
        self.engine.dispose()

    def login(self, n):
        """切换测试身份，游客不携带 Cookie。"""
        self.client.cookies.clear()
        if n:
            self.client.cookies.set(get_settings().session_cookie_name, f'forum-{n}')

    def post(self, body='中文\n<script>作为文字</script>', request_id=None):
        """发布并确保不是静态挂载返回的 404。"""
        response = self.client.post('/api/forum/posts', json={'body': body, 'request_id': request_id or str(uuid4())})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def comment(self, post_id, body='评论', reply_to=None, request_id=None):
        """发布评论或两层回复并返回已确认内容。"""
        response = self.client.post(f'/api/forum/posts/{post_id}/comments', json={'request_id': request_id or str(uuid4()), 'body': body, 'reply_to_comment_id': reply_to})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_public_read_auth_origin_and_forged_author(self):
        """游客只读，同源校验和作者归属均不可绕过。"""
        self.login(None)
        self.assertEqual(self.client.get('/api/forum/posts').status_code, 200)
        payload = {'request_id': str(uuid4()), 'body': 'b'}
        self.assertEqual(self.client.post('/api/forum/posts', json=payload).status_code, 401)
        self.login(1)
        self.assertEqual(self.client.post('/api/forum/posts', json=payload, headers={'Origin':'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/forum/posts', json={**payload, 'user_id':2}).status_code, 422)

    def test_post_idempotency_before_rate_limit_and_payload_conflict(self):
        """同编号重试先于限频确认，改负载拒绝，新请求限频。"""
        key = str(uuid4())
        first = self.post(request_id=key)
        self.assertEqual(self.post(request_id=key)['id'], first['id'])
        response = self.client.post('/api/forum/posts', json={'request_id':key,'body':'不同'})
        self.assertEqual(response.status_code, 409)
        response = self.client.post('/api/forum/posts', json={'request_id':str(uuid4()),'body':'正文'})
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers['retry-after']), 0)

    def test_unicode_lengths_plain_text_and_summary(self):
        """Unicode 按码点计数，摘要有限，详情保留换行与 HTML 字面内容。"""
        body = '😀' * 1990 + '\n<b>文字</b>'
        first = self.post(body=body)
        detail = self.client.get(f"/api/forum/posts/{first['id']}").json()
        self.assertEqual(detail['body'], body)
        self.assertNotIn('title', detail)
        self.assertNotIn('title', self.client.get('/api/forum/posts').json()['items'][0])
        self.assertNotIn('body', self.client.get('/api/forum/posts').json()['items'][0])
        for text in ['😀'*2001, '  ', ' \n']:
            response = self.client.post('/api/forum/posts', json={'request_id':str(uuid4()), 'body':text})
            self.assertEqual(response.status_code, 422)

    def test_comments_replies_context_and_ownership(self):
        """回复已有回复保持根归属，跨帖引用及伪造根字段拒绝。"""
        post = self.post()
        self.login(2)
        other = self.post()
        root = self.comment(post['id'])
        self.login(1)
        reply = self.comment(post['id'], reply_to=root['id'])
        self.login(2)
        # 通过时钟推进避开配置默认的三秒间隔。
        with patch('backend.app.services.forum_service.utc_now', return_value=utc_now()+timedelta(seconds=5)):
            nested = self.comment(post['id'], reply_to=reply['id'])
        self.assertEqual(nested['root_comment_id'], root['id'])
        self.assertEqual(nested['reply_to_comment_id'], reply['id'])
        context = self.client.get(f"/api/forum/posts/{post['id']}/comments/{nested['id']}").json()
        self.assertEqual(context['root']['id'], root['id'])
        self.assertEqual(context['target']['id'], nested['id'])
        self.assertEqual(self.client.get(f"/api/forum/posts/{other['id']}/comments/{nested['id']}").status_code, 404)
        response = self.client.post(f"/api/forum/posts/{other['id']}/comments", json={'request_id':str(uuid4()), 'body':'x', 'reply_to_comment_id':root['id']})
        self.assertEqual(response.status_code, 409)
        detail = self.client.get(f"/api/forum/posts/{post['id']}").json()
        self.assertEqual(detail['comment_count'], 3)
        roots = self.client.get(f"/api/forum/posts/{post['id']}/comments").json()['items']
        self.assertEqual((len(roots),roots[0]['reply_count']), (1,2))
        self.assertEqual(len(self.client.get(f"/api/forum/comments/{root['id']}/replies").json()['items']),2)
        self.assertEqual(self.client.get(f"/api/forum/comments/{reply['id']}/replies").status_code,409)

    def test_comment_retry_conflict_and_shared_rate(self):
        """评论与回复共用限频，重试无重复记录或重复提醒。"""
        post = self.post()
        self.login(2)
        key = str(uuid4())
        root = self.comment(post['id'], request_id=key)
        self.assertEqual(self.comment(post['id'],request_id=key)['id'],root['id'])
        path = f"/api/forum/posts/{post['id']}/comments"
        self.assertEqual(self.client.post(path,json={'request_id':key,'body':'修改'}).status_code,409)
        self.assertEqual(self.client.post(path,json={'request_id':str(uuid4()),'body':'回复','reply_to_comment_id':root['id']}).status_code,429)
        self.assertEqual(self.client.post(path,json={'request_id':str(uuid4()),'body':'x'*501}).status_code,422)
        self.assertEqual(self.client.post(path,json={'request_id':str(uuid4()),'body':'x','root_comment_id':999}).status_code,422)
        self.login(1)
        self.assertEqual(self.client.get('/api/forum/notifications/unread-count').json()['count'],1)

    def test_like_idempotency_counters_and_deduplicated_notifications(self):
        """帖子、评论、回复点赞显式设置状态，反复点赞仅保留首次提醒。"""
        post = self.post()
        root = self.comment(post['id'])
        with patch('backend.app.services.forum_service.utc_now',return_value=utc_now()+timedelta(seconds=5)):
            reply = self.comment(post['id'],reply_to=root['id'])
        self.assertEqual(self.client.get('/api/forum/notifications/unread-count').json()['count'],0)
        self.login(2)
        for kind, obj in [('posts',post),('comments',root),('comments',reply)]:
            path = f"/api/forum/{kind}/{obj['id']}/like"
            for method, expected in [('put',1),('put',1),('delete',0),('delete',0),('put',1)]:
                response = getattr(self.client,method)(path)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json(),{'like_count':expected,'liked_by_me':bool(expected)})
        self.assertTrue(self.client.get(f"/api/forum/posts/{post['id']}").json()['liked_by_me'])
        self.login(1)
        self.assertEqual(self.client.get('/api/forum/notifications/unread-count').json()['count'],3)
        self.login(None)
        self.assertFalse(self.client.get(f"/api/forum/posts/{post['id']}").json()['liked_by_me'])

    def test_notifications_recipients_privacy_read_boundary_and_context(self):
        """读自己的通知，全部已读保留后来消息，回复只通知直接作者。"""
        post = self.post()
        root = self.comment(post['id'])
        self.login(2)
        reply = self.comment(post['id'], reply_to=root['id'])
        self.login(1)
        messages = self.client.get('/api/forum/notifications').json()
        self.assertEqual(len(messages['items']),1)
        notice = messages['items'][0]
        self.assertEqual((notice['kind'],notice['comment_id']),('reply',reply['id']))
        self.login(2)
        self.assertEqual(self.client.put(f"/api/forum/notifications/{notice['id']}/read").status_code,404)
        self.client.put(f"/api/forum/posts/{post['id']}/like")
        self.login(1)
        self.assertEqual(self.client.post('/api/forum/notifications/read-all',json={'through_id':messages['through_id']}).status_code,200)
        self.assertEqual(self.client.get('/api/forum/notifications/unread-count').json()['count'],1)
        self.client.put(f"/api/forum/notifications/{notice['id']}/read")
        self.assertEqual(self.client.get('/api/forum/notifications/unread-count').json()['count'],1)
        self.login(None)
        self.assertEqual(self.client.get('/api/forum/notifications').status_code,401)

    def test_notification_failure_rolls_back_entire_interaction(self):
        """通知失败时点赞和计数也回滚，重试仍能成功。"""
        post = self.post()
        self.login(2)
        with patch('backend.app.repositories.forum_repository.add_notification',side_effect=RuntimeError('simulated')):
            with self.assertRaises(RuntimeError):
                self.client.put(f"/api/forum/posts/{post['id']}/like")
        self.assertEqual(self.client.get(f"/api/forum/posts/{post['id']}").json()['like_count'],0)
        self.assertEqual(self.client.put(f"/api/forum/posts/{post['id']}/like").json()['like_count'],1)

    def test_cursor_limits_and_missing_objects(self):
        """有限页稳定排序，不接受无效游标及不存在目标。"""
        first = self.post()
        self.login(2)
        second = self.post()
        page = self.client.get('/api/forum/posts?limit=1').json()
        self.assertEqual(page['items'][0]['id'],second['id'])
        next_page = self.client.get(f"/api/forum/posts?limit=1&cursor={page['next_cursor']}").json()
        self.assertEqual(next_page['items'][0]['id'],first['id'])
        self.assertIsNone(next_page['next_cursor'])
        for query in ['limit=51','cursor=-1','limit=0']:
            self.assertEqual(self.client.get('/api/forum/posts?'+query).status_code,422)
        for path in ['/posts/999','/posts/999/comments','/comments/999/replies','/posts/0']:
            self.assertIn(self.client.get('/api/forum'+path).status_code,(404,422))

    def test_independent_32k_body_limit_normal_and_chunked(self):
        """论坛允许完整中文转义正文，普通/分块超限拒绝且登录仍为4KiB。"""
        import json
        payload = json.dumps({'request_id':str(uuid4()),'body':'中'*2000}).encode()
        response = self.client.post('/api/forum/posts',content=payload,headers={'content-type':'application/json'})
        self.assertEqual(response.status_code,200,response.text)
        for body in (b'x'*32769, iter([b'x'*16000,b'x'*17000])):
            self.assertEqual(self.client.post('/api/forum/posts',content=body).status_code,413)
        self.assertEqual(self.client.post('/api/auth/login',content=b'x'*4097).status_code,413)

    def test_unread_cap_read_state_survives_relike_and_current_avatar(self):
        """未读最多100、首次点赞通知已读后不复活，作者头像随账号读取。"""
        from backend.app.models.entities.forum import ForumNotification
        post=self.post();self.login(2)
        path=f"/api/forum/posts/{post['id']}/like"
        self.client.put(path);self.login(1)
        notice=self.client.get('/api/forum/notifications').json()['items'][0]
        self.client.put(f"/api/forum/notifications/{notice['id']}/read")
        self.login(2);self.client.delete(path);self.client.put(path);self.login(1)
        self.assertEqual(self.client.get('/api/forum/notifications/unread-count').json()['count'],0)
        with self.sessions() as db:
            db.get(User,1).avatar_id=17
            for number in range(105):
                db.add(ForumNotification(recipient_id=1,actor_id=2,post_id=post['id'],kind='post_like',event_key=f'test:{number}',created_at=utc_now()))
            db.commit()
        self.assertEqual(self.client.get('/api/forum/notifications/unread-count').json()['count'],100)
        self.assertEqual(self.client.get('/api/forum/posts').json()['items'][0]['avatar_id'],17)

    def test_body_only_creation_and_legacy_post_retry(self):
        """仅提交正文即可发帖；旧标题保留在数据库，不参与展示、重试或通知。"""
        from backend.app.models.entities.forum import ForumPost
        key=str(uuid4())
        with self.sessions() as db:
            db.add(ForumPost(user_id=1,request_id=key,title='历史标题',body='历史正文',created_at=utc_now()))
            db.commit()
        result=self.post(body='历史正文',request_id=key)
        self.assertEqual(result['body'],'历史正文')
        self.assertNotIn('title',result)
        self.assertEqual(self.client.post('/api/forum/posts',json={'request_id':str(uuid4()),'title':'不再接受','body':'正文'}).status_code,422)
        self.login(2)
        self.client.put(f"/api/forum/posts/{result['id']}/like")
        self.login(1)
        notice=self.client.get('/api/forum/notifications').json()['items'][0]
        self.assertNotIn('title',notice)
        self.assertEqual(notice['excerpt'],'历史正文')

    def test_late_comment_context_and_finite_reply_pages(self):
        """后续页的通知目标直接可取；根评论、回复均按稳定游标分页。"""
        post=self.post()
        with patch.object(get_settings(),'forum_comment_interval_seconds',0):
            roots=[self.comment(post['id'],body=f'根{n}') for n in range(22)]
            replies=[self.comment(post['id'],body=f'回复{n}',reply_to=roots[-1]['id']) for n in range(12)]
        roots_page=self.client.get(f"/api/forum/posts/{post['id']}/comments").json()
        self.assertEqual(len(roots_page['items']),20)
        self.assertIsNotNone(roots_page['next_cursor'])
        context=self.client.get(f"/api/forum/posts/{post['id']}/comments/{replies[-1]['id']}").json()
        self.assertEqual(context['root']['id'],roots[-1]['id'])
        page=self.client.get(f"/api/forum/comments/{roots[-1]['id']}/replies").json()
        self.assertEqual(len(page['items']),10)
        last=self.client.get(f"/api/forum/comments/{roots[-1]['id']}/replies?cursor={page['next_cursor']}").json()
        self.assertEqual([item['id'] for item in last['items']],[item['id'] for item in replies[-2:]])

    def test_comment_notification_failure_rolls_back_content_and_counters(self):
        """消息保存失败时内容、帖子计数与发布间隔全部回滚。"""
        from backend.app.models.entities.forum import ForumComment
        post=self.post();self.login(2)
        with patch('backend.app.repositories.forum_repository.add_notification',side_effect=RuntimeError('simulated')):
            with self.assertRaises(RuntimeError):self.comment(post['id'])
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(ForumComment)).all()),0)
        self.assertEqual(self.client.get(f"/api/forum/posts/{post['id']}").json()['comment_count'],0)
        self.comment(post['id'])
