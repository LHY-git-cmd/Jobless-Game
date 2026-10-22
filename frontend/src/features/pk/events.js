/** SSE只订阅资源通知，不发送业务命令；浏览器断网后自动重连并恢复快照。 */
export function subscribeEvents({ onResource, onReconnect, onState = () => {}, Source = globalThis.EventSource }) {
  const source = new Source('/api/v1/me/events');
  let active = true;
  source.addEventListener('resource-updated', event => {
    if (!active) return;
    try {
      const message = JSON.parse(event.data);
      if (typeof message.resource === 'string' && message.resource.startsWith('/api/v1/')) onResource(message.resource);
    } catch { onReconnect(); }
  });
  source.addEventListener('resync', () => { if (active) { onState('实时连接已恢复'); onReconnect(); } });
  source.addEventListener('open', () => { if (active) onState('实时连接正常'); });
  source.addEventListener('error', () => {
    if (active) { onState('实时连接中断，正在重连。可手动刷新状态。'); onReconnect(); }
  });
  return { /** 账号变更后关闭连接并忽略所有迟到回调。 */ close() { active = false; source.close(); } };
}
