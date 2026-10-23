/** 主动退出使用既有条件放弃接口；先核验权威状态，避免覆盖其他页面的结算。 */
import { api } from './client.js';

/** 丢失退出响应时可重读已放弃状态；失败不清理草稿，由调用方显示重试。 */
export async function abandonAttempt({attempt,request=api}) {
  const latest=await request(attempt.links.self);
  if(latest.data.status==='abandoned')return latest;
  if(latest.data.status!=='active')throw new Error('本局已结束，请刷新资料后再返回选关。');
  if(!latest.etag)throw new Error('无法核验对局状态，请重试退出。');
  return request(attempt.links.self,{method:'PATCH',body:{status:'abandoned'},headers:{'If-Match':latest.etag}});
}
