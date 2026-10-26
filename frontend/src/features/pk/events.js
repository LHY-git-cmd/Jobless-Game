/** SSE只订阅资源通知，不发送业务命令；浏览器断网后自动重连并恢复快照。 */
export function subscribeEvents({ onResource, onReconnect, onState = () => {}, Source = globalThis.EventSource,
  setTimer=globalThis.setTimeout,clearTimer=globalThis.clearTimeout }) {
  let source,active=true,timer=null,failures=0;
  /** 主动重建也覆盖409/503等浏览器不自动重连的响应；始终只有一个源和一个等待器。 */
  function connect(){
    if(!active)return;
    const current=new Source('/api/v1/me/events');source=current;
    const valid=()=>active&&current===source;
    current.addEventListener('resource-updated', event => {
      if(!valid())return;
      try{const message=JSON.parse(event.data);if(typeof message.resource==='string'&&message.resource.startsWith('/api/v1/'))onResource(message.resource);}
      catch{onReconnect();}
    });
    current.addEventListener('resync',()=>{if(valid()){failures=0;onState('实时连接已恢复');onReconnect();}});
    current.addEventListener('open',()=>{if(valid()){failures=0;onState('实时连接正常');}});
    current.addEventListener('error',()=>{
      if(!valid())return;
      current.close();source=null;
      onState('实时连接中断，正在重连。可手动刷新状态。');onReconnect();
      timer=setTimer(()=>{timer=null;connect();},Math.min(5000,1000*++failures));
    });
  }
  connect();
  return { /** 账号变更/离页关闭所有资源，旧事件和等待回调都不能复活连接。 */ close(){active=false;if(timer!==null)clearTimer(timer);timer=null;source?.close();source=null;} };
}
