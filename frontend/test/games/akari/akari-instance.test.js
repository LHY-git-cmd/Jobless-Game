/** 验证不同尺寸照明实例互不污染，同时兼容旧题盘调用。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createAkari, inspectAkari, toggleBulb, lightRay, akariCell } from '../../../src/games/akari/rules.js';

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
