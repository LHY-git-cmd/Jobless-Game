/** 全站站内消息：可见且登录才轮询，消息失败不影响游戏，账号切换废弃旧响应。 */
import { forumRequest } from './forum-client.js';
import { createAvatarImage } from './avatar.js?v=20261020-avatars';

export class NotificationController {
  /** 可注入时钟与调度器，方便验证完成后调度、冷却和过载退避。 */
  constructor({request=forumRequest,onChange=()=>{},onUnauthorized=()=>{},setTimer=(fn,ms)=>globalThis.setTimeout(fn,ms),clearTimer=id=>globalThis.clearTimeout(id),now=Date.now}={}) {
    Object.assign(this,{request,onChange,onUnauthorized,setTimer,clearTimer,now});
    this.epoch=0;this.user=null;this.visible=true;this.timer=null;this.checking=false;this.loading=false;this.lastCheck=0;this.failures=0;
    this.state={count:0,latest_id:0,items:[],through_id:0,next_cursor:null,message:'',busy:false};
  }
  /** 通知消费者仅接收公开状态，不能取得会话凭据。 */
  emit() { this.onChange({...this.state,items:[...this.state.items]}); }
  /** 账号切换立即清理私人列表和未读数，即使请求取消失败也不会恢复旧数据。 */
  setUser(user) {
    if(this.user?.id===user?.id)return;
    this.stop();this.epoch++;this.user=user;this.checking=false;this.loading=false;this.lastCheck=0;this.failures=0;
    this.state={count:0,latest_id:0,items:[],through_id:0,next_cursor:null,message:'',busy:false};this.emit();
    if(user&&this.visible)void this.refresh();
  }
  /** 清除唯一计时器，隐藏和退出均调用。 */
  stop() { if(this.timer!==null)this.clearTimer(this.timer);this.timer=null; }
  /** 频繁切换标签页时保留五秒冷却。 */
  setVisible(visible) {
    this.visible=visible;this.stop();
    if(visible&&this.user) {
      const delay=Math.max(0,5000-(this.now()-this.lastCheck));
      if(delay)this.schedule(delay);else void this.refresh();
    }
  }
  /** 下一轮只在前一次请求结束后安排，永不积累 setInterval 并发。 */
  schedule(ms) {
    this.stop();
    if(this.user&&this.visible)this.timer=this.setTimer(()=>{this.timer=null;void this.refresh();},ms);
  }
  /** 读取轻量计数，失败指数退避且尊重服务器 Retry-After。 */
  async refresh() {
    if(!this.user||!this.visible||this.checking)return;
    this.stop();this.checking=true;const epoch=this.epoch;let delay=60000;
    try {
      const result=await this.request('notifications/unread-count');
      if(epoch!==this.epoch)return;
      if(!Number.isInteger(result.count)||result.count<0||result.count>100)throw new Error('消息服务返回异常。');
      this.state.count=result.count;this.state.latest_id=result.latest_id;this.failures=0;this.emit();
    } catch(error) {
      if(epoch!==this.epoch)return;
      delay=Math.max(Math.min(300000,60000*2**Math.min(++this.failures,3)),(error.retryAfter||0)*1000);
      if(error.status===401)this.onUnauthorized();
    } finally {
      if(epoch===this.epoch){this.checking=false;this.lastCheck=this.now();this.schedule(delay);}
    }
  }
  /** 主动打开才加载列表，单纯查看不改变已读；后续页保留首批查询边界。 */
  async load(more=false) {
    if(!this.user||this.loading||more&&!this.state.next_cursor)return;
    this.loading=true;this.state.busy=true;this.state.message='正在读取消息…';this.emit();
    const epoch=this.epoch;
    try {
      const result=await this.request(`notifications${more?`?cursor=${this.state.next_cursor}`:''}`);
      if(epoch!==this.epoch)return;
      if(!Array.isArray(result.items))throw new Error('消息服务返回异常。');
      const previous=more?this.state.items:[];
      this.state.items=[...new Map([...previous,...result.items].map(item=>[item.id,item])).values()];
      if(!more)this.state.through_id=result.through_id;
      this.state.next_cursor=result.next_cursor;this.state.message=this.state.items.length?'':'还没有消息，去论坛聊聊吧。';
    } catch(error) {
      if(epoch!==this.epoch)return;
      this.state.message=error.status===401?'登录已失效，请重新登录。':error.message;
      if(error.status===401)this.onUnauthorized();
    } finally {
      if(epoch===this.epoch){this.loading=false;this.state.busy=false;this.emit();}
    }
  }
  /** 点击单条才标记已读，成功结果用于更新计数。 */
  async read(id) { return this.mark(`notifications/${id}/read`,{method:'PUT'},id); }
  /** 使用首次列表查询返回的最大编号，不吞掉后来到达的消息。 */
  async readAll() { return this.mark('notifications/read-all',{method:'POST',body:{through_id:this.state.through_id}},null); }
  /** 写请求同样校验账号代数，失败时保留可重试的列表。 */
  async mark(path,options,id) {
    if(!this.user)return false;
    const epoch=this.epoch, boundary=this.state.through_id;
    try {
      const result=await this.request(path,options);
      if(epoch!==this.epoch)return false;
      this.state.items=this.state.items.map(item=>(id===null?item.id<=boundary:item.id===id)?{...item,read_at:item.read_at||new Date().toISOString()}:item);
      this.state.count=result.count;this.state.latest_id=result.latest_id;this.state.message='';this.emit();return true;
    } catch(error) {
      if(epoch!==this.epoch)return false;
      this.state.message=error.message;this.emit();if(error.status===401)this.onUnauthorized();return false;
    }
  }
}

/** 每个页面只创建一份铃铛和原生模态对话框，关闭后焦点回到铃铛。 */
export function initNotifications() {
  const host=document.querySelector('.auth-controls');
  if(!host||host.notificationController)return host?.notificationController;
  const bell=document.createElement('button');bell.type='button';bell.className='notification-bell hidden';
  bell.setAttribute('aria-haspopup','dialog');bell.setAttribute('aria-controls','notification-dialog');
  bell.innerHTML='<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg><span class="notification-count"></span>';
  host.prepend(bell);
  // 三个游戏界面复用同一消息控制器；跳转继续沿用现有棋局保存逻辑。
  const bells=[bell];let returnFocus=bell;
  for(const row of document.querySelectorAll('.game-panel .top-row')){
    const gameBell=bell.cloneNode(true);gameBell.classList.add('notification-game');row.append(gameBell);bells.push(gameBell);
  }
  const dialog=document.createElement('dialog');dialog.id='notification-dialog';dialog.className='notification-dialog';dialog.setAttribute('aria-labelledby','notification-title');
  dialog.innerHTML='<div class="notification-heading"><h2 id="notification-title">站内消息</h2><button type="button" class="notification-close" aria-label="关闭消息">×</button></div><div class="notification-toolbar"><button type="button" class="notification-read-all">全部已读</button><button type="button" class="notification-retry">刷新消息</button></div><p role="status" class="notification-status"></p><div class="notification-list"></div><button type="button" class="notification-more" hidden>加载更多消息</button>';
  document.body.append(dialog);
  const list=dialog.querySelector('.notification-list'),status=dialog.querySelector('.notification-status'),more=dialog.querySelector('.notification-more');
  let lastItems=null;
  const labels={post_like:'赞了你的帖子',comment_like:'赞了你的评论',comment:'评论了你的帖子',reply:'回复了你'};
  const controller=new NotificationController({
    onUnauthorized:()=>document.dispatchEvent(new Event('auth-expired')),
    onChange:state=>{
      for(const button of bells){
        button.classList.toggle('hidden',!controller.user);button.setAttribute('aria-label',`站内消息，${state.count>99?'99+':state.count} 条未读`);
        button.querySelector('span').textContent=state.count?(state.count>99?'99+':String(state.count)):'';
      }
      status.textContent=state.message;more.hidden=!state.next_cursor;more.disabled=state.busy;
      dialog.querySelector('.notification-read-all').disabled=state.busy||!state.through_id;
      dialog.querySelector('.notification-retry').disabled=state.busy;
      // 计数轮询不重新构建列表，避免键盘焦点被每分钟的回包移除。
      const signature=JSON.stringify(state.items);
      if(signature!==lastItems){
        lastItems=signature;list.replaceChildren();
        for(const item of state.items){
          const link=document.createElement('a');link.className=`notification-item${item.read_at?'':' is-unread'}`;
          link.href=`./forum-post.html?id=${item.post_id}${item.comment_id?`&comment=${item.comment_id}#comment-${item.comment_id}`:''}`;
          link.append(createAvatarImage(item.avatar_id));
          const text=document.createElement('span'),title=document.createElement('strong'),excerpt=document.createElement('span'),time=document.createElement('time');
          title.textContent=`${item.read_at?'':'未读 · '}${item.username}${labels[item.kind]||'与你互动'}`;
          excerpt.textContent=item.excerpt;time.textContent=new Date(item.created_at+'Z').toLocaleString('zh-CN');time.dateTime=item.created_at+'Z';
          text.append(title,excerpt,time);link.append(text);
          link.addEventListener('click',async event=>{
            if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey){void controller.read(item.id);return;}
            event.preventDefault();const destination=link.href;
            if(await controller.read(item.id))location.assign(destination);
          });list.append(link);
        }
      }
    },
  });
  host.notificationController=controller;
  /** 恢复焦点并避免换号后仍显示旧消息模态。 */
  function close(){dialog.close();returnFocus.focus();}
  for(const button of bells)button.addEventListener('click',()=>{returnFocus=button;dialog.showModal();void controller.load();});
  dialog.querySelector('.notification-close').addEventListener('click',close);
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  dialog.querySelector('.notification-retry').addEventListener('click',()=>void controller.load());
  more.addEventListener('click',()=>void controller.load(true));
  dialog.querySelector('.notification-read-all').addEventListener('click',()=>void controller.readAll());
  document.addEventListener('auth-changed',event=>{if(dialog.open)close();controller.setUser(event.detail.user);});
  document.addEventListener('visibilitychange',()=>controller.setVisible(!document.hidden));
  window.addEventListener('pagehide',()=>controller.setVisible(false));
  window.addEventListener('pageshow',()=>controller.setVisible(!document.hidden));
  controller.setVisible(!document.hidden);
  return controller;
}
