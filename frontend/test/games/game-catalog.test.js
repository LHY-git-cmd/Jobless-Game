/** 游戏选关入口契约：三个游戏保持独立地址，旧深链接回到对应新版空目录。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { gameFromSearch, gameLink, GAME_PAGES } from '../../src/games/catalog.js';

test('三张游戏卡片使用各自的新版选关地址，刷新保留游戏类型', () => {
  for (const game of ['mine', 'akari', 'sudoku']) {
    const target = gameLink(game);
    assert.equal(gameFromSearch(new URL(target, 'https://game.example/').search).id, game);
    assert.equal(GAME_PAGES[game].id, game);
  }
});

test('旧资格关链接仅解析游戏，不恢复旧关卡；非法参数回退照明目录', () => {
  assert.equal(gameFromSearch('?level=mine-beginner-001').id, 'mine');
  assert.equal(gameFromSearch('?level=sudoku-beginner-001').id, 'sudoku');
  assert.equal(gameFromSearch('?level=akari-004').id, 'akari');
  assert.equal(gameFromSearch('?game_id=unknown').id, 'akari');
  assert.equal(gameFromSearch('?game_id=mine&level=akari-004').id, 'mine');
  assert.equal(gameFromSearch('?game_id=__proto__').id, 'akari');
});
