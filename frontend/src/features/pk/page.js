/** 竞技大厅与独立游戏页共用控制器：HTTP写入、SSE重读、按账号隔离草稿。 */
import { initAuth } from '../account/auth.js';
import { authRequest } from '../account/client.js';
import { Events } from '../../shared/events.js';
import { api as arenaApi } from '../progression/client.js';
import { subscribeEvents } from './events.js';
import { createArenaBoard } from '../../games/arena-board.js';
import { createAvatarImage } from '../account/avatar.js';
import { createRequestId } from '../../shared/request-id.js';
import { arenaDestination, arenaResult, readArenaSnapshot } from './flow.js';

/** gamePage固定本页职责；游戏页始终读取URL中的那一局，保证双方都看到旧局结果。 */
export function initArenaPage({gamePage=false}={}) {
  const $=id=>document.getElementById(id),auth=initAuth({restoreSession:()=>readArenaSnapshot(()=>authRequest('me'))});
  const names={mine:'扫雷',akari:'照明',sudoku:'数独'};
  const requestedRoom=new URLSearchParams(location.search).get('room');
  let uid,epoch=0,read=0,busy=false,eligible=false,enabled=false,room=null,ticket=null,invitations=[],points=100;
  let subscription=null,refreshTimer=null,boardRoom=null,offset=0,dead=false,resultShown=null,searchVersion=0,navigating=false;
  let memory={requests:{},drafts:{},lastRoom:null},storage;
  try{storage=localStorage;}catch{/* 受限存储仍允许本页对局，刷新恢复另行提示。 */}
  const board=$('arena-board')?createArenaBoard({host:$('arena-board'),onChange:draft=>{
    if(room){memory.drafts[room.room_id]={...(memory.drafts[room.room_id]||{}),draft};save();}
  },onReveal:index=>void reveal(index),onComplete:()=>void submit()}):null;

  /** 换号后在途响应不能写入新账号内存。 */
  async function api(path,options){
    const stamp=epoch;
    const value=options?.method&&options.method!=='GET'?await arenaApi(path,options):await readArenaSnapshot(()=>arenaApi(path,options),{current:()=>!dead&&!navigating&&stamp===epoch});
    if(dead||navigating||stamp!==epoch)throw Object.assign(new Error('账号已切换或页面已离开。'),{stale:true});return value;
  }
  /** 相同账号保存幂等键和本人草稿，不保存对手答案或积分凭据。 */
  function save(){if(uid)try{storage?.setItem(`jobless-pk-v2:${uid}`,JSON.stringify(memory));}catch{message('本地存储不可用，刷新后可能丢失未提交布局。');}}
  /** 共用状态提示始终可见，包括结算弹窗中的重试错误。 */
  function message(text){$('arena-message').textContent=text;$('arena-message').hidden=!text;if($('arena-result-dialog')?.open)$('arena-result-message').textContent=text;}
  /** 页面切换先保存当前房间，同一状态的重复通知只跳转一次。 */
  function navigate(target){if(navigating||dead)return;navigating=true;save();location.replace(target);}
  /** 同一创建意图重试复用UUID，成功后释放。 */
  function intent(kind,data){const previous=memory.requests[kind];if(!previous||JSON.stringify(previous.data)!==JSON.stringify(data)){memory.requests[kind]={data,key:createRequestId()};save();}return memory.requests[kind].key;}
  /** 玩家名称只用textContent，头像只用固定预设素材。 */
  function player(prefix,user){const host=$(prefix+'-avatar');if(!host)return;const id=String(user?.user_id??user?.id??'')+':'+String(user?.avatar_id||1);if(host.dataset.identity!==id){host.replaceChildren(createAvatarImage(user?.avatar_id));host.dataset.identity=id;}$(prefix+'-name').textContent=user?.username||'请先登录';}
  /** 显示服务器时间锚点；浏览器到零不会自行开局或判定胜负。 */
  function timing(){
    const now=Date.now()+offset;let label='等待开始',ms=0;
    if(ticket?.status==='waiting'){label='匹配用时';ms=now-Date.parse(ticket.created_at);}
    if(room?.status==='countdown'){label='即将开始';ms=Math.ceil(Math.max(0,Date.parse(room.starts_at)-now)/1000)*1000;}
    if(room?.status==='playing'){label='对局剩余';ms=Date.parse(room.ends_at)-now;}
    if(room?.result){label='本局用时';ms=room.result.duration_ms;}
    const seconds=Math.floor(Math.max(0,ms)/1000);$('arena-clock-label').textContent=label;$('arena-clock').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
  }
  /** 大厅保留模式选择、双人准备和倒计时，开局再进行原生页面跳转。 */
  function renderLobby(){
    if(gamePage)return;
    player('arena-self',auth.currentUser);$('arena-own-id').textContent=uid?`我的ID：${auth.currentUser.player_id||auth.currentUser.id}`:'登录后邀请或匹配';
    const opponent=room?.members?.find(v=>!v.is_me),me=room?.members?.find(v=>v.is_me),outgoing=invitations.find(v=>v.sender_id===uid&&v.status==='pending');
    $('arena-invite-open').hidden=Boolean(opponent);$('arena-opponent-avatar').hidden=!opponent;
    if(opponent)player('arena-opponent',opponent);else $('arena-opponent-name').textContent=outgoing?outgoing.target_name:'邀请一位对手';
    $('arena-self-status').textContent=me?.ready?'已准备':'未准备';
    $('arena-opponent-status').textContent=opponent?(opponent.ready?'已准备':'等待准备'):ticket?'正在寻找对手':outgoing?'等待接受邀请':'或开始自动匹配';
    const active=room&&['waiting','countdown','playing'].includes(room.status);
    $('arena-invite-open').disabled=busy||!eligible||!enabled||Boolean(ticket||active||outgoing);
    $('arena-mode').disabled=busy||!eligible||Boolean(ticket||outgoing||room&&(room.source==='match'||room.host_id!==uid||room.status!=='waiting'));
    if(room)$('arena-mode').value=room.game_id;
    $('arena-cancel-invite').hidden=!outgoing;$('arena-cancel-invite').disabled=busy;
    const action=$('arena-action');action.disabled=busy||!enabled;
    if(!uid){action.textContent='登录并继续';action.disabled=false;}
    else if(!eligible){action.textContent='5级解锁竞技';action.disabled=true;}
    else if(ticket)action.textContent='取消匹配';
    else if(room?.status==='waiting'){action.textContent=me?.ready?'取消准备':'准备';action.disabled=busy||!opponent;}
    else if(room?.status==='countdown'){action.textContent='即将开始…';action.disabled=true;}
    else if(room?.result)action.textContent='查看本局结果';
    else action.textContent=outgoing?'等待接受邀请':'开始匹配';
    if(outgoing)action.disabled=true;
    const incoming=invitations.filter(v=>v.target_id===uid&&v.status==='pending');$('arena-invitations').hidden=!incoming.length;
    $('arena-incoming-list').replaceChildren(...incoming.map(item=>{
      const row=document.createElement('div');row.className='arena-incoming';const text=document.createElement('span');text.textContent=`${item.sender_name} 邀请你进行${names[item.game_id]}对战`;
      const accept=document.createElement('button'),decline=document.createElement('button');accept.type=decline.type='button';accept.textContent='接受';decline.textContent='拒绝';accept.disabled=decline.disabled=busy;
      accept.addEventListener('click',()=>void act(async()=>adoptRoom(await api(`arena/invitations/${item.invitation_id}/accept`,{method:'POST',body:{}}))));
      decline.addEventListener('click',()=>void act(()=>api(`arena/invitations/${item.invitation_id}`,{method:'DELETE'})));row.append(text,accept,decline);return row;
    }));
  }
  /** 独立游戏页只绑定当前局，结果刷新不重建棋盘或覆盖历史结果。 */
  function renderGame(){
    if(!gamePage)return;
    const playing=Boolean(room?.puzzle),me=room?.members?.find(v=>v.is_me),opponent=room?.members?.find(v=>!v.is_me);
    $('arena-game').hidden=!playing;
    $('arena-matchup').textContent=room?`${auth.currentUser?.username||'我'}  VS  ${opponent?.username||'对手已离开'}${me?.completed?' · 你已完成，等待结算':''}`:'';
    if(playing){
      $('arena-title').textContent=`${names[room.game_id]}竞技`;document.title=`${names[room.game_id]}竞技 · 无职游戏`;
      $('arena-game-title').textContent=room.result?'本局已结束':me?.completed?'已完成，等待对局结果':'对局进行中';
      $('arena-game-help').textContent=room.game_id==='mine'?'双方同一雷区和安全起点。先选格，再点击标记或排雷；踩雷立即判负。':room.game_id==='akari'?'点按白格放灯或撤灯，照亮全部白格，满足数字且灯泡不互照。':'选格后用数字键盘填写；支持笔记、撤回和清除。行、列与九宫内1～9不重复。';
      if(boardRoom!==room.room_id){boardRoom=room.room_id;board.load(room.game_id,room.puzzle,memory.drafts[room.room_id]?.draft||{},room.mine_board);}
      else if(room.game_id==='mine')board.setMine(room.mine_board);
      board.setDisabled(busy||room.status!=='playing'||Boolean(me?.completed)||Boolean(memory.drafts[room.room_id]?.pending));
      $('arena-submit').hidden=room.game_id==='mine'||room.status!=='playing'||Boolean(me?.completed);
      $('arena-submit').disabled=busy;$('arena-submit').textContent=memory.drafts[room.room_id]?.pending?'重试提交解答':'提交解答';
    }
    if(room?.result){
      const value=arenaResult(room.result,uid);$('arena-result-title').textContent=value.title;$('arena-result-description').textContent=value.description;
      if(value.score)points=value.score.points;
      $('arena-rematch').disabled=busy||!opponent||(!room.next_room_id&&!room.lobby_expires_at);
      $('arena-return').disabled=busy;
      if(resultShown!==room.room_id){resultShown=room.room_id;$('arena-result-message').textContent='';$('arena-result-dialog').showModal();}
    }
  }
  /** 全页按钮随HTTP锁更新，避免双击造成多次输入。 */
  function render(){
    if(dead||navigating)return;
    const destination=arenaDestination(gamePage,room);
    // 尚未完成身份恢复时不让空快照触发返回，保持登录页可用。
    if(destination&&room){navigate(destination);return;}
    renderLobby();renderGame();$('arena-points').textContent=String(points);
    $('arena-leave').hidden=!room;$('arena-leave').disabled=busy;timing();
  }
  /** 采用权威快照，保持换页草稿与服务器时间一致。 */
  function adoptRoom(value){const data=value.data||value;room={...data,etag:value.etag||data.etag};ticket=null;offset=Date.parse(data.server_now)-Date.now();if(!Number.isFinite(offset))offset=0;memory.lastRoom=data.room_id;save();}
  /** 80ms合并资源通知，网络恢复只重读，不依据事件内容计算积分。 */
  function schedule(){if(refreshTimer||dead)return;refreshTimer=setTimeout(()=>{refreshTimer=null;void refresh();},80);}
  /** 游戏固定读取URL中的旧局；大厅读取账号当前占用，旧异步请求不覆盖新快照。 */
  async function refresh(){
    if(!uid||!enabled||navigating)return;const stamp=epoch,version=++read;
    try{
      if(gamePage){
        if(!requestedRoom||!/^[a-f0-9-]{36}$/i.test(requestedRoom)){navigate('./pk.html');return;}
        const value=await api('rooms/'+requestedRoom);if(stamp!==epoch||version!==read)return;adoptRoom(value);
      }else{
        const value=await api('me/arena/state'+(memory.lastRoom?'?last_room='+encodeURIComponent(memory.lastRoom):''));if(stamp!==epoch||version!==read)return;
        const data=value.data;points=data.account.points;eligible=data.eligibility.eligible;invitations=data.invitations;ticket=data.ticket?.status==='waiting'?data.ticket:null;
        if(data.room)adoptRoom({data:data.room,etag:data.room.etag});else{room=null;memory.lastRoom=null;save();}
      }
      if(!eligible)message('达到5级后解锁竞技。');
      else if(room?.status==='waiting')message(room.members.length===2?'对手已到位，双方准备后3秒开始。':'等待对手；可离开房间后重新邀请或匹配。');
      else if(room?.status==='countdown')message('双方已准备，倒计时结束后进入游戏页面。');
      else if(room?.status==='playing')message(room.members.find(m=>m.is_me)?.completed?'已提交正确解答，正在等待服务器结算。':'');
      else if(ticket){offset=Date.parse(ticket.server_now)-Date.now();message('正在匹配相同模式的玩家，最多等待60秒，可随时取消。');}
      else if(!room)message('选择模式，邀请玩家或开始自动匹配。');
      render();
    }catch(error){if(stamp===epoch){if(gamePage&&error.status===404){navigate('./pk.html');return;}showError(error);}}
  }
  /** 在途动作期间冻结输入，错误保留原请求及终盘用于重试。 */
  async function act(work){if(busy||!uid)return;const stamp=epoch;busy=true;read++;render();try{await work();if(stamp===epoch&&!navigating)await refresh();}catch(error){if(stamp===epoch){showError(error);if(error.status===409||error.status===412)await refresh();}}finally{if(stamp===epoch){busy=false;render();}}}
  /** 身份失效交由共享登录处理，其他错误留在当前页面。 */
  function showError(error){if(error.stale)return;message(error.message);if(error.status===401)document.dispatchEvent(new CustomEvent(Events.AUTH_EXPIRED));}
  /** 成功释放幂等键，丢响应时继续复用原键。 */
  async function create(kind,data){const value=await api(kind,{method:'POST',body:data,headers:{'Idempotency-Key':intent(kind,data)}});delete memory.requests[kind];save();return value;}
  /** 大厅主操作仅切换本人准备，不将匹配成功视为准备完成。 */
  async function action(){
    if(!uid)return auth.requireLogin(()=>identityChanged());if(!eligible)return;
    if(room?.result){navigate(`./pk-game.html?room=${encodeURIComponent(room.room_id)}`);return;}
    if(ticket)return act(async()=>{await api(ticket.links.self,{method:'DELETE'});ticket=null;});
    if(room?.status==='waiting')return act(async()=>{
      const latest=await api('rooms/'+room.room_id),desired=!latest.data.members.find(v=>v.is_me).ready;
      try{adoptRoom(await api(latest.data.links.readiness,{method:'PUT',body:{ready:desired},headers:{'If-Match':latest.etag}}));}
      catch(error){if(error.status!==412)throw error;const current=await api('rooms/'+latest.data.room_id);if(current.data.status==='waiting'&&current.data.members.find(v=>v.is_me)?.ready!==desired)adoptRoom(await api(current.data.links.readiness,{method:'PUT',body:{ready:desired},headers:{'If-Match':current.etag}}));else adoptRoom(current);}
    });
    return act(async()=>{const value=await create('matchmaking-tickets',{game_id:$('arena-mode').value,difficulty:'normal'});ticket=value.data;});
  }
  /** 扫雷只发索引，服务端确认已揭格和胜负。 */
  async function reveal(index){if(room?.status!=='playing')return;return act(async()=>adoptRoom(await api(`rooms/${room.room_id}/reveals/${index}`,{method:'PUT',body:{}})));}
  /** 首次提交冻结终盘，422才解锁修正，其余错误允许原负载重试。 */
  async function submit(){
    if(busy||room?.status!=='playing'||room.members.find(m=>m.is_me)?.completed)return;
    const entry=memory.drafts[room.room_id]||={draft:board.snapshot()};entry.pending||=board.payload();save();
    return act(async()=>{try{await api(room.links.submission,{method:'PUT',body:entry.pending});entry.pending=null;save();}catch(error){if(error.status===422){entry.pending=null;save();}throw error;}});
  }
  /** 返回不准备，再战只确认本人；对手未确认时回到房间显示等待。 */
  async function continuation(ready){
    if(!room?.result)return;
    return act(async()=>{const value=await api(room.links.continuation,{method:'POST',body:{ready}});adoptRoom(value);$('arena-result-dialog').close();navigate('./pk.html');});
  }
  /** 搜索仅由主动提交触发，不逐字符请求。 */
  async function search(event){
    event.preventDefault();const stamp=epoch,version=++searchVersion;$('arena-search-message').textContent='正在查找…';$('arena-search-results').replaceChildren();
    try{
      const value=await api('arena/users?q='+encodeURIComponent($('arena-search-query').value.trim()));if(stamp!==epoch||version!==searchVersion)return;
      $('arena-search-message').textContent=value.data.items.length?'仅在线、空闲且已达5级的玩家可邀请。':'未找到玩家，请输入8位玩家ID或完整用户名。';
      for(const user of value.data.items){
        const row=document.createElement('div');row.className='arena-search-result';const text=document.createElement('span');text.textContent=`${user.username} · ID ${user.player_id} · ${!user.online?'离线':!user.idle?'忙碌':!user.eligible?'未达5级':'可邀请'}`;
        const invite=document.createElement('button');invite.type='button';invite.textContent='邀请';invite.disabled=!user.invitable;
        invite.addEventListener('click',()=>void act(async()=>{await create('arena/invitations',{user_id:user.user_id,game_id:$('arena-mode').value,difficulty:'normal'});$('arena-search-dialog').close();}));row.append(createAvatarImage(user.avatar_id),text,invite);$('arena-search-results').append(row);
      }
    }catch(error){if(stamp===epoch)$('arena-search-message').textContent=error.message;}
  }
  /** 换号关闭旧流、棋盘和弹窗，新账号不能恢复旧账号对局。 */
  async function identityChanged(){
    const next=auth.currentUser?.id??null;if(next===uid)return;uid=next;epoch++;read++;subscription?.close();subscription=null;busy=false;room=ticket=null;invitations=[];points=100;eligible=false;
    memory={requests:{},drafts:{},lastRoom:null};board?.clear();boardRoom=null;resultShown=null;
    for(const id of ['arena-search-dialog','arena-leave-dialog','arena-result-dialog'])$(id)?.close();
    if(uid)try{const saved=JSON.parse(storage?.getItem(`jobless-pk-v2:${uid}`)||'null');if(saved?.requests&&saved?.drafts)memory=saved;}catch{/* 损坏草稿不恢复。 */}
    const stamp=epoch;
    try{
      const features=(await api('features')).data;if(stamp!==epoch)return;enabled=features.progression&&features.pk_rooms;
      if(!uid){message('登录后参与竞技，达到5级解锁。');render();return;}
      if(!enabled){message('竞技模式暂未开放。');render();return;}
      // 首次恢复先确认在线租约，确保大厅可操作时已能被查找邀请。
      // 租约更新本身幂等且不写业务数据，可在503时有限重试；对局写操作仍不自动重放。
      await readArenaSnapshot(()=>api('me/presence',{method:'POST',body:{visible:!document.hidden}}),{current:()=>!dead&&!navigating&&stamp===epoch});
      if(gamePage){const value=(await api('me/arena')).data;points=value.points;eligible=value.eligible;}
      await refresh();if(stamp!==epoch||navigating)return;
      subscription=subscribeEvents({onResource:schedule,onReconnect:schedule,onState:text=>{if(stamp===epoch)$('arena-connection').textContent=text;}});
    }catch(error){if(stamp===epoch)showError(error);}render();
  }
  /** 页面各自只绑定实际存在的控件。 */
  function listen(id,event,callback){$(id)?.addEventListener(event,callback);}
  listen('arena-action','click',()=>void action());listen('arena-refresh','click',()=>void refresh());
  listen('arena-invite-open','click',()=>{$('arena-search-results').replaceChildren();$('arena-search-dialog').showModal();$('arena-search-query').focus();});
  listen('arena-search-form','submit',search);listen('arena-search-close','click',()=>$('arena-search-dialog').close());
  listen('arena-cancel-invite','click',()=>void act(async()=>{const item=invitations.find(v=>v.sender_id===uid);if(item)await api('arena/invitations/'+item.invitation_id,{method:'DELETE'});}));
  listen('arena-mode','change',()=>{const desired=$('arena-mode').value;if(room)void act(async()=>{const value=await api('rooms/'+room.room_id);adoptRoom(await api(`rooms/${room.room_id}/mode`,{method:'PUT',body:{game_id:desired,difficulty:'normal'},headers:{'If-Match':value.etag}}));});});
  listen('arena-submit','click',()=>void submit());listen('arena-rematch','click',()=>void continuation(true));listen('arena-return','click',()=>void continuation(false));
  listen('arena-result-dialog','cancel',event=>event.preventDefault());
  listen('arena-leave','click',()=>{$('arena-leave-description').textContent=room?.status==='playing'?'比赛已经开始，退出将判负并扣除10积分。':'离开房间后将释放你的席位。';$('arena-leave-dialog').showModal();});
  listen('arena-result-leave','click',()=>{$('arena-leave-description').textContent='离开房间后将释放你的席位，当前结算不会改变。';$('arena-leave-dialog').showModal();});
  listen('arena-leave-cancel','click',()=>$('arena-leave-dialog').close());
  listen('arena-leave-confirm','click',()=>void act(async()=>{if(room)await api(room.links.membership,{method:'DELETE'});room=null;memory.lastRoom=null;save();$('arena-leave-dialog').close();if(gamePage)navigate('./pk.html');}));
  const timer=setInterval(timing,250);
  document.addEventListener(Events.AUTH_CHANGED,()=>void identityChanged());document.addEventListener(Events.USER_PROFILE_UPDATED,()=>render());
  window.addEventListener('pagehide',()=>{dead=true;epoch++;subscription?.close();clearInterval(timer);clearTimeout(refreshTimer);board?.destroy();});
  window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
  void auth.ready.then(identityChanged);
}
