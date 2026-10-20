/** 论坛主题列表：有限游标、登录续接发帖、固定负载重试和返回位置恢复。 */
import { initAuth } from './auth.js?v=20261020-forum';
import { ForumClient, validateText } from './forum-client.js';
import { contentCard, bindCount, showError } from './forum-view.js';

const auth=initAuth(),client=new ForumClient();
const $=selector=>document.querySelector(selector),list=$('#forum-list'),status=$('#forum-status'),more=$('#forum-more'),retry=$('#forum-retry');
const dialog=$('#forum-compose-dialog'),form=$('#forum-form'),title=$('#forum-title-input'),body=$('#forum-body-input'),formStatus=$('#forum-form-status'),submit=$('#forum-submit');
const titleCount=bindCount(title,$('#forum-title-count'),80),bodyCount=bindCount(body,$('#forum-body-count'),2000);
let cursor=null,busy=false,started=false,pages=0,loadSerial=0,retryAppend=false;

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
    if(!append){list.replaceChildren();pages=0;}
    for(const item of result.items)if(!list.querySelector(`[data-id="${item.id}"]`))list.append(contentCard(item,{summary:true,onLike:like}));
    cursor=result.next_cursor;pages++;more.hidden=!cursor;status.textContent=list.children.length?'':'还没有讨论，来发表第一个主题吧。';
  }catch(error){if(serial===loadSerial){showError(error,status);if(!error.stale){retry.hidden=false;retryAppend=append;}}}
  finally{if(epoch===client.epoch&&serial===loadSerial){busy=false;more.disabled=false;}}
}

/** 关闭时保留未确认的原文，打开后可继续使用相同请求编号重试。 */
function close(){dialog.close();$('#forum-compose').focus();}
$('#forum-compose').addEventListener('click',()=>void auth.requireLogin(()=>{dialog.showModal();title.focus();}));
$('#forum-compose-close').addEventListener('click',close);
dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
more.addEventListener('click',()=>void load(true));retry.addEventListener('click',()=>void load(retryAppend));
form.addEventListener('submit',async event=>{
  event.preventDefault();if(submit.disabled)return;
  let payload;
  try{payload={title:validateText(title.value,80),body:validateText(body.value,2000)};}
  catch(error){formStatus.textContent=error.message;return;}
  const epoch=client.epoch;submit.disabled=true;title.readOnly=body.readOnly=true;form.setAttribute('aria-busy','true');formStatus.textContent='正在发布…';
  try{
    const result=await client.publish('posts',payload);if(!result)return;
    close();form.reset();titleCount();bodyCount();formStatus.textContent='';status.textContent='主题已发布。';await load();
  }catch(error){showError(error,formStatus);if(!error.stale)formStatus.textContent+=' 原文已保留，请使用本按钮重试。';}
  finally{if(epoch===client.epoch){submit.disabled=false;submit.textContent=client.pending.has('posts')?'重试发布':'发布主题';title.readOnly=body.readOnly=client.pending.has('posts');form.setAttribute('aria-busy','false');}}
});

/** 换号后清空发布内容和旧账号点赞，公开讨论重新以当前身份读取。 */
document.addEventListener('auth-changed',event=>{
  if(!started)return;client.setUser(event.detail.user);busy=false;cursor=null;list.replaceChildren();form.reset();formStatus.textContent='';
  title.readOnly=body.readOnly=false;submit.disabled=false;submit.textContent='发布主题';titleCount();bodyCount();if(dialog.open)close();void load();
});
document.addEventListener('user-profile-updated',()=>{busy=false;void load();});
window.addEventListener('pagehide',()=>{try{sessionStorage.setItem('forum-return',JSON.stringify({pages:Math.min(pages,5),y:scrollY}));}catch{}});
auth.ready.then(async()=>{
  started=true;client.setUser(auth.currentUser);await load();
  try{
    const saved=JSON.parse(sessionStorage.getItem('forum-return')||'null');
    while(saved&&cursor&&pages<saved.pages&&!busy)await load(true);
    if(saved)scrollTo(0,Math.max(0,Number(saved.y)||0));
  }catch{}
});
