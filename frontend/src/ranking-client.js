/** 同源排行榜和挑战客户端：超时保持失败语义，Cookie 决定账号归属。 */

/** 生成 UUID v4；公网 HTTP 不提供 randomUUID 时仍使用安全随机数生成幂等编号。 */
export function createRequestId(cryptoApi = globalThis.crypto) {
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  if (typeof cryptoApi?.getRandomValues !== "function") {
    throw new Error("当前浏览器无法生成请求编号，请更新浏览器后重试。");
  }
  const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
  // 按 UUID v4 规范设置版本和变体，其余位保留浏览器安全随机数。
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export async function rankingRequest(path, { method = "GET", body } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(`/api/${path}`, {
      method, credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: body ? { "Content-Type": "application/json" } : {},
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(typeof data?.detail === "string" ? data.detail : "请求失败，请稍后重试。");
      error.status = response.status;
      throw error;
    }
    if (!data || typeof data !== "object") throw new Error("服务返回异常，请重试。");
    return data;
  } catch (error) {
    if (error.name === "AbortError" || error instanceof TypeError) throw new Error("连接失败，请检查网络后重试。");
    throw error;
  } finally { clearTimeout(timeout); }
}

/** 保存当前账号本轮状态；代数隔离防止离开或换号后的旧响应覆盖新局。 */
export class ChallengeClient {
  /** 注入请求和唯一标识生成器，生产与测试共用同一套状态逻辑。 */
  constructor(request = rankingRequest, uuid = createRequestId) {
    this.request = request;
    this.uuid = uuid;
    this.reset();
  }

  /** 清理内存状态；旧响应只能被丢弃，账号凭据始终只由 Cookie 管理。 */
  reset() {
    this.generation = (this.generation || 0) + 1;
    this.state = null;
    this.startId = null;
    this.restartPayload = null;
    this.pending = new Map();
  }

  /** 导出本轮幂等标识和未确认请求，刷新后仍使用相同负载重试。 */
  snapshot() {
    return { state: this.state, startId: this.startId, restartPayload: this.restartPayload, pending: [...this.pending] };
  }

  /** 恢复本地请求状态并换代，使恢复前的异步回包失效。 */
  restore(snapshot) {
    this.reset();
    this.state = snapshot.state;
    this.startId = snapshot.startId;
    this.restartPayload = snapshot.restartPayload;
    this.pending = new Map(snapshot.pending);
  }

  /** 只读取当前轮次，不通过创建接口覆盖服务器上的其他轮次。 */
  async resume() {
    const generation = this.generation;
    return this.accept(await this.request(`challenges/${this.state.run_id}`), generation);
  }

  /** 对同一创建请求复用幂等 ID，解决服务端成功但响应丢失的情况。 */
  async start() {
    const generation = this.generation;
    this.startId ||= this.uuid();
    const state = await this.request("challenges/start", { method: "POST", body: { request_id: this.startId } });
    return this.accept(state, generation);
  }

  /** 有效进度中的三个关卡全部开放。 */
  canEnter(index) {
    return Boolean(this.state && Number.isInteger(index) && index >= 0 && index < 3);
  }

  /** 当前关保存后启用本关结算操作。 */
  saved(index) { return this.state?.levels[index]?.seconds !== null && this.state?.levels[index]?.seconds !== undefined; }

  /** 服务器回包必须属于仍然有效的本地轮次。 */
  accept(state, generation) {
    if (generation !== this.generation) throw new Error("本轮已离开，请重新开始。");
    if (!state?.run_id || !Array.isArray(state.levels) || state.levels.length !== 3) throw new Error("关卡状态异常，请重新开始。");
    this.state = state;
    return state;
  }

  /** 首次提交冻结完整负载；失败重试不能改变秒数、开发标记或尝试标识。 */
  async complete(index, seconds, development = false) {
    if (!this.canEnter(index)) throw new Error("请先选择有效关卡。");
    const generation = this.generation;
    if (!this.pending.has(index)) this.pending.set(index, {
      category: ["mine", "akari", "sudoku"][index], revision: this.state.revision,
      attempt_id: this.state.levels[index].attempt_id, duration_seconds: seconds, development,
    });
    const state = await this.request(`challenges/${this.state.run_id}/complete`, { method: "POST", body: this.pending.get(index) });
    this.accept(state, generation);
    this.pending.delete(index);
    return state;
  }

  /** 重开失败复用同一标识，成功后仅清理本关的旧提交负载。 */
  async restart(index) {
    if (!this.canEnter(index)) throw new Error("请先选择有效关卡。");
    const generation = this.generation;
    this.restartPayload ||= { category: ["mine", "akari", "sudoku"][index], revision: this.state.revision, request_id: this.uuid() };
    const state = await this.request(`challenges/${this.state.run_id}/restart`, { method: "POST", body: this.restartPayload });
    this.accept(state, generation);
    this.restartPayload = null;
    this.pending.delete(index);
    return state;
  }
}
