/** 全站可见账号在线租约及对战邀请；跨标签合并读取，不使用每秒数据库轮询。 */
import { requestJson } from '../../shared/http.js';

/** 已认证页面每25秒续在线、15秒查看邀请；仅竞技功能开放时运行。 */
export function initArenaPresence(){
  let user=null,epoch=0,dead=false,enabled=false,timer=null,inFlight=false;
  const tab=crypto.randomUUID();let dialog=null,current=null;
  /** 离开/隐藏只释放本标签租约，让其他可见标签及时接管，不篡改其他账号租约。 */
  function release(){
    if(!user)return;
    try{const key=`jobless-arena-presence:${user.id}`,value=JSON.parse(localStorage.getItem(key)||'null');if(value?.tab===tab)localStorage.removeItem(key);}catch{/* 存储受限仍由短期租约自然过期。 */}
  }
  /** 共享localStorage租约使同账号多个标签只由一个可见页面心跳。 */
  function lead(){
    try{
      const key=`jobless-arena-presence:${user.id}`,value=JSON.parse(localStorage.getItem(key)||'null');
      if(value&&value.until>Date.now()&&value.tab!==tab)return false;
      localStorage.setItem(key,JSON.stringify({tab,until:Date.now()+12000}));return true;
    }catch{return true;}
  }
  /** 原生邀请弹窗复用账号公开资料；接受后进入竞技页恢复实际房间。 */
  function show(item){
    if(location.pathname.endsWith('/pk.html')||document.querySelector('dialog[open]'))return;
    if(!dialog){
      dialog=document.createElement('dialog');dialog.className='auth-dialog';
      dialog.setAttribute('aria-labelledby','arena-incoming-title');
      dialog.innerHTML='<div class="auth-card"><h2 id="arena-incoming-title">对战邀请</h2><p data-invite-text></p><p data-invite-error role="status"></p><div class="journey-actions"><button type="button" data-invite-decline>暂不接受</button><button type="button" data-invite-accept>接受邀请</button></div></div>';
      document.body.append(dialog);
      for(const accept of [false,true])dialog.querySelector(accept?'[data-invite-accept]':'[data-invite-decline]').addEventListener('click',()=>void respond(accept));
    }
    current=item;
    dialog.querySelector('[data-invite-error]').textContent='';
    dialog.querySelectorAll('button').forEach(button=>button.disabled=false);
    dialog.querySelector('[data-invite-text]').textContent=`${item.sender_name} 邀请你进行${{mine:'扫雷',akari:'照明',sudoku:'数独'}[item.game_id]}对战。`;
    if(!dialog.open)dialog.showModal();
  }
  /** 每次业务操作携带当前账号代数，换号后的迟到响应不能导航或写回新账号。 */
  async function respond(accept){
    if(!current||!user)return;
    const stamp=epoch,item=current;
    const buttons=[...dialog.querySelectorAll('button')];buttons.forEach(x=>x.disabled=true);
    try{
      await requestJson(`/api/v1/arena/invitations/${item.invitation_id}${accept?'/accept':''}`,{method:accept?'POST':'DELETE',...(accept?{body:{}}:{})});
      if(stamp!==epoch)return;
      dialog.close();current=null;if(accept)location.assign('./pk.html');
    }catch(error){if(stamp===epoch)dialog.querySelector('[data-invite-error]').textContent=error.message;}
    finally{if(stamp===epoch)buttons.forEach(x=>x.disabled=false);}
  }
  let lastHeartbeat=0,lastInvites=0;
  /** 有界定时只在可见、登录和本标签获租约时发请求，离线错误留待下次重试。 */
  async function tick(){
    if(dead||!user||!enabled||document.hidden||inFlight||!lead())return;
    inFlight=true;const stamp=epoch;
    try{
      if(Date.now()-lastHeartbeat>=25000){await requestJson('/api/v1/me/presence',{method:'POST',body:{visible:true}});lastHeartbeat=Date.now();}
      if(stamp!==epoch)return;
      if(Date.now()-lastInvites>=15000){
        const value=await requestJson('/api/v1/me/arena/invitations');lastInvites=Date.now();
        if(stamp!==epoch)return;
        const incoming=value.items?.find(item=>item.target_id===user.id&&item.status==='pending');
        if(incoming)show(incoming);else if(dialog?.open){dialog.close();current=null;}
      }
    }catch{/* 竞技关闭、网络或容量错误不得阻止当前页面。 */}
    finally{inFlight=false;}
  }
  document.addEventListener('visibilitychange',()=>{if(document.hidden)release();else void tick();});
  timer=setInterval(()=>void tick(),5000);
  window.addEventListener('pagehide',()=>{release();dead=true;epoch++;clearInterval(timer);dialog?.close();},{once:true});
  return {
    /** 登录/换号立即废弃旧邀请；查询开关成功后才启用在线维护。 */
    async setUser(next){
      if(user?.id===next?.id)return;release();user=next;epoch++;lastHeartbeat=lastInvites=0;dialog?.close();current=null;
      if(!user)return;
      const stamp=epoch;
      try{const value=await requestJson('/api/v1/features');if(stamp!==epoch)return;enabled=value.pk_rooms&&value.progression;if(enabled)void tick();}catch{if(stamp===epoch)enabled=false;}
    },
  };
}
