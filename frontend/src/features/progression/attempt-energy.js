/** 正式会话的体力快照与原子重开适配，三款游戏共用同一协议。 */
import { Events } from '../../shared/events.js';

/** 浏览器立即同步权威体力，测试或销毁环境不创建虚假DOM事件。 */
export function publishAttemptEnergy(uid,value){
  if(!value?.energy||typeof document==='undefined')return;
  document.dispatchEvent(new CustomEvent(Events.ENERGY_CHANGED,{detail:{userId:uid,energy:value.energy}}));
}

/** 重开UUID保存在既有账号草稿容器，断网/刷新后仍重试同一原子操作。 */
export async function restartAttempt({attempt,store,request}){
  const key='restart:'+attempt.attempt_id;
  const response=await request(attempt.links.self+'/restart',{method:'POST',body:{},headers:{'Idempotency-Key':store.startKey(key)}});
  return {response,clear:()=>store.clearStart(key)};
}

/** 统一描述免费教学、普通开局及重开的实际体力规则。 */
export function energyHint(tutorial,restarting=false){
  return tutorial?'入门免费，不消耗或返还体力。':restarting?'原棋局消耗的体力不返还，重开再消耗1点；通关返还1点。':'开始新局消耗1点体力，通关返还1点；继续原局不重复消耗。';
}
