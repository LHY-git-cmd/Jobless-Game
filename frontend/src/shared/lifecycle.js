/** 应用实例资源作用域：统一清理监听、订阅和调度器，避免刷新模拟重复初始化。 */
export function createScope() {
  const cleanups = [];
  let disposed = false;
  return {
    /** 清理操作在销毁时逆序执行；已销毁作用域立即释放新资源。 */
    add(cleanup) {
      if (disposed) cleanup();
      else cleanups.push(cleanup);
      return cleanup;
    },
    /** 绑定到明确目标，保留捕获等原生事件选项。 */
    listen(target, event, handler, options) {
      target.addEventListener(event, handler, options);
      this.add(() => target.removeEventListener(event, handler, options));
    },
    /** 配置请求等异步结果只允许回到仍存活的实例。 */
    guard(handler) {
      return (...args) => { if (!disposed) return handler(...args); };
    },
    /** 多次销毁只释放一次，先标记再清理以阻止清理过程中的旧回调。 */
    dispose() {
      if (disposed) return;
      disposed = true;
      for (const cleanup of cleanups.splice(0).reverse()) cleanup();
    },
  };
}
