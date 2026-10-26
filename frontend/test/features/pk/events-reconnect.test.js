/** 作用：跨页时旧SSE仍占用连接，拒绝后的新页必须能重新建立通知流。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { subscribeEvents } from '../../../src/features/pk/events.js';

test('SSE被拒绝后主动重建，重连读取权威快照，关闭后不会复活旧连接',()=>{
  const instances=[],timers=new Map();let counter=0,refreshes=0;
  class Source {
    /** 最小事件源替身，模拟409后浏览器不会自动重连。 */
    constructor(){this.events={};instances.push(this);}
    /** 保存浏览器事件回调。 */
    addEventListener(name,callback){this.events[name]=callback;}
    /** 记录主动关闭。 */
    close(){this.closed=true;}
  }
  const subscription=subscribeEvents({Source,onResource:()=>{},onReconnect:()=>refreshes++,setTimer:callback=>{timers.set(++counter,callback);return counter;},clearTimer:id=>timers.delete(id)});
  instances[0].events.error();assert.equal(instances[0].closed,true);assert.equal(timers.size,1);
  const callback=[...timers.values()][0];timers.clear();callback();
  assert.equal(instances.length,2);
  instances[1].events.resync();assert.ok(refreshes>=1);
  instances[1].events.error();subscription.close();assert.equal(timers.size,0);
  instances[0].events.resync();assert.equal(instances.length,2);
});
