/** 验证不同尺寸照明实例互不污染，同时兼容旧题盘调用。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createAkari, inspectAkari, toggleBulb, lightRay, akariCell } from '../../../src/games/akari/rules.js';
import { availableAkariStars } from '../../../src/games/akari/controller.js';

test('照明可得星数遵守时间边界，入门固定一星，旧奖励和服务器结果优先', () => {
  const level={level_version:3,max_stars:3,t3_ms:60000,t2_ms:120000};
  const attempt={level_version:3,puzzle:{tutorial:false}};
  assert.deepEqual([0,60000,60001,120000,120001].map(ms=>availableAkariStars(level,attempt,ms)),[3,3,2,2,1]);
  assert.equal(availableAkariStars({...level,max_stars:1},{...attempt,puzzle:{tutorial:true}},999999),1);
  assert.equal(availableAkariStars(level,{...attempt,level_version:2},999999),3);
  assert.equal(availableAkariStars(level,attempt,999999,2),2);
});

test('长方形关卡以实例地图和尺寸运算，不污染默认旧关', () => {
  const game = createAkari({ rows: 2, cols: 3, map: ['.1.', '#.#'] });
  assert.deepEqual(lightRay(0, game), [0]);
  assert.equal(akariCell(1, game), '1');
  assert.equal(toggleBulb(game, 0), true);
  assert.equal(toggleBulb(game, 2), true);
  assert.equal(inspectAkari(game).whiteCount, 3);
  assert.equal(game.complete, false);
  assert.equal(inspectAkari(createAkari()).whiteCount, 66);
});
