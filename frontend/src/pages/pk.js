/** 三模式竞技大厅：邀请、分池匹配、双方准备、权威棋盘及积分，所有写入通过HTTP。 */
import { initAuth } from '../features/account/auth.js';
import { Events } from '../shared/events.js';
import { api as arenaApi } from '../features/progression/client.js';
import { subscribeEvents } from '../features/pk/events.js';
import { createFormalBoard } from '../games/formal-board.js';
import { createAvatarImage } from '../features/account/avatar.js';

const $=id=>document.getElementById(id);
const names={mine:'扫雷',akari:'照明',sudoku:'数独'};
const auth=initAuth();
let uid,epoch=0,read=0,busy=false,eligible=false,enabled=false,features={},room=null,ticket=null,invitations=[],points=100;
let subscription=null,refreshTimer=null,boardRoom=null,offset=0,dead=false,lastResult=null,searchVersion=0;
let memory={requests:{},drafts:{},lastRoom:null},storage;
try{storage=localStorage;}catch{/* 本页仍可运行，但刷新后草稿不能恢复。 */}
/** 所有在途响应统一核对账号代数，换号后不能在工作回调内写入新账号内存。 */
async function api(path,options){
  const stamp=epoch,value=await arenaApi(path,options);
  if(dead||stamp!==epoch)throw Object.assign(new Error('账号已切换。'),{stale:true});
  return value;
}
const board=createFormalBoard({host:$('arena-board'),onChange:draft=>{
  if(room){memory.drafts[room.room_id]={...(memory.drafts[room.room_id]||{}),draft};save();}
},onReveal:index=>void reveal(index)});

/** 草稿只保存本人棋盘与幂等请求，不包含对手布局或任何积分凭据。 */
function save(){if(uid)try{storage?.setItem(`jobless-pk-v2:${uid}`,JSON.stringify(memory));}catch{$('arena-message').textContent='本地存储不可用，刷新后可能丢失未提交布局。';}}
/** 每个创建意图复用UUID，响应丢失重试不重复入队、邀请或建房。 */
function intent(kind,data){
  const previous=memory.requests[kind];
  if(!previous||JSON.stringify(previous.data)!==JSON.stringify(data)){memory.requests[kind]={data,key:crypto.randomUUID()};save();}
  return memory.requests[kind].key;
}
/** 用户名仅用textContent渲染，图片由固定预设编号创建。 */
function player(prefix,user){
  const host=$(prefix+'-avatar'),id=String(user?.user_id??user?.id??'')+':'+String(user?.avatar_id||1);
  if(host.dataset.identity!==id){host.replaceChildren(createAvatarImage(user?.avatar_id));host.dataset.identity=id;}
  $(prefix+'-name').textContent=user?.username||'请先登录';
}
/** 时间只显示服务器锚点，客户端到零不自行开始或判定结果。 */
function timing(){
  const now=Date.now()+offset;
  let label='等待开始',ms=0;
  if(ticket?.status==='waiting'){label='匹配用时';ms=now-Date.parse(ticket.created_at);}
  if(room?.status==='countdown'){label='即将开始';ms=Math.ceil(Math.max(0,Date.parse(room.starts_at)-now)/1000)*1000;}
  if(room?.status==='playing'){label='对局用时';ms=now-Date.parse(room.starts_at);}
  if(room?.result){label='本局用时';ms=room.result.duration_ms;}
  const seconds=Math.floor(Math.max(0,ms)/1000);
  $('arena-clock-label').textContent=label;$('arena-clock').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
}
/** 大厅按钮由权威状态决定，配对成功仅进入准备，不自动开局。 */
function render(){
  const user=auth.currentUser;
  player('arena-self',user);$('arena-own-id').textContent=user?`我的ID：${user.id}`:'登录后邀请或匹配';
  $('arena-points').textContent=String(points);
  const opponent=room?.members?.find(v=>!v.is_me),me=room?.members?.find(v=>v.is_me);
  const outgoing=invitations.find(v=>v.sender_id===uid&&v.status==='pending');
  $('arena-invite-open').hidden=Boolean(opponent);$('arena-opponent-avatar').hidden=!opponent;
  if(opponent)player('arena-opponent',opponent);
  else $('arena-opponent-name').textContent=outgoing?outgoing.target_name:'邀请一位对手';
  $('arena-self-status').textContent=room?.status==='playing'?(me?.completed?'已完成':'对局中'):me?.ready?'已准备':'未准备';
  $('arena-opponent-status').textContent=opponent?(opponent.completed?'已完成':opponent.ready?'已准备':'等待准备'):ticket?.status==='waiting'?'正在寻找对手':outgoing?'等待接受邀请':'或开始自动匹配';
  const active=room&&['waiting','countdown','playing'].includes(room.status);
  $('arena-invite-open').disabled=busy||!eligible||!enabled||Boolean(ticket||active||outgoing);
  $('arena-leave').hidden=!room;
  $('arena-leave').disabled=busy;
  $('arena-cancel-invite').hidden=!outgoing;$('arena-cancel-invite').disabled=busy;
  $('arena-mode').disabled=busy||!eligible||Boolean(ticket||outgoing||room&&(room.source==='match'||room.host_id!==uid||room.status!=='waiting'));
  if(room)$('arena-mode').value=room.game_id;
  const action=$('arena-action');action.disabled=busy||!enabled;
  if(!uid){action.textContent='登录并继续';action.disabled=false;}
  else if(!eligible){action.textContent='5级解锁竞技';action.disabled=true;}
  else if(ticket?.status==='waiting')action.textContent='取消匹配';
  else if(room?.status==='waiting'){action.textContent=me?.ready?'取消准备':'准备';action.disabled=busy||!opponent;}
  else if(room?.status==='countdown'){action.textContent='即将开始…';action.disabled=true;}
  else if(room?.status==='playing'){action.textContent=me?.completed?'等待对局结果':'对局进行中';action.disabled=true;}
  else if(room?.result)action.textContent='返回大厅';
  else {action.textContent=outgoing?'等待接受邀请':'开始匹配';action.disabled=busy||Boolean(outgoing);}
  const playing=Boolean(room?.puzzle);
  $('arena-game').hidden=!playing;
  if(playing){
    $('arena-game-title').textContent=`${names[room.game_id]} · ${room.status==='playing'?'对局进行中':'本局已结束'}`;
    $('arena-game-help').textContent=room.game_id==='mine'?'双方同一雷区与安全起始格；踩雷立即判负。点按格子排雷，可切换标记。':room.game_id==='akari'?'照亮全部白格、满足数字且灯泡不互照后提交解答。':'填写空白数字，行、列与九宫内1～9不重复。完成后提交解答。';
    if(boardRoom!==room.room_id){boardRoom=room.room_id;board.load(room.game_id,room.puzzle,memory.drafts[room.room_id]?.draft||{},room.mine_board);}
    else if(room.game_id==='mine')board.setMine(room.mine_board);
    board.setDisabled(busy||room.status!=='playing'||Boolean(me?.completed)||Boolean(memory.drafts[room.room_id]?.pending));
    $('arena-submit').hidden=room.game_id==='mine'||room.status!=='playing'||Boolean(me?.completed);
    $('arena-submit').disabled=busy;$('arena-submit').textContent=memory.drafts[room.room_id]?.pending?'重试提交解答':'提交解答';
  }else if(boardRoom){board.clear();boardRoom=null;}
  $('arena-result').hidden=!room?.result;
  if(!room?.result)$('arena-result').textContent='';
  if(room?.result){
    const result=room.result,score=result.scores?.find(v=>v.user_id===uid);
    const outcome=result.outcome==='draw'?'本局平局':result.outcome==='win'?(result.winner_id===uid?'你赢得了本局':'本局落败'):'对局作废';
    $('arena-result').textContent=`${outcome}。${score?`积分 ${score.delta>=0?'+':''}${score.delta}，当前 ${score.points} 分。`:''}`;
    if(score){points=score.points;$('arena-points').textContent=String(points);}
  }
  const incoming=invitations.filter(v=>v.target_id===uid&&v.status==='pending');
  $('arena-invitations').hidden=!incoming.length;
  $('arena-incoming-list').replaceChildren(...incoming.map(item=>{
    const row=document.createElement('div');row.className='arena-incoming';
    const text=document.createElement('span');text.textContent=`${item.sender_name} 邀请你进行${names[item.game_id]}对战`;
    const accept=document.createElement('button'),decline=document.createElement('button');accept.type=decline.type='button';accept.textContent='接受';decline.textContent='拒绝';accept.disabled=decline.disabled=busy;
    accept.addEventListener('click',()=>void act(async()=>{const value=await api(`arena/invitations/${item.invitation_id}/accept`,{method:'POST',body:{}});adoptRoom(value);}));
    decline.addEventListener('click',()=>void act(()=>api(`arena/invitations/${item.invitation_id}`,{method:'DELETE'})));
    row.append(text,accept,decline);return row;
  }));
  timing();
}
/** 采用新的房间快照；结束后仍留结果，刷新可读本人最近房间。 */
function adoptRoom(value){
  const data=value.data||value;room={...data,etag:value.etag||data.etag};ticket=null;
  offset=Date.parse(data.server_now)-Date.now();if(!Number.isFinite(offset))offset=0;
  memory.lastRoom=data.room_id;save();
  if(room.status==='playing'&&lastResult!==room.room_id){lastResult=room.room_id;setTimeout(()=>$('arena-game').scrollIntoView({behavior:'instant',block:'start'}),0);}
}
/** SSE仅提示重读，不通过事件直接写胜负/积分；80毫秒内重复通知合并。 */
function schedule(){if(refreshTimer||dead)return;refreshTimer=setTimeout(()=>{refreshTimer=null;void refresh();},80);}
/** 并行有限读取状态，旧请求在换号或后续刷新后不能覆盖新数据。 */
async function refresh(){
  if(!uid||!enabled)return;
  const stamp=epoch,version=++read;
  try{
    const snapshot=await api('me/arena/state'+(memory.lastRoom?'?last_room='+encodeURIComponent(memory.lastRoom):''));
    if(stamp!==epoch||version!==read)return;
    const data=snapshot.data;
    points=data.account.points;eligible=data.eligibility.eligible;invitations=data.invitations;ticket=data.ticket;
    const eligibility={data:data.eligibility};
    if(ticket&&ticket.status!=='waiting')ticket=null;
    if(data.room)adoptRoom({data:data.room,etag:data.room.etag});
    else {room=null;memory.lastRoom=null;save();}
    if(!eligible)$('arena-message').textContent=`达到5级后解锁竞技，当前${eligibility.data.level}级。`;
    else if(room?.status==='waiting')$('arena-message').textContent=room.members.length===2?'对手已到位，双方准备后3秒开始。':'等待另一位玩家。';
    else if(room?.status==='countdown')$('arena-message').textContent='双方已准备，倒计时3秒后开始。';
    else if(ticket){offset=Date.parse(ticket.server_now)-Date.now();$('arena-message').textContent='正在匹配相同模式的玩家，最多等待60秒，可随时取消。';}
    else if(!room)$('arena-message').textContent='选择模式，邀请玩家或开始自动匹配。';
    render();
  }catch(error){if(stamp===epoch)showError(error);}
}
/** 请求失败保留当前意图与棋盘，重复操作由业务幂等保护。 */
async function act(work){
  if(busy||!uid)return;const stamp=epoch;busy=true;render();
  try{await work();if(stamp!==epoch)return;await refresh();}
  catch(error){if(stamp===epoch){showError(error);if(error.status===409||error.status===412)await refresh();}}
  finally{if(stamp===epoch){busy=false;render();}}
}
/** 身份失效交由共享登录处理，其他错误只显示有限可理解文字。 */
function showError(error){if(error.stale)return;$('arena-message').textContent=error.message;if(error.status===401)document.dispatchEvent(new CustomEvent(Events.AUTH_EXPIRED));}
/** 同一创建意图失败保持原UUID，成功后释放再生成下一次意图。 */
async function create(kind,data){
  const value=await api(kind,{method:'POST',body:data,headers:{'Idempotency-Key':intent(kind,data)}});
  delete memory.requests[kind];save();return value;
}
/** 主按钮随状态匹配、取消、准备或离开结果页。 */
async function action(){
  if(!uid)return auth.requireLogin(()=>identityChanged());
  if(!eligible)return;
  if(room?.result){read++;room=null;ticket=null;memory.lastRoom=null;boardRoom=null;board.clear();save();render();return refresh();}
  if(ticket)return act(async()=>{await api(ticket.links.self,{method:'DELETE'});ticket=null;});
  if(room?.status==='waiting')return act(async()=>{
    const latest=await api('rooms/'+room.room_id);const me=latest.data.members.find(v=>v.is_me);
    const desired=!me.ready;
    try{adoptRoom(await api(latest.data.links.readiness,{method:'PUT',body:{ready:desired},headers:{'If-Match':latest.etag}}));}
    catch(error){
      if(error.status!==412)throw error;
      // 双方同时准备只重放本人原意图，不能因重读后状态变化反向切换准备。
      const current=await api('rooms/'+latest.data.room_id);
      if(current.data.status==='waiting'&&current.data.members.find(v=>v.is_me)?.ready!==desired)
        adoptRoom(await api(current.data.links.readiness,{method:'PUT',body:{ready:desired},headers:{'If-Match':current.etag}}));
      else adoptRoom(current);
    }
  });
  return act(async()=>{const value=await create('matchmaking-tickets',{game_id:$('arena-mode').value,difficulty:'normal'});ticket=value.data;});
}
/** 扫雷输入由服务端揭格，不能将未揭地雷传入浏览器。 */
async function reveal(index){
  if(!room||room.status!=='playing')return;
  return act(async()=>adoptRoom(await api(`rooms/${room.room_id}/reveals/${index}`,{method:'PUT',body:{}})));
}
/** 合法解答冻结重试负载；422才解除冻结供玩家修正。 */
async function submit(){
  if(!room||room.status!=='playing')return;
  const entry=memory.drafts[room.room_id]||={draft:board.snapshot()};entry.pending||=board.payload();save();
  return act(async()=>{try{await api(room.links.submission,{method:'PUT',body:entry.pending});entry.pending=null;save();}
    catch(error){if(error.status===422){entry.pending=null;save();}throw error;}});
}
/** 搜索仅发用户主动提交的完整姓名或ID，不逐字符查询。 */
async function search(event){
  event.preventDefault();const stamp=epoch,version=++searchVersion;
  $('arena-search-message').textContent='正在查找…';$('arena-search-results').replaceChildren();
  try{
    const value=await api('arena/users?q='+encodeURIComponent($('arena-search-query').value.trim()));
    if(stamp!==epoch||version!==searchVersion)return;
    $('arena-search-message').textContent=value.data.items.length?'仅在线、空闲且已达5级的玩家可邀请。':'未找到玩家，请输入完整用户名或用户ID。';
    for(const user of value.data.items){
      const row=document.createElement('div');row.className='arena-search-result';const text=document.createElement('span');text.textContent=`${user.username} · ID ${user.user_id} · ${!user.online?'离线':!user.idle?'忙碌':!user.eligible?'未达5级':'可邀请'}`;
      const button=document.createElement('button');button.type='button';button.textContent='邀请';button.disabled=!user.invitable;
      button.addEventListener('click',()=>{void act(async()=>{await create('arena/invitations',{user_id:user.user_id,game_id:$('arena-mode').value,difficulty:'normal'});$('arena-search-dialog').close();});});
      row.append(createAvatarImage(user.avatar_id),text,button);$('arena-search-results').append(row);
    }
  }catch(error){if(stamp===epoch)$('arena-search-message').textContent=error.message;}
}
/** 换号先清空旧房间和棋盘，再读取新账号等级、积分和待处理邀请。 */
async function identityChanged(){
  const next=auth.currentUser?.id??null;if(next===uid)return;
  uid=next;epoch++;read++;subscription?.close();subscription=null;busy=false;room=ticket=null;invitations=[];points=100;eligible=false;
  memory={requests:{},drafts:{},lastRoom:null};board.clear();boardRoom=null;lastResult=null;
  $('arena-search-dialog').close();$('arena-leave-dialog').close();
  if(uid)try{const saved=JSON.parse(storage?.getItem(`jobless-pk-v2:${uid}`)||'null');if(saved?.requests&&saved?.drafts)memory=saved;}catch{/* 不使用损坏草稿。 */}
  const stamp=epoch;
  try{
    features=(await api('features')).data;if(stamp!==epoch)return;enabled=features.progression&&features.pk_rooms;
    if(!uid){$('arena-message').textContent='登录后参与竞技，达到5级解锁。';render();return;}
    if(!enabled){$('arena-message').textContent='竞技模式暂未开放。';render();return;}
    await api('me/presence',{method:'POST',body:{visible:!document.hidden}});if(stamp!==epoch)return;
    await refresh();
    if(stamp!==epoch)return;
    subscription=subscribeEvents({onResource:schedule,onReconnect:schedule,onState:message=>{if(stamp===epoch)$('arena-connection').textContent=message;}});
  }catch(error){if(stamp===epoch)showError(error);}
  render();
}
$('arena-action').addEventListener('click',()=>void action());
$('arena-refresh').addEventListener('click',()=>void refresh());
$('arena-invite-open').addEventListener('click',()=>{$('arena-search-results').replaceChildren();$('arena-search-dialog').showModal();$('arena-search-query').focus();});
$('arena-search-form').addEventListener('submit',search);$('arena-search-close').addEventListener('click',()=>$('arena-search-dialog').close());
$('arena-cancel-invite').addEventListener('click',()=>void act(async()=>{const item=invitations.find(v=>v.sender_id===uid);if(item)await api('arena/invitations/'+item.invitation_id,{method:'DELETE'});}));
$('arena-mode').addEventListener('change',()=>{const desired=$('arena-mode').value;if(room)void act(async()=>{const value=await api('rooms/'+room.room_id);adoptRoom(await api(`rooms/${room.room_id}/mode`,{method:'PUT',body:{game_id:desired,difficulty:'normal'},headers:{'If-Match':value.etag}}));});});
$('arena-submit').addEventListener('click',()=>void submit());
$('arena-leave').addEventListener('click',()=>{$('arena-leave-description').textContent=room?.status==='playing'?'比赛已经开始，退出将判负并扣除10积分。':'准备阶段退出不扣积分。';$('arena-leave-dialog').showModal();});
$('arena-leave-cancel').addEventListener('click',()=>$('arena-leave-dialog').close());
$('arena-leave-confirm').addEventListener('click',()=>{void act(async()=>{await api(room.links.membership,{method:'DELETE'});room=null;memory.lastRoom=null;save();$('arena-leave-dialog').close();});});
const timer=setInterval(timing,250);
document.addEventListener(Events.AUTH_CHANGED,()=>void identityChanged());
document.addEventListener(Events.USER_PROFILE_UPDATED,()=>render());
window.addEventListener('pagehide',()=>{dead=true;epoch++;subscription?.close();clearInterval(timer);clearTimeout(refreshTimer);board.destroy();});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
void auth.ready.then(identityChanged);
