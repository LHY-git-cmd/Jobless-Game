/** 竞技页面流转与结果文案：输入仅为服务器快照，不按本地时钟判胜。 */
export function arenaDestination(gamePage,room) {
  if(gamePage) return !room||['waiting','countdown'].includes(room.status)?'./pk.html':null;
  return room&&(room.status==='playing'||room.result)?`./pk-game.html?room=${encodeURIComponent(room.room_id)}`:null;
}

/** 跨页账号组件同时恢复时允许短暂过载；最多读取三次，不重放业务写请求。 */
export async function readArenaSnapshot(request,{current=()=>true,wait=ms=>new Promise(resolve=>setTimeout(resolve,ms))}={}) {
  for(let attempt=0;attempt<3;attempt++){
    if(!current())throw Object.assign(new Error('账号已切换。'),{stale:true});
    try{return await request();}
    catch(error){if(error.status!==503||attempt===2)throw error;await wait(Math.min(3000,Math.max(400,error.retryAfter*1000||400*(attempt+1))));}
  }
}

/** 房间接口以JSON整数revision作为强版本；只接受与头部完全一致的修订。 */
export function roomWriteVersion(snapshot){
  const revision=snapshot?.data?.revision;
  const expected=Number.isSafeInteger(revision)&&revision>=0?`"${revision}"`:null;
  // gzip代理可能只在ETag前加W/；不能将任意弱标签直接去前缀后用于条件写。
  if(!expected||![expected,`W/${expected}`].includes(snapshot.etag))throw new Error('无法核验房间版本，请刷新后重试。');
  return expected;
}

/** 准备切换先重读快照，真正412只有限重试本人原意图，不反向取消准备。 */
export async function toggleArenaReadiness({roomId,request}){
  const latest=await request('rooms/'+roomId);
  const me=latest.data.members.find(member=>member.is_me);
  if(!me)throw new Error('你已不在房间，请刷新后重试。');
  const desired=!me.ready;
  /** 每次条件写都核对该次新快照，而不是复用旧ETag。 */
  const write=value=>request(value.data.links.readiness,{method:'PUT',body:{ready:desired},headers:{'If-Match':roomWriteVersion(value)}});
  try{return await write(latest);}
  catch(error){
    if(error.status!==412)throw error;
    const current=await request('rooms/'+roomId);
    const own=current.data.members.find(member=>member.is_me);
    if(!own)throw new Error('你已不在房间，请刷新后重试。');
    if(current.data.status==='waiting'&&own.ready!==desired)return write(current);
    return current;
  }
}

/** 分开说明结果与原因，超时、踩雷和退出均可理解。 */
export function arenaResult(result,uid) {
  const score=result.scores?.find(item=>item.user_id===uid);
  const title=result.reason==='match_timeout'?'时间结束':result.outcome==='draw'?'本局平局':result.outcome==='win'?(result.winner_id===uid?'本局胜利':'本局落败'):'对局已结束';
  const reasons={match_timeout:'10分钟已到，双方均未完成，本局平局。',mine_hit:'有玩家踩中地雷，对局结束。',player_left:'有玩家主动退出，对局结束。',opponent_disconnected:'对手断线超过宽限时间。',both_offline:'双方断线，对局作废。',server_restart:'服务重启，对局作废。',waiting_timeout:'房间等待已到期。',valid_completion:result.outcome==='draw'?'双方在1秒窗口内正确完成，本局平局。':'已有玩家正确完成本局。'};
  const seconds=Math.floor((result.duration_ms||0)/1000);
  return {title,description:`${reasons[result.reason]||'本局已结算。'} 用时 ${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}。${score?` 积分 ${score.delta>=0?'+':''}${score.delta}，当前 ${score.points} 分。`:''}`,score};
}
