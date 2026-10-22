/** 公共传输契约：超时隔离、定时器释放、JSON/204 与业务错误信息保留。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { requestJson, HttpError } from '../../src/shared/http.js';
import { authRequest, AuthError } from '../../src/features/account/client.js';
import { forumRequest } from '../../src/features/forum/client.js';
import { rankingRequest } from '../../src/features/ranking/client.js';

test('共享传输设置同源 Cookie/禁止缓存并序列化 JSON，204 不读取响应体', async () => {
  const calls=[], cleared=[];
  const fetchImpl=async (url,options)=>{ calls.push({url,options}); return {ok:true,status:204,json(){throw new Error('204 must not read JSON');}}; };
  assert.equal(await requestJson('/api/example',{method:'POST',body:{text:'原文'},fetchImpl,
    setTimer:()=>7,clearTimer:id=>cleared.push(id)}),null);
  assert.equal(calls.length,1);
  assert.equal(calls[0].options.credentials,'same-origin');
  assert.equal(calls[0].options.cache,'no-store');
  assert.deepEqual(JSON.parse(calls[0].options.body),{text:'原文'});
  assert.deepEqual(cleared,[7]);
});

test('每次请求有独立超时，超时不重试且释放失败和成功请求的定时器', async () => {
  const timers=[],cleared=[];
  let calls=0;
  const options={timeoutMs:30,setTimer:(callback,ms)=>{timers.push({callback,ms});return timers.length;},clearTimer:id=>cleared.push(id)};
  const first=requestJson('/slow',{...options,fetchImpl:async (_,request)=>{
    calls++; return await new Promise((resolve,reject)=>request.signal.addEventListener('abort',()=>reject(new DOMException('timeout','AbortError'))));
  }});
  const rejected=assert.rejects(first,/连接失败/);
  assert.deepEqual(await requestJson('/fast',{...options,fetchImpl:async()=>({ok:true,status:200,json:async()=>({done:true})})}),{done:true});
  timers[0].callback(); await rejected;
  assert.equal(timers[0].ms,30);
  assert.equal(calls,1);
  assert.deepEqual(cleared.sort(),[1,2]);
});

test('HTTP 错误保留状态、结构化 detail 和 Retry-After，非 JSON 错误仍有状态', async () => {
  for(const data of [{detail:{message:'繁忙',field:'username'}},null]) {
    await assert.rejects(requestJson('/failed',{fetchImpl:async()=>({ok:false,status:503,
      headers:new Headers({'Retry-After':'3'}),json:async()=>{if(!data)throw new Error('proxy html');return data;}})}),
    error=>error instanceof HttpError&&error.status===503&&error.retryAfter===3&&error.detail===(data?.detail));
  }
});

test('迁移后各业务包装保留认证字段/204、论坛退避与挑战错误文案差异', async t => {
  const original=globalThis.fetch;
  t.after(()=>{globalThis.fetch=original;});
  globalThis.fetch=async()=>({ok:false,status:422,headers:new Headers({'Retry-After':'4'}),json:async()=>({detail:{message:'字段错误',field:'username'}})});
  await assert.rejects(authRequest('login'),error=>error instanceof AuthError&&error.field==='username'&&error.status===422);
  await assert.rejects(forumRequest('posts'),error=>error.message==='字段错误'&&error.retryAfter===4);
  await assert.rejects(rankingRequest('challenges/start'),error=>error.message==='请求失败，请稍后重试。'&&error.status===422);
  globalThis.fetch=async()=>({ok:true,status:204});
  assert.equal(await authRequest('logout',{method:'POST'}),null);
  globalThis.fetch=async()=>({ok:true,status:200,json:async()=>[]});
  await assert.rejects(forumRequest('posts'),/返回异常/);
  await assert.rejects(authRequest('me'),/返回异常/);
});
