/** 论坛同源客户端：固定失败重试负载，代数隔离账号，明确设置点赞状态。 */
import { requestJson } from './lib/http.js';
import { createRequestId } from './ranking-client.js';

/** 与 Python strip 一致，补充 JS trim 未覆盖的控制空白并保留 BOM 字面内容。 */
export function validateText(value, max) {
  const text = typeof value === 'string' ? value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu, '') : '';
  if (!text) throw new Error('内容不能为空。');
  if (Array.from(text).length > max) throw new Error(`内容最多 ${max} 个字符。`);
  return text;
}

/** 请求独立超时，保留状态码和重试间隔供界面及轮询退避。 */
export async function forumRequest(path, options = {}) {
  const data = await requestJson(`/api/forum/${path}`, options);
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('服务返回异常，请重试。');
  return data;
}

export class ForumClient {
  /** 测试可注入传输和编号，生产凭据始终由 Cookie 管理。 */
  constructor(request = forumRequest, uuid = createRequestId) {
    this.request=request; this.uuid=uuid; this.epoch=0; this.user=null;
    this.pending=new Map(); this.busy=new Set();
  }
  /** 只有身份变动才丢弃待提交请求，头像更新保留当前输入。 */
  setUser(user) {
    if (this.user?.id === user?.id) { this.user=user; return; }
    this.user=user; this.epoch++; this.pending.clear(); this.busy.clear();
  }
  /** 所有响应必须与发起时账号相同。 */
  accept(result, epoch) {
    if (epoch!==this.epoch) { const error=new Error('账号已变更，请重试。'); error.stale=true; throw error; }
    return result;
  }
  /** 游客允许读取，读取结果同样隔离旧身份的点赞字段。 */
  async read(path) {
    const epoch=this.epoch;
    try{return this.accept(await this.request(path),epoch);}
    catch(error){this.accept(null,epoch);throw error;}
  }
  /** 第一次提交冻结负载，网络失败时不允许改变重试内容。 */
  async publish(path, body) {
    if (!this.user) throw Object.assign(new Error('请先登录。'), {status:401});
    if (this.busy.has(path)) return null;
    const epoch=this.epoch;
    if (!this.pending.has(path)) this.pending.set(path,structuredClone({...body,request_id:this.uuid()}));
    const payload=this.pending.get(path);
    this.busy.add(path);
    try {
      const result=this.accept(await this.request(path,{method:'POST',body:payload}),epoch);
      this.pending.delete(path); return result;
    } catch(error){this.accept(null,epoch);throw error;}
    finally { if(epoch===this.epoch)this.busy.delete(path); }
  }
  /** 同一内容请求未完成时禁止再次操作，成功后由服务端结果更新界面。 */
  async like(kind,id,liked) {
    if (!this.user) throw Object.assign(new Error('请先登录。'), {status:401});
    const path=`${kind}/${id}/like`, epoch=this.epoch;
    if(this.busy.has(path))return null;
    this.busy.add(path);
    try { return this.accept(await this.request(path,{method:liked?'DELETE':'PUT'}),epoch); }
    catch(error){this.accept(null,epoch);throw error;}
    finally { if(epoch===this.epoch)this.busy.delete(path); }
  }
}
