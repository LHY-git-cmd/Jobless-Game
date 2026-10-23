/** 论坛正文列表：有限游标、登录续接发帖、固定负载重试和返回位置恢复。 */
import { cacheIds } from "../shared/dom.js";
import { Events } from "../shared/events.js";
import { initAuth } from '../features/account/auth.js';
import { ForumClient, validateText } from '../features/forum/client.js';
import { bindCount, showError } from '../features/forum/view.js';
import { createPostThread } from '../features/forum/discussion.js';

const ui = cacheIds({
  forumList: 'forum-list',
  forumStatus: 'forum-status',
  forumMore: 'forum-more',
  forumRetry: 'forum-retry',
  forumComposeDialog: 'forum-compose-dialog',
  forumForm: 'forum-form',
  forumBodyInput: 'forum-body-input',
  forumFormStatus: 'forum-form-status',
  forumSubmit: 'forum-submit',
  forumBodyCount: 'forum-body-count',
  forumCompose: 'forum-compose',
  forumComposeClose: 'forum-compose-close'
});

const auth=initAuth(),client=new ForumClient();
const list=ui.forumList,status=ui.forumStatus,more=ui.forumMore,retry=ui.forumRetry;
const dialog=ui.forumComposeDialog,form=ui.forumForm,body=ui.forumBodyInput,formStatus=ui.forumFormStatus,submit=ui.forumSubmit;
const bodyCount=bindCount(body,ui.forumBodyCount,2000);
let cursor=null,busy=false,started=false,pages=0,loadSerial=0,retryAppend=false;
const threads=new Map();

/** 移除旧列表时废弃其异步渲染资格，不让展开请求影响后来的页面。 */
function clearThreads(){for(const view of threads.values())view.dispose();threads.clear();list.replaceChildren();}

/** 同帖独立管理评论与输入，评论编号不参与帖子列表的去重。 */
function addThread(item){
  const view=createPostThread(item,{client,onLike:like,onError:error=>{if(error.status===401)showError(error,status);},
    onEditorOpen:id=>{for(const [otherId,thread] of threads)if(otherId!==id)thread.closeEditor();},
    onLogin:(id,target)=>void auth.requireLogin(async()=>{
      // 登录会重新读取个人点赞状态，续接时找到新卡片，避免聚焦已移除的输入框。
      try{await load();if(!threads.has(id))addThread(await client.read(`posts/${id}`));threads.get(id)?.reply(target);}
      catch(error){showError(error,status);}
    })});
  threads.set(item.id,view);list.append(view.element);
}

/** 页面失败只更新状态，晚到的旧身份响应不能改变当前页面。 */
async function like(item,kind) {
  try {
    if(!client.user){await auth.requireLogin(async()=>{try{await client.like(kind,item.id,false);await load();}catch(error){showError(error,status);}});return;}
    return await client.like(kind,item.id,item.liked_by_me);
  } catch(error){showError(error,status);}
}

/** 读取一页并只追加未出现的卡片，重试仍使用原游标。 */
async function load(append=false) {
  if(busy&&append)return;busy=true;const epoch=client.epoch,serial=++loadSerial;
  status.textContent='正在读取讨论…';more.disabled=true;retry.hidden=true;
  try {
    const result=await client.read(`posts${append&&cursor?`?cursor=${cursor}`:''}`);
    if(serial!==loadSerial)return;
    if(!append){
      // 新帖发布或头像刷新不移除正在输入/发送的评论，避免丢失原文和待确认编号。
      const drafts=[...threads].filter(([,view])=>view.hasDraft);
      for(const view of threads.values())if(!view.hasDraft)view.dispose();
      threads.clear();for(const [id,view] of drafts)threads.set(id,view);
      list.replaceChildren();pages=0;
    }
    for(const item of result.items)if(!threads.has(item.id))addThread(item);
    else if(!append)list.append(threads.get(item.id).element);
    if(!append)for(const view of threads.values())if(!view.element.isConnected)list.append(view.element);
    cursor=result.next_cursor;pages++;more.hidden=!cursor;status.textContent=list.children.length?'':'还没有讨论，来发表第一个帖子吧。';
  }catch(error){if(serial===loadSerial){showError(error,status);if(!error.stale){retry.hidden=false;retryAppend=append;}}}
  finally{if(epoch===client.epoch&&serial===loadSerial){busy=false;more.disabled=false;}}
}

/** 关闭时保留未确认的原文，打开后可继续使用相同请求编号重试。 */
function close(){dialog.close();ui.forumCompose.focus();}
ui.forumCompose.addEventListener('click',()=>void auth.requireLogin(()=>{dialog.showModal();body.focus();}));
ui.forumComposeClose.addEventListener('click',close);
dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
more.addEventListener('click',()=>void load(true));retry.addEventListener('click',()=>void load(retryAppend));
form.addEventListener('submit',async event=>{
  event.preventDefault();if(submit.disabled)return;
  let payload;
  try{payload={body:validateText(body.value,2000)};}
  catch(error){formStatus.textContent=error.message;return;}
  const epoch=client.epoch;submit.disabled=true;body.readOnly=true;form.setAttribute('aria-busy','true');formStatus.textContent='正在发布…';
  try{
    const result=await client.publish('posts',payload);if(!result)return;
    close();form.reset();bodyCount();formStatus.textContent='';status.textContent='帖子已发布。';await load();
  }catch(error){showError(error,formStatus);if(!error.stale)formStatus.textContent+=' 原文已保留，请使用本按钮重试。';}
  finally{if(epoch===client.epoch){submit.disabled=false;submit.textContent=client.pending.has('posts')?'重试发布':'发布';body.readOnly=client.pending.has('posts');form.setAttribute('aria-busy','false');}}
});

/** 换号后清空发布内容和旧账号点赞，公开讨论重新以当前身份读取。 */
document.addEventListener(Events.AUTH_CHANGED,event=>{
  if(!started)return;client.setUser(event.detail.user);busy=false;cursor=null;clearThreads();form.reset();formStatus.textContent='';
  body.readOnly=false;submit.disabled=false;submit.textContent='发布';bodyCount();if(dialog.open)close();void load();
});
document.addEventListener(Events.USER_PROFILE_UPDATED,()=>{busy=false;void load();});
window.addEventListener('pagehide',()=>{try{sessionStorage.setItem('forum-return',JSON.stringify({pages:Math.min(pages,5),y:scrollY}));}catch{}});
auth.ready.then(async()=>{
  started=true;client.setUser(auth.currentUser);await load();
  try{
    const saved=JSON.parse(sessionStorage.getItem('forum-return')||'null');
    while(saved&&cursor&&pages<saved.pages&&!busy)await load(true);
    if(saved)scrollTo(0,Math.max(0,Number(saved.y)||0));
  }catch{}
});
