/** 同源排行榜读取：超时保持失败语义，Cookie决定账号归属；旧挑战独立归档。 */

import { requestJson, HttpError } from '../../shared/http.js';

export { createRequestId } from '../../shared/request-id.js';

/** 排行接口保留原有对象校验和非字符串 detail 的通用错误文案。 */
export async function rankingRequest(path, options = {}) {
  try {
    const data = await requestJson(`/api/${path}`, options);
    if (!data || typeof data !== 'object') throw new Error('服务返回异常，请重试。');
    return data;
  } catch (error) {
    if (error instanceof HttpError) {
      throw Object.assign(new Error(typeof error.detail === 'string' ? error.detail : '请求失败，请稍后重试。'), { status: error.status });
    }
    throw error;
  }
}

