/** 同源 JSON 传输：统一超时、Cookie、响应解析；不自动重试业务写请求。 */

export class HttpError extends Error {
  /** detail 保留字段等业务元数据，供各客户端映射自身错误契约。 */
  constructor(response, data) {
    const detail = data?.detail;
    super(typeof detail === 'string' ? detail : detail?.message || '请求失败，请稍后重试。');
    this.status = response.status;
    this.detail = detail;
    this.retryAfter = Number(response.headers?.get('Retry-After')) || 0;
  }
}

/** timeoutMs 默认十二秒；可注入传输/调度器验证超时，凭据始终由 Cookie 管理。 */
export async function requestJson(path, { method = 'GET', body, timeoutMs = 12000,
  fetchImpl = globalThis.fetch, setTimer = globalThis.setTimeout, clearTimer = globalThis.clearTimeout } = {}) {
  const controller = new AbortController();
  const timer = setTimer(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(path, {
      method, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    // 代理可能返回 HTML；保留状态码，让业务包装选择相应错误文案。
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw new HttpError(response, data);
    return data;
  } catch (error) {
    if (error.name === 'AbortError' || error instanceof TypeError) throw new Error('连接失败，请检查网络后重试。');
    throw error;
  } finally {
    clearTimer(timer);
  }
}
