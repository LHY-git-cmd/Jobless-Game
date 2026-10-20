/** 公共 DOM 与事件契约：保留语义名称、查询范围及可清理订阅。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { cacheIds, $, $$ } from '../src/lib/dom.js';
import { Events, emit, on, off } from '../src/lib/events.js';

test('固定节点支持语义映射与 ID 数组，局部根节点不泄漏到全局', () => {
  const board = {}, root = { getElementById: id => id === 'game-board' ? board : null };
  assert.deepEqual(cacheIds({ board: 'game-board', optional: 'absent' }, root), { board, optional: null });
  assert.deepEqual(cacheIds(['game-board'], root), { 'game-board': board });
  const local = { querySelector: selector => [selector, board], querySelectorAll: () => new Set([board]) };
  assert.deepEqual($('.cell', local), ['.cell', board]);
  assert.deepEqual($$('.cell', local), [board]);
});

test('共享事件常量冻结，订阅支持取消及显式目标，不影响其他监听', () => {
  assert.equal(Object.isFrozen(Events), true);
  const target = new EventTarget(), received = [];
  const listener = event => received.push(event.detail);
  const unsubscribe = on(Events.AUTH_CHANGED, listener, target);
  emit(Events.AUTH_CHANGED, { user: { id: 1 } }, target);
  unsubscribe();
  emit(Events.AUTH_CHANGED, { user: null }, target);
  assert.deepEqual(received, [{ user: { id: 1 } }]);
  on(Events.RECORDS_UPDATED, listener, target);
  off(Events.RECORDS_UPDATED, listener, target);
  emit(Events.RECORDS_UPDATED, 'ignored', target);
  assert.equal(received.length, 1);
});
