/** 作用：验证竞技跳转边界和服务端结果说明，不依赖浏览器时钟判胜。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { arenaDestination, arenaResult, readArenaSnapshot } from '../../../src/features/pk/flow.js';

test('大厅等待和倒计时均不跳转，playing才进入独立游戏页',()=>{
  for(const status of ['waiting','countdown'])assert.equal(arenaDestination(false,{room_id:'a',status}),null);
  assert.equal(arenaDestination(false,{room_id:'a',status:'playing'}),'./pk-game.html?room=a');
});
test('游戏页直达未开始房间回到准备大厅，结果页刷新仍可展示结算',()=>{
  assert.equal(arenaDestination(true,{room_id:'a',status:'countdown'}),'./pk.html');
  assert.equal(arenaDestination(true,{room_id:'a',status:'finished',result:{outcome:'draw'}}),null);
  assert.equal(arenaDestination(true,null),'./pk.html');
});
test('超时结果明确说明平局和积分，胜负取服务端winner_id',()=>{
  const result={outcome:'draw',reason:'match_timeout',duration_ms:600000,scores:[{user_id:7,delta:0,points:100}]};
  assert.match(arenaResult(result,7).title,/时间结束/);
  assert.match(arenaResult(result,7).description,/平局/);
  assert.match(arenaResult(result,7).description,/100/);
  assert.match(arenaResult({...result,outcome:'win',winner_id:7,reason:'mine_hit'},7).title,/胜利/);
  assert.match(arenaResult({...result,outcome:'win',winner_id:8,reason:'mine_hit'},7).title,/落败/);
});
test('跨页读取遇到503有界重试，换号后不继续请求，业务错误不重试',async()=>{
  let calls=0;const delays=[];
  const value=await readArenaSnapshot(async()=>{if(++calls<3)throw Object.assign(new Error('busy'),{status:503,retryAfter:1});return 'room';},{wait:async ms=>delays.push(ms)});
  assert.equal(value,'room');assert.equal(calls,3);assert.deepEqual(delays,[1000,1000]);
  calls=0;
  await assert.rejects(()=>readArenaSnapshot(async()=>{calls++;throw Object.assign(new Error('busy'),{status:503});},{current:()=>calls===0,wait:async()=>{}}),error=>error.stale===true);
  assert.equal(calls,1);
  calls=0;
  await assert.rejects(()=>readArenaSnapshot(async()=>{calls++;throw Object.assign(new Error('missing'),{status:404});},{wait:async()=>{}}));
  assert.equal(calls,1);
});
