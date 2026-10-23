/** 跨模块事件名称集中声明；局部组件交互优先使用显式回调。 */
export const Events = Object.freeze({
  AUTH_CHANGED: 'auth-changed',
  AUTH_EXPIRED: 'auth-expired',
  AUTHORIZED_START: 'authorized-start',
  RECORDS_UPDATED: 'records-updated',
  PROGRESSION_CONFIRMED: 'progression-confirmed',
  ENERGY_CHANGED: 'energy-changed',
  SETTLEMENT_OPENED: 'settlement-opened',
  SETTLEMENT_CLOSED: 'settlement-closed',
  USER_PROFILE_UPDATED: 'user-profile-updated',
});

/** target 可注入页面文档或组件节点，保持原有事件作用范围。 */
export function emit(event, detail, target = document) {
  target.dispatchEvent(new CustomEvent(event, { detail }));
}

/** 返回取消方法，让应用实例统一清理订阅。 */
export function on(event, handler, target = document) {
  target.addEventListener(event, handler);
  return () => off(event, handler, target);
}

/** 解除指定处理器，不干扰同一事件的其他订阅。 */
export function off(event, handler, target = document) {
  target.removeEventListener(event, handler);
}
