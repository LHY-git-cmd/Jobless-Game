/** 本地中间盘只辅助恢复；正式进度以服务器为准，账号/尝试/版本严格隔离。 */
import { createRequestId } from '../../shared/request-id.js';

/** 存储不可用时保留本页内存并报告；写入失败不改变正式奖励。 */
export function createJourneyStore(storage, uid, onError = () => {}) {
  const key = `jobless-journey-v1:${uid}`;
  let value = { entries: {}, starts: {}, selected: null };
  try {
    const parsed = JSON.parse(storage?.getItem(key) || 'null');
    if (parsed?.entries && parsed?.starts) value = parsed;
  } catch { onError('本地进度读取失败，仍可从服务器恢复正式尝试。'); }
  /** 按有限关卡保存本地草稿，不保存正式权益或账号凭据。 */
  function persist() {
    try { storage?.setItem(key, JSON.stringify(value)); }
    catch { onError('本地存储不可用，离开前请提交结果；刷新可能丢失未提交布局。'); }
  }
  /** 绑定版本和内容摘要，旧盘不可套用到另一次或另一个版本。 */
  function identity(attempt) { return `${attempt.attempt_id}:${attempt.level_version}:${attempt.puzzle.checksum}`; }
  return {
    /** 恢复同一次正式尝试的本地草稿，调用方仍须先GET核验。 */
    load(attempt) {
      const entry = value.entries[attempt.level_id];
      return entry?.identity === identity(attempt) ? structuredClone(entry) : null;
    },
    /** 保存尚未上传的棋盘，冻结待提交负载不会被后续绘制覆盖。 */
    save(attempt, draft) {
      const previous = this.load(attempt);
      value.entries[attempt.level_id] = { identity: identity(attempt), draft: structuredClone(draft), pending: previous?.pending ?? null };
      value.selected = attempt.level_id;
      persist();
    },
    /** 网络失败后刷新仍使用同一终盘PUT，直至确认成功或明确放弃。 */
    freeze(attempt, payload) {
      if (!this.load(attempt)) this.save(attempt, {});
      value.entries[attempt.level_id].pending = structuredClone(payload);
      persist();
    },
    /** 服务器确认后解除本地冻结，已确认结果不靠本地奖励重建。 */
    clearPending(attempt) {
      if (this.load(attempt)) { value.entries[attempt.level_id].pending = null; persist(); }
    },
    /** 退出成功后仅清理同一次尝试；重读存储，保留其他标签页的新局和其他关卡。 */
    discard(attempt) {
      try {
        const latest=JSON.parse(storage?.getItem(key)||'null');
        if(latest?.entries&&latest?.starts)value=latest;
      } catch { onError('本地存储读取失败，已退出的对局不能继续。'); }
      if(value.entries[attempt.level_id]?.identity!==identity(attempt))return;
      delete value.entries[attempt.level_id];
      delete value.starts[attempt.level_id];delete value.starts[`restart:${attempt.attempt_id}`];
      if(value.selected===attempt.level_id)value.selected=null;
      persist();
    },
    /** 一个尚未确认的开始动作始终重用原UUID。 */
    startKey(level) { if (!value.starts[level]) { value.starts[level] = createRequestId(); persist(); } return value.starts[level]; },
    /** 仅在开始已确认或确认放弃该请求后换新UUID。 */
    clearStart(level) { delete value.starts[level]; persist(); },
    /** 每账号最后所选关卡，仅作为导航提示。 */
    get selected() { return value.selected; },
    /** 只用作GET定位，必须由服务器核验账号、版本与状态后才能恢复。 */
    reference(level) { return value.entries[level]?.identity?.split(':')[0] || null; },
  };
}
