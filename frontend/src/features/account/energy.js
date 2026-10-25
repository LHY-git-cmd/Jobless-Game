/** 账号体力：显示服务器余额和恢复倒计时，修订号防止旧快照回填。 */
import { requestJson } from '../../shared/http.js';
import { Events } from '../../shared/events.js';

/** 注入时钟仅供显示；不依据倒计时自行增加余额。 */
export function createEnergyModel({request=()=>requestJson('/api/v1/me/energy'),now=Date.now,onChange=()=>{},onUnauthorized=()=>{}}={}){
  let uid=null,epoch=0,busy=false,dead=false,value=null,anchor=now(),asOf=-Infinity,retryAt=0;
  /** 发布当前账号状态，读取失败不会被伪装成0体力。 */
  function publish(status){if(!dead)onChange({userId:uid,status,energy:value});}
  /** 只接受有界整数、合法修订与可解析服务器时间。 */
  function valid(data){return data&&Number.isInteger(data.capacity)&&data.capacity>0&&data.capacity<=10&&Number.isInteger(data.current)&&data.current>=0&&data.current<=data.capacity&&Number.isSafeInteger(data.revision)&&data.revision>=0&&Number.isFinite(Date.parse(data.server_now))&&(data.next_recovery_at===null||Number.isFinite(Date.parse(data.next_recovery_at)));}
  /** 同修订按服务器取样时间排序，防止历史完成快照带回旧倒计时。 */
  function accept(userId,data){
    if(dead||uid===null||uid!==userId||!valid(data))return false;
    const timestamp=Date.parse(data.server_now);
    if(value&&(data.revision<value.revision||data.revision===value.revision&&timestamp<asOf))return false;
    value=structuredClone(data);asOf=timestamp;anchor=now();publish('ready');return true;
  }
  /** 每次只保持一个读取；迟到响应必须同时通过账号与修订检查。 */
  async function refresh(){
    if(dead||uid===null||busy)return;
    const stamp=epoch,userId=uid;busy=true;
    try{const data=await request();if(dead||stamp!==epoch)return;if(!valid(data))throw new Error('体力数据无效');retryAt=0;accept(userId,data);}
    catch(error){if(!dead&&stamp===epoch){retryAt=now()+30000;publish('error');if(error.status===401)onUnauthorized();}}
    finally{if(stamp===epoch)busy=false;}
  }
  /** 服务器锚点加本地经过时长，系统时间误差不改变实际体力。 */
  function remaining(){if(!value?.next_recovery_at)return null;return Math.max(0,Math.ceil((Date.parse(value.next_recovery_at)-asOf-Math.max(0,now()-anchor))/1000));}
  return {
    /** 换号清空快照和在途读取资格。 */
    setUser(user){const next=user?.id??null;if(next===uid)return;uid=next;epoch++;busy=false;value=null;asOf=-Infinity;publish(next===null?'guest':'loading');if(next!==null)void refresh();},
    refresh,accept,remaining,
    /** 每秒只更新文字，恢复边界至多发起一个在途读取。 */
    tick(){if(dead||uid===null)return;if(remaining()===0&&now()>=retryAt)void refresh();else if(value)publish('ready');},
    /** 卸载后迟到请求不得更新新页面。 */
    destroy(){dead=true;epoch++;uid=null;value=null;},
  };
}

/** 直接绑定头像旁的体力，独立于星星汇聚动画更新。 */
export function initEnergyDisplay(host){
  const display=document.createElement('div');display.className='player-energy';display.hidden=true;
  display.innerHTML='<span class="player-energy-main"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 10-12h-7l1-8Z"/></svg><strong>— / 10</strong><span>体力</span></span><small></small>';
  // 倒计时逐秒变化不应持续打断读屏，余额变化仍可通过区域标签读取。
  display.setAttribute('role','group');display.setAttribute('aria-label','账号体力');host.append(display);
  const model=createEnergyModel({onUnauthorized:()=>document.dispatchEvent(new CustomEvent(Events.AUTH_EXPIRED)),onChange:state=>{
    display.hidden=state.userId===null;
    display.querySelector('strong').textContent=state.energy?`${state.energy.current} / ${state.energy.capacity}`:'— / 10';
    const seconds=model.remaining();
    display.querySelector('small').textContent=state.status==='error'?'体力暂不可用':!state.energy?'读取中…':seconds===null?'体力已满':seconds===0?'正在恢复…':`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')} 后恢复1点`;
  }});
  /** 只接受当前账号的开局、结算或重开快照。 */
  function changed(event){model.accept(event.detail?.userId,event.detail?.energy);}
  /** 页面返回及重新可见时核对一次，隐藏页面不额外轮询。 */
  function visible(){if(!document.hidden)void model.refresh();}
  document.addEventListener(Events.ENERGY_CHANGED,changed);document.addEventListener('visibilitychange',visible);window.addEventListener('pageshow',visible);
  const timer=setInterval(()=>{if(!document.hidden)model.tick();},1000);
  window.addEventListener('pagehide',event=>{if(event.persisted)return;clearInterval(timer);model.destroy();document.removeEventListener(Events.ENERGY_CHANGED,changed);document.removeEventListener('visibilitychange',visible);window.removeEventListener('pageshow',visible);},{once:true});
  return model;
}
