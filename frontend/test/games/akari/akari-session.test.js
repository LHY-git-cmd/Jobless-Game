/** 作用：验证照明变尺寸会话、全亮未满足数字、草稿隔离及终盘重试。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createAkariSession } from '../../../src/games/akari/session.js';

/** 小题盘具有两个独立区域，能分别验证未满足数字和最终通关。 */
function fixture() {
  const memory=new Map(),calls=[];
  let attempt,starts=0,time=10000,offline=false;
  const levels=[{level_id:'akari-v2-001',level_version:1,number:1,rows:3,cols:3}];
  const storage={getItem:key=>memory.get(key),setItem:(key,value)=>memory.set(key,value)};
  /** 只模拟资源协议；照明和通关运算使用正式规则。 */
  async function request(path,options={}) {
    calls.push({path,...structuredClone(options)});
    if(path==='features')return {data:{progression:true}};
    if(path==='levels?game_id=akari')return {data:{items:levels}};
    if(path==='me/level-progress?game_id=akari&limit=50')return {data:{items:[]}};
    if(path==='attempts') {
      starts++;
      attempt={attempt_id:String(starts),level_id:levels[0].level_id,level_version:1,status:'active',
        puzzle:{rows:3,cols:3,map:['..1','###','1..'],checksum:'fixed'},
        timing:{elapsed_ms:0,paused:false,revision:0},
        links:{self:`/api/v1/attempts/${starts}`,completion:`/api/v1/attempts/${starts}/completion`}};
    } else if(path.endsWith('/clock')) {
      attempt.timing={elapsed_ms:time-10000,paused:options.body.paused,revision:attempt.timing.revision+1};
    } else if(path.endsWith('/completion')) {
      if(offline)throw new Error('离线');
      if(options.method==='PUT')attempt.status='completed';
      return {data:{duration_ms:1000,stars:3,best_stars:3,awarded_stars:3,awarded_xp:80,progression:{total_stars:3}}};
    } else if(options.method==='PATCH')attempt.status='abandoned';
    return {data:structuredClone(attempt),etag:'"1"'};
  }
  return {request,storage,calls,now:()=>time,tick:ms=>time+=ms,fail:value=>offline=value,get starts(){return starts;}};
}

test('照明只在显式开始时创建局，同账号恢复灯泡且不同账号隔离',async()=>{
  const f=fixture(),model=createAkariSession({uid:1,...f});
  await model.load();model.select('akari-v2-001');assert.equal(f.starts,0);
  await model.open();await model.toggle(1);assert.equal(model.state.board.bulbs.has(1),true);model.destroy();
  const restored=createAkariSession({uid:1,...f});await restored.load();
  assert.deepEqual([...restored.state.board.bulbs],[1]);assert.equal(f.starts,1);
  const other=createAkariSession({uid:2,...f});await other.load();assert.equal(other.state.attempt,null);
});

test('全亮仍缺数字不可提交，只有满足全部约束才结算',async()=>{
  const f=fixture(),model=createAkariSession({uid:1,...f});await model.load();await model.open();
  await model.toggle(0);await model.toggle(8);
  assert.equal(model.state.board.complete,false);
  assert.equal(f.calls.some(v=>v.path.endsWith('/completion')),false);
  await model.toggle(0);await model.toggle(8);await model.toggle(1);await model.toggle(7);
  assert.equal(model.state.result.stars,3);
  const before=f.calls.length;await model.toggle(1);assert.equal(f.calls.length,before);
});

test('断网后冻结同一终盘，刷新核验资源再重试，不另建尝试',async()=>{
  const f=fixture(),model=createAkariSession({uid:1,...f});await model.load();await model.open();
  await model.toggle(1);f.fail(true);await assert.rejects(model.toggle(7),/离线/);
  assert.equal(model.state.pending,true);await model.toggle(1);assert.deepEqual([...model.state.board.bulbs],[1,7]);
  model.destroy();f.fail(false);const restored=createAkariSession({uid:1,...f});await restored.load();
  assert.equal(restored.state.result.stars,3);assert.equal(f.starts,1);
  const payloads=f.calls.filter(v=>v.path.endsWith('/completion')&&v.method==='PUT').map(v=>v.body);
  assert.deepEqual(payloads,[{bulbs:[1,7]},{bulbs:[1,7]}]);
});

test('规则和隐藏页面暂停独立，全部解除才能修改，重开只清当前局',async()=>{
  const f=fixture(),model=createAkariSession({uid:1,...f});await model.load();await model.open();
  await model.toggle(1);await model.setPaused('rules',true);const frozen=model.elapsed();f.tick(9000);
  await model.toggle(7);assert.equal(model.elapsed(),frozen);assert.equal(model.state.board.bulbs.has(7),false);
  await model.setPaused('hidden',true);await model.setPaused('rules',false);assert.equal(model.state.paused,true);
  await model.setPaused('hidden',false);assert.equal(model.state.paused,false);
  await model.restart();assert.equal(model.state.board.bulbs.size,0);assert.equal(f.starts,2);
});

test('退出后迟到响应不可回填棋盘或发奖',async()=>{
  const f=fixture();let resolve,awards=0;
  const request=async(path,options)=>path.endsWith('/completion')?new Promise(done=>resolve=done):f.request(path,options);
  const model=createAkariSession({uid:1,...f,request,onReward:()=>awards++});await model.load();await model.open();await model.toggle(1);
  const ending=model.toggle(7);await new Promise(done=>setImmediate(done));model.destroy();
  resolve({data:{stars:3,awarded_xp:80}});await ending;
  assert.equal(model.state.attempt,null);assert.equal(model.state.board,null);assert.equal(awards,0);
});

test('入门先练习撤灯，再完成全盘；恢复时丢弃损坏的灯泡草稿',async()=>{
  const f=fixture();
  /** 教学与普通题使用相同终盘规则，只增加本地引导步骤。 */
  const request=async(path,options)=>{
    const result=await f.request(path,options);
    if(result.data?.puzzle)result.data.puzzle.tutorial=true;
    return result;
  };
  const model=createAkariSession({uid:1,...f,request});await model.load();await model.open();
  await model.toggle(1);assert.equal(model.state.tutorialStep,1);
  await model.toggle(1);assert.equal(model.state.tutorialStep,2);
  await model.toggle(1);await model.toggle(7);assert.equal(model.state.result.stars,3);
  model.destroy();
  const key='jobless-journey-v1:akari:1',saved=JSON.parse(f.storage.getItem(key));
  saved.entries['akari-v2-001'].draft.bulbs={bad:true};f.storage.setItem(key,JSON.stringify(saved));
  const restored=createAkariSession({uid:1,...f,request});await restored.load();
  assert.equal(restored.state.board.bulbs.size,0);
});
