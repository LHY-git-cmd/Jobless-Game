/** 作用：验证竞技跳转边界和服务端结果说明，不依赖浏览器时钟判胜。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { arenaDestination, arenaResult, readArenaSnapshot, roomWriteVersion, toggleArenaReadiness } from '../../../src/features/pk/flow.js';

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

/** 每个快照都携带服务端房间修订，模拟gzip代理只把响应ETag改为弱标签。 */
function snapshot(revision=7,ready=false,status='waiting'){
  return {data:{room_id:'room-a',revision,status,members:[{is_me:true,ready},{is_me:false,ready:false}],links:{readiness:'/api/v1/rooms/room-a/members/me/readiness'}},etag:`W/"${revision}"`};
}

test('准备使用与房间JSON一致的强修订，兼容压缩弱标签且不改变普通强标签',()=>{
  for(const revision of [0,7,25]){
    const value=snapshot(revision);
    assert.equal(roomWriteVersion(value),`"${revision}"`);
    value.etag=`"${revision}"`;assert.equal(roomWriteVersion(value),value.etag);
  }
});

test('缺失、伪造或与JSON不一致的版本不能发起准备写请求',async()=>{
  for(const revision of [undefined,-1,'7',7.5,8,Number.MAX_SAFE_INTEGER+1]){
    const value=snapshot();value.data.revision=revision;let writes=0;
    await assert.rejects(()=>toggleArenaReadiness({roomId:'room-a',request:async(path,options)=>{if(options?.method)writes++;return value;}}),/核验/);
    assert.equal(writes,0);
  }
  for(const etag of [null,'','"8"','W/"8"','W/"007"','opaque']){
    const value=snapshot();value.etag=etag;assert.throws(()=>roomWriteVersion(value),/核验/);
  }
});

test('压缩快照准备和取消准备均带正确版本，不把W/原样提交',async()=>{
  for(const ready of [false,true]){
    const calls=[];
    const result=await toggleArenaReadiness({roomId:'room-a',request:async(path,options)=>{calls.push({path,...options});return snapshot(7,ready);}});
    assert.equal(result.data.room_id,'room-a');
    assert.deepEqual(calls,[{path:'rooms/room-a'},{path:'/api/v1/rooms/room-a/members/me/readiness',method:'PUT',body:{ready:!ready},headers:{'If-Match':'"7"'}}]);
  }
});

test('对手并发准备导致412时重读新版本，只重放本人原准备意图',async()=>{
  const writes=[];let reads=0;
  await toggleArenaReadiness({roomId:'room-a',request:async(path,options)=>{
    if(!options?.method)return snapshot(++reads===1?7:8);
    writes.push(options);
    if(writes.length===1)throw Object.assign(new Error('状态已更新'),{status:412});
    return snapshot(9,true,'countdown');
  }});
  assert.deepEqual(writes.map(v=>v.body.ready),[true,true]);
  assert.deepEqual(writes.map(v=>v.headers['If-Match']),['"7"','"8"']);
});

test('冲突后本人已准备或已倒计时，不再反向取消；第二次冲突仍向调用方报告',async()=>{
  for(const status of ['waiting','countdown']){
    let reads=0,writes=0;
    const value=await toggleArenaReadiness({roomId:'room-a',request:async(path,options)=>{
      if(!options?.method)return ++reads===1?snapshot():snapshot(8,true,status);
      writes++;throw Object.assign(new Error('冲突'),{status:412});
    }});
    assert.equal(writes,1);assert.equal(value.data.members[0].ready,true);
  }
  let writes=0;
  await assert.rejects(()=>toggleArenaReadiness({roomId:'room-a',request:async(path,options)=>{
    if(!options?.method)return snapshot();writes++;throw Object.assign(new Error('冲突'),{status:412});
  }}),error=>error.status===412);
  assert.equal(writes,2);
});
