/** 历史单关挑战客户端，仅用于旧实现及其兼容回归。 */
import { rankingRequest } from '../../features/ranking/client.js';
import { createRequestId } from '../../shared/request-id.js';

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
