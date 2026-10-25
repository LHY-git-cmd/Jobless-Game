/** 主动退出使用既有条件放弃接口；先核验权威状态，避免覆盖其他页面的结算。 */
import { api } from './client.js';

/** 丢失退出响应时可重读已放弃状态；失败不清理草稿，由调用方显示重试。 */
export async function abandonAttempt({attempt,request=api}) {
  const latest=await request(attempt.links.self);
  if(latest.data.status==='abandoned')return latest;
  if(latest.data.status!=='active')throw new Error('本局已结束，请刷新资料后再返回选关。');
  let version=latest.etag;
  // 本接口强版本约定为JSON中的整数revision；gzip代理可能只在响应头加上W/。
  // 只有头部与JSON版本一致时才使用该明确修订号，不把任意弱ETag当作强校验器。
  if(version?.startsWith('W/')){
    const revision=latest.data.revision;
    const expected=Number.isSafeInteger(revision)&&revision>=0?`"${revision}"`:null;
    version=expected&&version===`W/${expected}`?expected:null;
  }
  if(!version)throw new Error('无法核验对局状态，请重试退出。');
  return request(attempt.links.self,{method:'PATCH',body:{status:'abandoned'},headers:{'If-Match':version}});
}
