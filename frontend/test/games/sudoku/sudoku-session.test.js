/** 作用：先验证数独正式会话的开始、草稿、暂停、结算重试和身份隔离。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createSudokuSession } from '../../../src/games/sudoku/session.js';

/** 用16格协议夹具减少测试噪声，真实服务端另有81格契约测试。 */
function fixture(){
  const memory=new Map(),calls=[];
  let time=10000,attempt,starts=0,fail=false;
  const answer=[1,2,3,4,3,4,1,2,2,1,4,3,4,3,2,1];
  const levels=[{level_id:'sudoku-easy',level_version:1,difficulty:'easy',max_stars:3}];
  const storage={getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v)};
  /** 请求响应复制，防止被测会话意外修改服务器夹具。 */
  async function request(path,options={}){
    calls.push({path,...options});
    if(path==='features')return {data:{progression:true}};
    if(path==='levels?game_id=sudoku')return {data:{items:levels}};
    if(path==='me/level-progress?game_id=sudoku&limit=50')return {data:{items:[]}};
    if(path==='attempts'){
      starts++; attempt={attempt_id:String(starts),level_id:'sudoku-easy',level_version:1,status:'active',
        started_at:new Date(time).toISOString(),puzzle:{rows:4,cols:4,values:answer.map((v,i)=>i===1||i===6?0:v),checksum:'p'},
        board:{outcome:'active'},timing:{elapsed_ms:0,paused:false,revision:0},
        links:{self:'/api/v1/attempts/'+starts,completion:'/api/v1/attempts/'+starts+'/completion'}};
    }else if(path.endsWith('/clock')){
      attempt.timing={elapsed_ms:time-10000,paused:options.body.paused,revision:attempt.timing.revision+1};
    }else if(path.endsWith('/completion')){
      if(fail)throw new Error('离线');
      if(options.method==='GET'&&attempt.status!=='completed')throw Object.assign(new Error('未完成'),{status:404});
      attempt.status='completed';attempt.ended_at=new Date(time).toISOString();
      return {data:{stars:3,best_stars:3,awarded_stars:3,awarded_xp:6,duration_ms:5000,progression:{total_stars:3}}};
    }else if(options.method==='PATCH')attempt.status='abandoned';
    return {data:structuredClone(attempt),etag:'"1"'};
  }
  return {request,storage,calls,now:()=>time,tick:ms=>time+=ms,get starts(){return starts;},fail:v=>fail=v};
}

test('select does not start; edits and notes restore from the same account and attempt',async()=>{
  const f=fixture(),m=createSudokuSession({uid:1,...f});await m.load();m.select('sudoku-easy');assert.equal(f.starts,0);
  await m.open();m.choose(1);m.toggleNotes();await m.input(2);assert.equal(m.state.grid.notes[1],2);
  m.destroy();const restored=createSudokuSession({uid:1,...f});await restored.load();
  assert.equal(f.starts,1);assert.equal(restored.state.grid.notes[1],2);assert.equal(restored.state.grid.notesMode,true);
  const other=createSudokuSession({uid:2,...f});await other.load();assert.equal(other.state.attempt,null);
});

test('nested pause freezes inputs until every reason is removed',async()=>{
  const f=fixture(),m=createSudokuSession({uid:1,...f});await m.load();await m.open();m.choose(1);
  await m.setPaused('rules',true);const frozen=m.elapsed();f.tick(9000);await m.input(2);
  assert.equal(m.elapsed(),frozen);assert.equal(m.state.grid.values[1],0);
  await m.setPaused('hidden',true);await m.setPaused('rules',false);assert.equal(m.state.paused,true);
  await m.setPaused('hidden',false);assert.equal(m.state.paused,false);
});

test('manual pause survives hidden pages and reload until explicitly resumed',async()=>{
  const f=fixture(),m=createSudokuSession({uid:1,...f});await m.load();await m.open();
  await m.setPaused('manual',true);assert.equal(m.state.manualPaused,true);
  await m.setPaused('hidden',true);await m.setPaused('hidden',false);
  assert.equal(m.state.paused,true);m.destroy();
  const restored=createSudokuSession({uid:1,...f});await restored.load();
  assert.equal(restored.state.manualPaused,true);assert.equal(restored.state.paused,true);
  await restored.setPaused('manual',false);assert.equal(restored.state.paused,false);
  await restored.setPaused('manual',true);await restored.restart();
  assert.equal(restored.state.manualPaused,false);assert.equal(restored.state.paused,false);
});

test('offline final submission persists exact payload and retries without a new attempt',async()=>{
  const f=fixture();let rewards=0;
  const m=createSudokuSession({uid:1,...f,onReward:()=>rewards++});await m.load();await m.open();
  m.choose(1);await m.input(2);m.choose(6);f.fail(true);await assert.rejects(m.input(1),/离线/);
  assert.equal(m.state.pending,true);const frozen=m.elapsed();f.tick(9000);assert.equal(m.elapsed(),frozen);
  m.destroy();f.fail(false);const restored=createSudokuSession({uid:1,...f,onReward:()=>rewards++});await restored.load();
  assert.equal(restored.state.result.awarded_xp,6);assert.equal(f.starts,1);assert.equal(rewards,1);
  const submissions=f.calls.filter(v=>v.path.endsWith('/completion')&&v.method==='PUT');
  assert.equal(submissions.length,2);assert.deepEqual(submissions[0].body,submissions[1].body);
});

test('destroy ignores late responses and prevents old account writes',async()=>{
  const f=fixture();let release;
  const m=createSudokuSession({uid:1,...f,request:async(path,options)=>{
    if(path==='attempts')await new Promise(resolve=>release=resolve);return f.request(path,options);
  }});
  await m.load();const work=m.open();await new Promise(resolve=>setTimeout(resolve,0));m.destroy();release();await work;
  assert.equal(m.state.attempt,null);
});

test('retry resumes a server clock paused while the final tutorial response was in flight',async()=>{
  const f=fixture();let paused=false,first=true;
  const m=createSudokuSession({uid:1,...f,request:async(path,options)=>{
    if(path.endsWith('/completion')&&options?.method==='PUT'){
      if(first){first=false;paused=true;}
      if(paused)throw Object.assign(new Error('游戏已暂停'),{code:'attempt_paused'});
    }
    if(path.endsWith('/clock')&&options.body.paused===false)paused=false;
    return f.request(path,options);
  }});
  await m.load();await m.open();m.choose(1);await m.input(2);m.choose(6);
  await assert.rejects(m.input(1),/暂停/);await m.complete();
  assert.equal(m.state.result.awarded_xp,6);assert.equal(f.starts,1);
});
