/** 作用：TDD验证体力权威修订、账号隔离、倒计时和恢复节点读取。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createEnergyModel } from '../../../src/features/account/energy.js';

/** 体力快照只来自服务器，测试时钟只影响显示和恢复节点。 */
function energy(current,revision,next=1800000){return {current,capacity:5,revision,recovery_seconds:1800,server_now:new Date(0).toISOString(),next_recovery_at:current===5?null:new Date(next).toISOString()};}

test('新快照立即更新，旧修订及旧账号不能覆盖余额',async()=>{
  const pending=[],states=[];const model=createEnergyModel({request:()=>new Promise(resolve=>pending.push(resolve)),onChange:value=>states.push(value),now:()=>0});
  model.setUser({id:1});assert.equal(model.accept(1,energy(4,2)),true);
  pending[0](energy(5,0));await Promise.resolve();assert.equal(states.at(-1).energy.current,4);
  assert.equal(model.accept(1,energy(5,1)),false);model.setUser({id:2});
  assert.equal(model.accept(1,energy(3,3)),false);pending[1](energy(5,0));await Promise.resolve();assert.equal(states.at(-1).energy.current,5);
  model.destroy();
});

test('恢复节点才读取，不逐秒轮询，也不本地伪造加体力',async()=>{
  let time=0,calls=0,resolve;const states=[];
  const model=createEnergyModel({now:()=>time,request:async()=>{calls++;if(calls===1)return energy(4,1);return new Promise(done=>resolve=done);},onChange:value=>states.push(value)});
  model.setUser({id:1});await Promise.resolve();
  for(let i=1;i<10;i++){time=i*1000;model.tick();}assert.equal(calls,1);assert.equal(model.remaining(),1791);
  time=1800000;model.tick();model.tick();assert.equal(calls,2);assert.equal(states.at(-1).energy.current,4);
  resolve(energy(5,2));await new Promise(done=>setImmediate(done));assert.equal(states.at(-1).energy.current,5);model.destroy();
});

test('网络失败不把体力伪造成0，退出使迟到读取失效',async()=>{
  let resolve;const states=[];const model=createEnergyModel({request:()=>new Promise(done=>resolve=done),onChange:value=>states.push(value)});
  model.setUser({id:1});model.setUser(null);resolve(energy(5,0));await Promise.resolve();assert.equal(states.at(-1).status,'guest');
  const broken=createEnergyModel({request:async()=>{throw new Error('离线');},onChange:value=>states.push(value)});broken.setUser({id:2});await Promise.resolve();await Promise.resolve();
  assert.equal(states.at(-1).energy,null);assert.equal(states.at(-1).status,'error');broken.destroy();
});

test('恢复读取失败有30秒退避，保留余额且新成功快照解除退避',async()=>{
  let time=0,calls=0,fail=false;const states=[];
  const model=createEnergyModel({now:()=>time,request:async()=>{calls++;if(fail)throw new Error('离线');return energy(4,1);},onChange:value=>states.push(value)});
  model.setUser({id:1});await new Promise(done=>setImmediate(done));
  time=1800000;fail=true;model.tick();await new Promise(done=>setImmediate(done));
  for(let i=0;i<20;i++){time+=1000;model.tick();}assert.equal(calls,2);assert.equal(states.at(-1).energy.current,4);
  time=1830000;fail=false;model.tick();await new Promise(done=>setImmediate(done));assert.equal(calls,3);model.destroy();
});
