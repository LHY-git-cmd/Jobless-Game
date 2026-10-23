/** 作用：先验证星级时间边界、冻结终盘、动画防重/取消与手机收敛后同步。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { availableMineStars, createStarCollection } from '../../../src/games/mine/stars.js';

const level={max_stars:3,t3_ms:75000,t2_ms:150000};
test('可得星数遵守含等号的时间边界，教学固定1星，失败0星',()=>{
  assert.deepEqual([0,75000,75001,150000,150001].map(ms=>availableMineStars(level,ms)),[3,3,2,2,1]);
  assert.equal(availableMineStars({...level,max_stars:1},9999999),1);
  assert.equal(availableMineStars(level,100,'lost'),0);
  assert.equal(availableMineStars(level,999999,'won',3),3);
});

/** 最小动画夹具只记录飞行数量和结束顺序，不模拟评分或账号奖励。 */
function fixture({reduced=false,visible=true}={}){
  const flights=[],completed=[],removed=[];
  const dom={body:{append(){}},createElement:()=>({className:'',style:{},setAttribute(){},append(){},
    remove(){removed.push(this);},animate(){let resolve;const finished=new Promise(done=>resolve=done);const effect={finished,cancel:resolve,finish:resolve};flights.push(effect);return effect;}})};
  const view={innerWidth:375,innerHeight:812,matchMedia:()=>({matches:reduced})};
  const target={getBoundingClientRect:()=>({left:20,top:visible?30:-200,width:60,height:24})};
  const source={getBoundingClientRect:()=>({left:100,top:visible?400:-400,width:80,height:30})};
  const collector=createStarCollection({dom,view,onComplete:value=>completed.push(value)});
  const reward={key:'attempt-1',userId:1,progression:{total_stars:8,xp:12,level:1,next_level_xp:90},awardedStars:2,source,target};
  return {collector,reward,flights,completed,removed};
}

test('只飞本次新增星，全部抵达才同步服务器总数，同一尝试不重放',async()=>{
  const f=fixture();const pending=f.collector.play(f.reward);
  assert.equal(f.flights.length,2);assert.equal(f.completed.length,0);
  f.flights[0].finish();await Promise.resolve();assert.equal(f.completed.length,0);
  f.flights[1].finish();await pending;
  assert.equal(f.completed[0].progression.total_stars,8);
  await f.collector.play(f.reward);assert.equal(f.flights.length,2);assert.equal(f.completed.length,1);
});

test('重复成绩或减少动画设置直接同步，不产生飞行对象',async()=>{
  const f=fixture({reduced:true});await f.collector.play(f.reward);
  assert.equal(f.flights.length,0);assert.equal(f.completed.length,1);
  const zero=fixture();await zero.collector.play({...zero.reward,awardedStars:0});
  assert.equal(zero.flights.length,0);assert.equal(zero.completed.length,1);
});

test('返回选关取消飞行但保留已确认奖励，换号取消不能写回旧身份',async()=>{
  const f=fixture();const pending=f.collector.play(f.reward);f.collector.cancel();await pending;
  assert.equal(f.completed.length,1);assert.equal(f.completed[0].userId,1);
  const changed=fixture();const old=changed.collector.play(changed.reward);changed.collector.cancel(false);await old;
  assert.equal(changed.completed.length,0);assert.ok(changed.removed.length);
});

test('手机端顶部总数在视野外时仍能完成收集，不滚动玩家页面',async()=>{
  const f=fixture({visible:false});const pending=f.collector.play(f.reward);
  assert.equal(f.flights.length,2);f.flights.forEach(effect=>effect.finish());await pending;
  assert.equal(f.completed[0].progression.total_stars,8);
});
