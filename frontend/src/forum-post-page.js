/** 独立帖子详情：评论分页、两层回复、通知直接定位与失败保留输入。 */
import { initAuth } from './auth.js?v=20261020-body-only';
import { ForumClient, validateText } from './forum-client.js';
import { contentCard, node, bindCount, showError } from './forum-view.js?v=20261021-thread-height';

const auth=initAuth(),client=new ForumClient(),$=selector=>document.querySelector(selector);
const params=new URLSearchParams(location.search),raw=params.get('id'),postId=/^[1-9]\d*$/.test(raw||'')?Number(raw):0;
const status=$('#forum-status'),comments=$('#forum-comments'),context=$('#forum-context'),body=$('#comment-body'),submit=$('#comment-submit'),formStatus=$('#comment-status');
const updateCount=bindCount(body,$('#comment-count'),500);
let cursor=null,commentBusy=false,started=false,target=null,revision=0;
const replyPages=new Map();

/** 点赞按服务端结果显示；登录过期由共享账号入口处理。 */
async function like(item,kind){
  try{if(!client.user){await auth.requireLogin(async()=>{try{await client.like(kind,item.id,false);await load();}catch(error){showError(error,status);}});return;}return await client.like(kind,item.id,item.liked_by_me);}
  catch(error){showError(error,status);}
}

/** 回复目标固定展示，失败待重试时不允许悄悄改换目标或负载。 */
function reply(item){
  if(client.pending.size){formStatus.textContent='请先重试当前待确认的评论。';return;}
  void auth.requireLogin(()=>{target=item;$('#comment-target').textContent=`回复 ${item.username}`;$('#comment-cancel').hidden=false;body.focus();$('#comment-form').scrollIntoView({block:'center',behavior:'smooth'});});
}

/** 清理回复选择，不覆盖用户正文。 */
function cancelReply(){target=null;$('#comment-target').textContent='发表评论';$('#comment-cancel').hidden=true;}

/** 详情卡片的评论数也可收起/展开讨论，右侧回复图标直接聚焦现有表单。 */
function toggleDiscussion(_,button){const panel=$('#forum-discussion');panel.hidden=!panel.hidden;button.setAttribute('aria-expanded',String(!panel.hidden));}

/** 回复帖子时清除评论目标，避免把新评论误发给上一次回复的人。 */
function replyToPost(){void auth.requireLogin(()=>{
  $('#forum-discussion').hidden=false;$('#forum-post .forum-count')?.setAttribute('aria-expanded','true');
  if(!client.pending.size)cancelReply();body.focus();
});}

/** 构造根评论和回复共用卡片，保持纯文本及固定两层展示。 */
function card(item){return contentCard(item,{kind:'comments',onLike:like,onReply:reply,onReplies:loadReplies});}

/** 每条根评论独立保存游标，展开失败保留按钮供重试。 */
async function loadReplies(root,container){
  let state=replyPages.get(root.id);
  if(state?.busy||state?.loaded&&!state.cursor)return;
  if(!state){state={cursor:null,busy:false,loaded:false};replyPages.set(root.id,state);}
  state.busy=true;const epoch=client.epoch,currentRevision=revision;
  let button=container.querySelector(':scope > button');
  if(!button){button=node('button','forum-load','加载回复');button.type='button';container.append(button);button.addEventListener('click',()=>void loadReplies(root,container));}
  button.disabled=true;button.textContent='正在读取回复…';
  try{
    const result=await client.read(`comments/${root.id}/replies${state.cursor?`?cursor=${state.cursor}`:''}`);
    if(currentRevision!==revision)return;
    for(const item of result.items)if(!container.querySelector(`[data-id="${item.id}"]`))container.insertBefore(card(item),button);
    // 通知先定位了后续回复时，后来展开前页仍保持时间/编号正序。
    for(const item of [...container.querySelectorAll(':scope > article')].sort((a,b)=>Number(a.dataset.id)-Number(b.dataset.id)))container.insertBefore(item,button);
    state.cursor=result.next_cursor;state.loaded=true;button.hidden=!state.cursor;button.textContent='加载更多回复';
    if(!container.querySelector('article'))container.insertBefore(node('p','forum-hint','还没有回复。'),button);
  }catch(error){if(!error.stale&&currentRevision===revision){showError(error,status);button.textContent='读取失败，重试回复';}}
  finally{if(epoch===client.epoch&&currentRevision===revision){state.busy=false;button.disabled=false;}}
}

/** 目标不在当前页时直接加载根和目标，不需要连续翻页。 */
async function locate(id,scroll=true){
  const currentRevision=revision;
  try{
    const result=await client.read(`posts/${postId}/comments/${id}`);if(currentRevision!==revision)return;
    let element=document.getElementById(`comment-${id}`);
    if(!element){
      let root=document.getElementById(`comment-${result.root.id}`);
      if(!root){context.replaceChildren(node('p','forum-hint','已定位到这条讨论'));root=card(result.root);context.append(root);}
      if(result.target.id!==result.root.id){
        const replies=root.querySelector('.forum-replies');replies.hidden=false;replies.append(card(result.target));
        root.querySelector('.forum-expand').setAttribute('aria-expanded','true');
      }
      element=document.getElementById(`comment-${id}`);
    }
    document.querySelectorAll('.forum-target').forEach(item=>item.classList.remove('forum-target'));
    element?.classList.add('forum-target');element?.setAttribute('tabindex','-1');
    if(scroll){element?.scrollIntoView({block:'center',behavior:'instant'});element?.focus({preventScroll:true});}
  }catch(error){if(!error.stale&&currentRevision===revision){showError(error,status);status.textContent+=' 可返回论坛或继续浏览本帖。';}}
}

/** 顶层评论每次最多20条，失败重试仍沿原游标读取。 */
async function loadComments(append=false){
  if(commentBusy)return;commentBusy=true;const epoch=client.epoch,currentRevision=revision;
  const message=$('#comments-status'),more=$('#comments-more'),retry=$('#comments-retry');
  message.textContent='正在读取评论…';more.disabled=true;retry.hidden=true;
  try{
    const result=await client.read(`posts/${postId}/comments${append&&cursor?`?cursor=${cursor}`:''}`);if(currentRevision!==revision)return;
    if(!append)comments.replaceChildren();
    for(const item of result.items)if(!comments.querySelector(`[data-id="${item.id}"]`)){
      const located=context.querySelector(`:scope > article[data-id="${item.id}"]`);comments.append(located||card(item));
    }
    if(!context.querySelector('article'))context.replaceChildren();
    cursor=result.next_cursor;more.hidden=!cursor;message.textContent=comments.children.length?'':'还没有评论，分享你的想法吧。';
  }catch(error){if(!error.stale&&currentRevision===revision){showError(error,message);retry.hidden=false;}}
  finally{if(epoch===client.epoch&&currentRevision===revision){commentBusy=false;more.disabled=false;}}
}

/** 详情可刷新、可收藏，编号错误不发数据库请求。 */
async function load(){
  const currentRevision=++revision;commentBusy=false;replyPages.clear();cursor=null;comments.replaceChildren();context.replaceChildren();$('#forum-post').replaceChildren();
  $('#forum-discussion').hidden=true;$('#forum-retry').hidden=true;
  if(!postId||!Number.isSafeInteger(postId)){status.textContent='帖子编号无效，请返回论坛。';return;}
  status.textContent='正在读取帖子…';
  try{
    const item=await client.read(`posts/${postId}`);if(currentRevision!==revision)return;
    $('#forum-post').append(contentCard(item,{onLike:like,onComments:toggleDiscussion,onReply:replyToPost,commentsId:'forum-discussion',commentsExpanded:true}));document.title='帖子详情 · 无职游戏';status.textContent='';$('#forum-discussion').hidden=false;
    await loadComments();if(params.get('comment')&&/^[1-9]\d*$/.test(params.get('comment')))await locate(params.get('comment'));
  }catch(error){if(!error.stale&&currentRevision===revision){showError(error,status);$('#forum-retry').hidden=false;}}
}

$('#comment-cancel').addEventListener('click',()=>{if(!client.pending.size)cancelReply();});
$('#forum-retry').addEventListener('click',()=>void load());
$('#comments-more').addEventListener('click',()=>void loadComments(true));
$('#comments-retry').addEventListener('click',()=>void loadComments(Boolean(comments.children.length)));
$('#comment-form').addEventListener('submit',event=>{
  event.preventDefault();if(submit.disabled)return;
  void auth.requireLogin(async()=>{
    let text;try{text=validateText(body.value,500);}catch(error){formStatus.textContent=error.message;return;}
    const epoch=client.epoch;submit.disabled=true;body.readOnly=true;$('#comment-cancel').disabled=true;formStatus.textContent='正在发布…';
    try{
      const result=await client.publish(`posts/${postId}/comments`,{body:text,reply_to_comment_id:target?.id||null});if(!result)return;
      body.value='';updateCount();cancelReply();formStatus.textContent='评论已发布。';
      await load();await locate(result.id);
    }catch(error){showError(error,formStatus);if(!error.stale)formStatus.textContent+=' 原文已保留，请重试。';}
    finally{if(epoch===client.epoch){submit.disabled=false;submit.textContent=client.pending.size?'重试发布':'发表评论';body.readOnly=Boolean(client.pending.size);$('#comment-cancel').disabled=Boolean(client.pending.size);}}
  });
});
document.addEventListener('auth-changed',event=>{
  if(!started)return;client.setUser(event.detail.user);cancelReply();body.value='';updateCount();body.readOnly=false;submit.disabled=false;submit.textContent='发表评论';$('#comment-cancel').disabled=false;formStatus.textContent='';void load();
});
document.addEventListener('user-profile-updated',()=>void load());
auth.ready.then(()=>{started=true;client.setUser(auth.currentUser);void load();});
