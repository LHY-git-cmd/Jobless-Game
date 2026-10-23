/** 作用：先验证主动退出的条件写入、丢响应重试及草稿按尝试清理，不访问真实网络。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { abandonAttempt } from '../../../src/features/progression/attempt-exit.js';
import { createJourneyStore } from '../../../src/features/progression/journey-store.js';

const attempt={attempt_id:'a',level_id:'level-a',level_version:1,puzzle:{checksum:'one'},links:{self:'/api/v1/attempts/a'}};

test('主动退出先GET最新ETag，再PATCH终止原局，不创建新局',async()=>{
  const calls=[];
  const request=async(path,options={})=>{
    calls.push({path,...options});
    return {data:{...attempt,status:options.method==='PATCH'?'abandoned':'active'},etag:'"7"'};
  };
  const result=await abandonAttempt({attempt,request});
  assert.equal(result.data.status,'abandoned');
  assert.deepEqual(calls,[{path:attempt.links.self},{path:attempt.links.self,method:'PATCH',body:{status:'abandoned'},headers:{'If-Match':'"7"'}}]);
});

test('退出成功但丢响应时，重试核验已结束状态，不重复写入',async()=>{
  let status='active',patches=0;
  const request=async(path,options={})=>{
    if(options.method==='PATCH'){patches++;status='abandoned';throw new Error('连接中断');}
    return {data:{...attempt,status},etag:'"8"'};
  };
  await assert.rejects(abandonAttempt({attempt,request}),/连接中断/);
  assert.equal((await abandonAttempt({attempt,request})).data.status,'abandoned');
  assert.equal(patches,1);
});

test('其他页面已结算或修订冲突时拒绝覆盖，调用方可保留草稿重试',async()=>{
  let patches=0;
  await assert.rejects(abandonAttempt({attempt,request:async()=>({data:{...attempt,status:'completed'},etag:'"9"'})}),/已结束/);
  const conflict=Object.assign(new Error('状态已变化'),{status:412});
  await assert.rejects(abandonAttempt({attempt,request:async(path,options={})=>{
    if(options.method==='PATCH'){patches++;throw conflict;}
    return {data:{...attempt,status:'active'},etag:'"8"'};
  }}),error=>error===conflict);
  assert.equal(patches,1);
});

test('清理只删除当前尝试草稿、待提交与开局键，保留其他关卡和账号',()=>{
  const memory=new Map(),storage={getItem:key=>memory.get(key),setItem:(key,value)=>memory.set(key,value)};
  const one=createJourneyStore(storage,1),two=createJourneyStore(storage,2);
  const other={...attempt,attempt_id:'b',level_id:'level-b'};
  one.save(attempt,{bulbs:[1]});one.freeze(attempt,{bulbs:[1]});one.startKey(attempt.level_id);
  one.save(other,{bulbs:[2]});two.save(attempt,{bulbs:[3]});
  one.discard(attempt);
  const restored=createJourneyStore(storage,1);
  assert.equal(restored.reference(attempt.level_id),null);
  assert.equal(restored.load(attempt),null);
  assert.deepEqual(restored.load(other).draft,{bulbs:[2]});
  assert.deepEqual(two.load(attempt).draft,{bulbs:[3]});
  assert.equal(JSON.parse(memory.get('jobless-journey-v1:1')).starts[attempt.level_id],undefined);
});

test('迟到退出清理不得删除另一页面的新局或新增关卡草稿',()=>{
  const memory=new Map(),storage={getItem:key=>memory.get(key),setItem:(key,value)=>memory.set(key,value)};
  const first=createJourneyStore(storage,1);first.save(attempt,{bulbs:[1]});
  const second=createJourneyStore(storage,1),next={...attempt,attempt_id:'new'};
  second.save(next,{bulbs:[5]});second.save({...attempt,level_id:'another',attempt_id:'another'},{bulbs:[9]});
  first.discard(attempt);
  const restored=createJourneyStore(storage,1);
  assert.equal(restored.reference(attempt.level_id),'new');
  assert.equal(restored.reference('another'),'another');
});
