/** v1资源客户端：JSON写请求和独立事件流分离，错误保留服务器资格/解锁原因。 */
import { requestJson } from '../../shared/http.js';

/** 仅接受同源v1资源链接，避免把Cookie请求带向非预期资源。 */
export function api(path, options = {}) {
  const target = path.startsWith('/api/v1/') ? path : `/api/v1/${path}`;
  if (!/^\/api\/v1\/[a-zA-Z0-9/?=&_.%-]+$/.test(target)) throw new Error('资源地址无效。');
  return requestJson(target, { ...options, includeMeta: true });
}

/** 创建型POST的UUID由调用方冻结保存，失败后原键原体重试。 */
export function createResource(path, data, key) {
  return api(path, { method: 'POST', body: data, headers: { 'Idempotency-Key': key } });
}
