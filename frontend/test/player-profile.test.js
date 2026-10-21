/** 首页账号成长读取：验证换号隔离、错误不伪造数据、同账号更新不重复请求。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createProfileProgress } from '../src/player-profile.js';

test('换号及退出后，迟到的成长响应不会恢复旧星数', async () => {
  const pending = [], states = [];
  const model = createProfileProgress({ request: () => new Promise(resolve => pending.push(resolve)), onChange: value => states.push(value) });
  model.setUser({ id: 1 }); model.setUser({ id: 2 });
  pending[0]({ xp: 80, level: 1, total_stars: 3, next_level_xp: 90 });
  await Promise.resolve();
  assert.equal(states.at(-1).progression, null);
  pending[1]({ xp: 160, level: 2, total_stars: 6, next_level_xp: 180 });
  await Promise.resolve();
  assert.equal(states.at(-1).progression.total_stars, 6);
  model.setUser(null);
  assert.equal(states.at(-1).status, 'guest');
  assert.equal(states.at(-1).progression, null);
});

test('成长关闭或网络失败显示不可用，同账号头像更新不重置成长', async () => {
  let calls = 0, current;
  const model = createProfileProgress({ request: async () => { calls++; throw Object.assign(new Error(), { status: 404 }); }, onChange: value => { current = value; } });
  model.setUser({ id: 1 }); await Promise.resolve();
  assert.equal(current.status, 'unavailable');
  assert.equal(current.progression, null);
  model.setUser({ id: 1, avatar_id: 5 });
  assert.equal(calls, 1);
});

test('非法成长数据不作为经验或星数展示，认证失效触发身份清理', async () => {
  let expired = 0, current;
  const model = createProfileProgress({ request: async () => ({ xp: -1, level: 1, total_stars: 100, next_level_xp: 90 }), onChange: value => { current = value; } });
  model.setUser({ id: 1 }); await Promise.resolve();
  assert.equal(current.status, 'error');
  const unauthorized = createProfileProgress({ request: async () => { throw Object.assign(new Error(), { status: 401 }); }, onUnauthorized: () => expired++ });
  unauthorized.setUser({ id: 1 }); await Promise.resolve();
  assert.equal(expired, 1);
});

test('接收结算权威成长后，较早读取不得覆盖总数，旧账号事件也不得写回',async()=>{
  const pending=[],states=[];
  const model=createProfileProgress({request:()=>new Promise(resolve=>pending.push(resolve)),onChange:state=>states.push(state)});
  model.setUser({id:1});
  const confirmed={xp:6,level:1,total_stars:3,next_level_xp:90};
  assert.equal(model.accept(1,confirmed),true);
  pending[0]({xp:0,level:1,total_stars:0,next_level_xp:90});await Promise.resolve();
  assert.equal(states.at(-1).progression.total_stars,3);
  model.setUser({id:2});assert.equal(model.accept(1,confirmed),false);
  assert.equal(states.at(-1).progression,null);
  assert.equal(model.accept(2,{...confirmed,xp:-1}),false);
});
