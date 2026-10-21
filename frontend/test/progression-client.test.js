/** 验证v1条件请求、账号隔离、冻结重试与事件销毁，不访问真实网络。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { requestJson, HttpError } from '../src/lib/http.js';
import { createJourneyStore } from '../src/progression/journey-store.js';
import { subscribeEvents } from '../src/pk/events.js';

test('v1请求保留If-Match/Idempotency-Key并返回ETag/Location', async () => {
  let sent;
  const value = await requestJson('/api/v1/attempts', { method: 'POST', body: { level_id: 'akari-001' },
    headers: { 'If-Match': '"2"', 'Idempotency-Key': 'same-key' }, includeMeta: true,
    fetchImpl: async (url, options) => { sent = options; return { ok: true, status: 201, json: async () => ({ attempt_id: 'id' }),
      headers: new Headers({ ETag: '"3"', Location: '/api/v1/attempts/id' }) }; } });
  assert.equal(sent.headers['If-Match'], '"2"');
  assert.equal(sent.headers['Idempotency-Key'], 'same-key');
  assert.equal(value.etag, '"3"');
  assert.equal(value.location, '/api/v1/attempts/id');
  assert.deepEqual(value.data, { attempt_id: 'id' });
});

test('Problem Details保留稳定code和逐项资格提示', async () => {
  const problem = { code: 'pk_locked', detail: '需要三项资格', requirements: [{ completed: false }], request_id: 'test' };
  await assert.rejects(requestJson('/api/v1/rooms', { fetchImpl: async () => ({ ok: false, status: 403, headers: new Headers(), json: async () => problem }) }),
    error => error instanceof HttpError && error.code === 'pk_locked' && error.problem.requirements.length === 1);
});

test('本地中间盘按账号/尝试隔离，冻结终盘在刷新后继续原请求', () => {
  const data = new Map();
  const storage = { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) };
  const one = createJourneyStore(storage, 1), two = createJourneyStore(storage, 2);
  const attempt = { attempt_id: 'a', level_id: 'akari-001', level_version: 1, game_id: 'akari', puzzle: { checksum: 'v1' } };
  one.save(attempt, { bulbs: [1, 3] });
  assert.equal(two.load(attempt), null);
  assert.deepEqual(one.load(attempt).draft.bulbs, [1, 3]);
  one.freeze(attempt, { bulbs: [1, 3] });
  assert.deepEqual(createJourneyStore(storage, 1).load(attempt).pending, { bulbs: [1, 3] });
  assert.equal(one.load({ ...attempt, attempt_id: 'b' }), null);
  assert.equal(one.load({ ...attempt, puzzle: { checksum: 'v2' } }), null);
  const first = one.startKey('akari-001');
  assert.equal(createJourneyStore(storage, 1).startKey('akari-001'), first);
  one.clearStart('akari-001');
  assert.notEqual(one.startKey('akari-001'), first);
});

test('退出/换号关闭事件连接后忽略迟到事件', () => {
  let source, calls = 0;
  class FakeSource {
    constructor() { source = this; this.events = {}; }
    addEventListener(name, callback) { this.events[name] = callback; }
    close() { this.closed = true; }
  }
  const subscription = subscribeEvents({ Source: FakeSource, onResource: () => calls++, onReconnect: () => calls++ });
  source.events['resource-updated']({ data: JSON.stringify({ resource: '/api/v1/rooms/a' }) });
  assert.equal(calls, 1);
  subscription.close();
  source.events['resource-updated']({ data: JSON.stringify({ resource: '/api/v1/rooms/a' }) });
  source.events.resync();
  assert.equal(calls, 1);
  assert.equal(source.closed, true);
});
