/** 存档协调：注入账号与快照来源，复用既有版本校验及序列化规则。 */
import { loadProgress, saveProgress } from '../progress.js';

/** canSave 阻止恢复中或无棋盘时覆盖存档；不持有任何控制器的可写状态。 */
export function createProgressCoordinator({ storage, getUserId, getSnapshot, canSave, onFailure }) {
  let destroyed = false;
  return {
    /** 每次读取当前身份，换号后不会继续使用旧账号键。 */
    load() { return loadProgress(storage, getUserId()); },
    /** 棋局操作后同步保存，不依赖浏览器必定发出退出事件。 */
    save(atHome = false) {
      if (destroyed || !canSave() || getUserId() == null) return false;
      const saved = saveProgress(storage, getUserId(), getSnapshot(atHome));
      if (!saved) onFailure();
      return saved;
    },
    /** 销毁后禁止旧回调写盘，仍可由测试读取已保存的兼容快照。 */
    destroy() { destroyed = true; },
  };
}
