/** 作用：在界面实现前验证显式开始、服务端权威、续玩、教学及网络重试。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createMineSession } from '../src/games/mine/session.js';

/** 最小接口夹具只模拟协议，不替代后端规则测试。 */
function fixture() {
  const calls = [], memory = new Map();
  let starts = 0, completionFails = false, attempt,clockTime=Date.parse('2026-10-22T00:00:00Z'),clockElapsed=0,clockPaused=false,clockRevision=0;
  const levels = ['easy','tutorial'].map((difficulty,i)=>({ level_id:`mine-test-${difficulty}`,difficulty,level_version:1,
    rows:i?5:10,cols:i?5:10,mine_count:i?3:10,name:difficulty,star_xp:i?[2]:[2,4,6],t3_ms:75000,t2_ms:150000 }));
  const storage = {getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v)};
  /** 开局在服务端存活，失败重试使用相同资源与键。 */
  async function request(path, options={}) {
    calls.push({path,...options});
    if(path==='features') return {data:{progression:true}};
    if(path==='levels?game_id=mine') return {data:{items:levels}};
    if(path==='me/level-progress?game_id=mine&limit=50') return {data:{items:levels.map(v=>({level_id:v.level_id,best_stars:0,current_attempt:null}))}};
    if(path==='attempts') {
      starts++;
      const level=levels.find(v=>v.level_id===options.body.level_id);
      attempt={attempt_id:'a',level_id:level.level_id,level_version:1,revision:0,status:'active',
        started_at:'2026-10-22T00:00:00Z',server_now:new Date(clockTime).toISOString(),ended_at:null,
        timing:{elapsed_ms:0,paused:false,paused_ms:0,revision:0},
        puzzle:{rows:level.rows,cols:level.cols,mine_count:level.mine_count,checksum:'c',tutorial:level.difficulty==='tutorial'},
        board:{revealed:[],outcome:'active',...(level.difficulty==='tutorial'?{tutorial_step:0}:{})},links:{self:'/api/v1/attempts/a',completion:'/api/v1/attempts/a/completion'}};
    } else if(path.endsWith('/clock')) {
      clockElapsed+=clockPaused?0:clockTime-Date.parse(attempt.server_now);clockPaused=options.body.paused;clockRevision++;
      attempt.server_now=new Date(clockTime).toISOString();attempt.timing={elapsed_ms:clockElapsed,paused:clockPaused,paused_ms:0,revision:clockRevision};
    } else if(path.endsWith('/reveals/0')) {
      attempt=structuredClone(attempt); attempt.board.revealed=[{index:0,value:1}];
      if(attempt.puzzle.tutorial) attempt.board.tutorial_step=1;
      else {attempt.board.outcome='won'; attempt.ended_at='2026-10-22T00:00:30Z';}
    } else if(path.endsWith('/tutorial-actions/number')) attempt.board.tutorial_step=2;
    else if(path.endsWith('/tutorial-actions/flag')) attempt.board.tutorial_step=3;
    else if(path.endsWith('/completion')) {
      if(completionFails) throw new Error('离线');
      attempt.status='completed';
      return {data:{stars:3,best_stars:3,awarded_stars:3,awarded_xp:6,duration_ms:30000}};
    }
    return {data:structuredClone(attempt),etag:'"1"'};
  }
  return {request,storage,calls,levels,get starts(){return starts;},failCompletion(v){completionFails=v;},now:()=>clockTime,tick(ms){clockTime+=ms;}};
}

test('切换难度不创建尝试，点击开始才发POST，标记不发揭格请求',async()=>{
  const f=fixture(), model=createMineSession({uid:1,...f});
  await model.load(); model.select('mine-test-tutorial'); model.select('mine-test-easy');
  assert.equal(f.starts,0);
  await model.open(); assert.equal(f.starts,1);
  model.choose(4); await model.mark();
  assert.deepEqual(model.state.flags,[4]);
  assert.equal(f.calls.filter(v=>v.path.includes('/reveals/')).length,0);
  assert.ok(f.storage.getItem('jobless-journey-v1:1'));
});

test('通关但结算离线时保留终盘，重试用空体PUT，不重开不重复揭格',async()=>{
  const f=fixture();let rewards=0;
  const model=createMineSession({uid:1,...f,onReward:()=>rewards++});
  await model.load();await model.open();model.choose(0); f.failCompletion(true);
  await assert.rejects(model.reveal(),/离线/);
  assert.equal(model.state.attempt.board.outcome,'won');
  assert.equal(model.state.result,null);
  f.failCompletion(false);await model.complete();
  assert.equal(model.state.result.awarded_xp,6);
  assert.equal(rewards,1);assert.equal(f.starts,1);
  assert.equal(f.calls.filter(v=>v.path.includes('/reveals/')).length,1);
  assert.deepEqual(f.calls.filter(v=>v.path.endsWith('/completion')).map(v=>v.body),[{},{}]);
});

test('刷新通过服务端GET恢复同一尝试和旗标，不重新开始',async()=>{
  const f=fixture();const first=createMineSession({uid:1,...f});
  await first.load();await first.open();first.choose(4);await first.mark(); first.destroy();
  const second=createMineSession({uid:1,...f});await second.load();
  assert.equal(f.starts,1);assert.equal(second.state.attempt.attempt_id,'a');
  assert.deepEqual(second.state.flags,[4]);
});

test('教学必须先揭安全格、确认数字、标记目标，再自由排雷',async()=>{
  const f=fixture(),model=createMineSession({uid:1,...f});await model.load();model.select('mine-test-tutorial');await model.open();
  model.choose(4);await model.reveal();
  assert.equal(f.calls.filter(v=>v.path.includes('/reveals/')).length,0);
  model.choose(0);await model.reveal();assert.equal(model.state.attempt.board.tutorial_step,1);
  await model.acknowledge();model.choose(6);await model.mark();
  assert.equal(model.state.attempt.board.tutorial_step,3);assert.ok(model.state.flags.includes(6));
});

test('销毁后迟到的响应不写回棋盘或存档',async()=>{
  const f=fixture();let release;
  const model=createMineSession({uid:1,...f,request:async(path,options)=>{
    if(path==='attempts') await new Promise(resolve=>release=resolve);
    return f.request(path,options);
  }});
  await model.load();const pending=model.open();await Promise.resolve();model.destroy();release();await pending;
  assert.equal(model.state.attempt,null);
});

test('规则和隐藏分别暂停，嵌套暂停全部解除才继续，暂停不能揭格',async()=>{
  const f=fixture(),model=createMineSession({uid:1,...f});await model.load();await model.open();
  f.tick(10000);assert.equal(model.elapsed(),10000);
  await model.setPaused('rules',true);const frozen=model.elapsed();f.tick(90000);
  assert.equal(model.elapsed(),frozen);model.choose(4);assert.equal(model.state.cell,null);
  await model.setPaused('hidden',true);await model.setPaused('rules',false);
  f.tick(5000);assert.equal(model.elapsed(),frozen);
  await model.setPaused('hidden',false);f.tick(3000);assert.equal(model.elapsed(),frozen+3000);
  assert.equal(f.calls.filter(v=>v.path.endsWith('/clock')&&v.body.paused).length,1);
});

test('暂停请求失败后保留冻结和原请求编号，恢复网络可原键重试',async()=>{
  const f=fixture();let failed=true;
  const model=createMineSession({uid:1,...f,request:async(path,options)=>{
    if(path.endsWith('/clock')&&options.body.paused&&failed){failed=false;throw new Error('离线');}
    return f.request(path,options);
  }});
  await model.load();await model.open();f.tick(2000);
  await assert.rejects(model.setPaused('rules',true),/离线/);f.tick(10000);
  assert.equal(model.elapsed(),2000);assert.equal(model.state.paused,true);
  await model.setPaused('rules',false);assert.equal(model.state.paused,false);
});
