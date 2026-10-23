/** 作用：验证三款游戏共用的原子重开只发一个POST，失败沿用原UUID。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { restartAttempt } from '../../../src/features/progression/attempt-energy.js';
import { createJourneyStore } from '../../../src/features/progression/journey-store.js';

test('原子重开失败不PATCH旧局，重试使用同一UUID及空负载',async()=>{
  const memory=new Map(),calls=[];let fail=true;
  const store=createJourneyStore({getItem:key=>memory.get(key),setItem:(key,value)=>memory.set(key,value)},1);
  const attempt={attempt_id:'original',links:{self:'/api/v1/attempts/original'}};
  const request=async(path,options)=>{calls.push({path,...options});if(fail)throw new Error('体力不足');return {data:{attempt_id:'new'}};};
  await assert.rejects(restartAttempt({attempt,store,request}),/体力不足/);fail=false;
  const result=await restartAttempt({attempt,store,request});
  assert.equal(calls[0].headers['Idempotency-Key'],calls[1].headers['Idempotency-Key']);
  assert.ok(calls.every(call=>call.method==='POST'&&call.path.endsWith('/restart')));assert.deepEqual(calls[0].body,{});
  const previous=calls[1].headers['Idempotency-Key'];result.clear();
  assert.notEqual(store.startKey('restart:original'),previous);
});
