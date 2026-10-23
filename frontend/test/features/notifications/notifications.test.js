/** 站内通知控制器契约：按可见性轮询，隔离账号，不累积并发计时器。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { NotificationController } from '../../../src/features/notifications/controller.js';

test('默认调度器保留浏览器全局对象接收者', t => {
  const originalSet=globalThis.setTimeout,originalClear=globalThis.clearTimeout;
  t.after(()=>{globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;});
  globalThis.setTimeout=function(){assert.equal(this,globalThis);return 1;};
  globalThis.clearTimeout=function(){assert.equal(this,globalThis);};
  const controller=new NotificationController();controller.user={id:1};controller.schedule(10);controller.stop();
});

test('登录才请求，完成后安排下一轮，隐藏及退出清空私人状态', async () => {
  const timers=new Map(); let serial=0, calls=0, finish;
  const controller=new NotificationController({request:()=>{calls++;return new Promise(r=>{finish=r;});},setTimer:(fn,ms)=>{timers.set(++serial,{fn,ms});return serial;},clearTimer:id=>timers.delete(id),onChange:()=>{}});
  controller.setUser(null); assert.equal(calls,0);
  controller.setUser({id:1}); assert.equal(calls,1); assert.equal(timers.size,0);
  finish({count:100,latest_id:10}); await new Promise(r=>setImmediate(r));
  assert.equal(controller.state.count,100); assert.equal(timers.size,1);
  assert.equal([...timers.values()][0].ms,60000);
  controller.setVisible(false); assert.equal(timers.size,0);
  controller.setUser(null); assert.equal(controller.state.count,0);
});

test('旧账号列表及计数不能污染新账号，并发请求只留一个', async () => {
  const pending=[];
  const controller=new NotificationController({request:path=>new Promise(r=>pending.push({path,r})),setTimer:()=>1,clearTimer:()=>{}});
  controller.setUser({id:1}); const old=controller.load();
  controller.setUser({id:2});
  pending[0].r({count:5,latest_id:8});pending[1].r({items:[{id:8}],through_id:8,next_cursor:null});
  await old; await new Promise(r=>setImmediate(r));
  assert.equal(controller.state.count,0);assert.deepEqual(controller.state.items,[]);
  pending[2].r({count:1,latest_id:9}); await new Promise(r=>setImmediate(r));
  assert.equal(controller.state.count,1);
  controller.setUser(null);
});

test('打开列表不自动已读，全部已读沿用第一次查询边界', async () => {
  const calls=[];
  const controller=new NotificationController({request:async(path,options)=>{calls.push({path,options}); if(path.includes('unread-count'))return {count:1,latest_id:9}; if(path==='notifications')return {items:[{id:9,read_at:null}],through_id:9,next_cursor:null};return {};},setTimer:()=>1,clearTimer:()=>{}});
  controller.setUser({id:1}); await controller.load();
  assert.equal(calls.some(x=>x.options?.method),false);
  await controller.readAll();
  assert.equal(calls.find(x=>x.path.endsWith('read-all')).options.body.through_id,9);
  controller.setUser(null);
});
