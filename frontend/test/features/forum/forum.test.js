/** 论坛客户端契约：失败冻结负载、账号隔离、明确点赞状态和码点长度。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { ForumClient, validateText, forumRequest } from '../../../src/features/forum/client.js';

test('正文按 Unicode 码点校验并统一去首尾空白', () => {
  assert.equal(validateText('  😀\n中文  ', 5), '😀\n中文');
  assert.throws(() => validateText(' \n', 10), /不能为空/);
  assert.throws(() => validateText('😀'.repeat(81),80), /80/);
});

test('失败重试冻结编号及负载，成功后下一次生成新编号', async () => {
  const calls = []; let fail = true, id = 0;
  const client = new ForumClient(async (path, options) => {
    calls.push(structuredClone(options.body));
    if (fail) { fail = false; throw new Error('offline'); }
    return {id:1};
  }, () => String(++id));
  client.setUser({id:1});
  await assert.rejects(client.publish('posts',{body:'原文'}),/offline/);
  await client.publish('posts',{body:'改文'});
  assert.deepEqual(calls[0], calls[1]);
  await client.publish('posts',{body:'新文'});
  assert.notEqual(calls[1].request_id,calls[2].request_id);
});

test('换号后晚到发布和读取响应失效，清空待提交内容', async () => {
  let finish;
  const client = new ForumClient(() => new Promise(resolve => { finish=resolve; }), ()=>'id');
  client.setUser({id:1});
  const old = client.publish('posts',{body:'b'});
  client.setUser({id:2}); finish({id:99});
  await assert.rejects(old,/账号/);
  assert.equal(client.pending.size,0);
  const reading = client.read('posts');
  client.setUser(null); finish({items:[]});
  await assert.rejects(reading,/账号/);
});

test('点赞在请求期间排除重复操作，明确 PUT 或 DELETE', async () => {
  let finish; const calls=[];
  const client = new ForumClient((path, options)=>{ calls.push(options.method); return new Promise(resolve=>{finish=resolve;}); });
  client.setUser({id:1});
  const first = client.like('posts',1,false);
  await client.like('posts',1,false);
  assert.deepEqual(calls,['PUT']);
  finish({like_count:1,liked_by_me:true}); await first;
  const second = client.like('posts',1,true);
  finish({like_count:0,liked_by_me:false}); await second;
  assert.deepEqual(calls,['PUT','DELETE']);
});

test('换号后的旧失败同样标记失效，不把旧错误展示给新账号', async () => {
  let fail;
  const client=new ForumClient(()=>new Promise((_,reject)=>{fail=reject;}),()=> 'id');
  client.setUser({id:1});
  for(const operation of [()=>client.read('posts'),()=>client.publish('posts',{body:'b'}),()=>client.like('posts',1,false)]){
    const result=operation();client.setUser({id:(client.user.id===1?2:1)});fail(new Error('旧账号错误'));
    await assert.rejects(result,error=>error.stale===true);
  }
});

test('错误保留 Retry-After 并拒绝无效成功响应', async t => {
  const original = globalThis.fetch; t.after(()=>{globalThis.fetch=original;});
  globalThis.fetch=async()=>({ok:false,status:503,headers:{get:()=> '3'},json:async()=>({detail:'繁忙'})});
  await assert.rejects(forumRequest('posts'),e=>e.status===503 && e.retryAfter===3);
  globalThis.fetch=async()=>({ok:true,json:async()=>null});
  await assert.rejects(forumRequest('posts'),/异常/);
});
