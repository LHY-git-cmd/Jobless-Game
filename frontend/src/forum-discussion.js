/** 列表帖子下的按需评论与直接回复，复用现有游标和固定负载幂等客户端。 */
import {validateText} from './forum-client.js';
import {contentCard,node,bindCount} from './forum-view.js?v=20261021-inline';

/** 每个帖子拥有独立展开、分页和输入状态；移除后废弃全部晚到回包。 */
export function createPostThread(item,{client,onLike,onLogin,onError=()=>{}}) {
  // 登录后续接可能读取单帖全文，统一取服务端正文的有限摘要供列表使用。
  item.excerpt??=Array.from(item.body||'').slice(0,160).join('');
  const element=node('div','forum-thread');element.dataset.postId=item.id;
  const panel=node('section','forum-inline-discussion');panel.id=`post-discussion-${item.id}`;panel.hidden=true;panel.setAttribute('aria-label','帖子评论');
  const list=node('div','forum-inline-comments'),message=node('p','forum-inline-status'),more=node('button','forum-inline-more','加载更多评论');
  message.setAttribute('role','status');more.type='button';more.hidden=true;
  const form=node('form','forum-inline-form');form.hidden=true;form.noValidate=true;
  const heading=node('div','forum-compose-target'),label=node('label','',`回复 ${item.username} 的帖子`),cancel=node('button','forum-inline-cancel','取消');
  const body=node('textarea','forum-inline-body');body.id=`inline-body-${item.id}`;body.name='body';body.rows=3;body.required=true;label.htmlFor=body.id;
  cancel.type='button';heading.append(label,cancel);
  const footer=node('div','forum-form-footer'),count=node('output','forum-inline-count'),submit=node('button','forum-inline-submit forum-primary','发送');
  count.id=`inline-count-${item.id}`;count.htmlFor=body.id;body.setAttribute('aria-describedby',count.id);submit.type='submit';footer.append(count,submit);
  const formStatus=node('p','forum-inline-form-status');formStatus.setAttribute('role','status');form.append(heading,body,footer,formStatus);
  const updateCount=bindCount(body,count,500),path=`posts/${item.id}/comments`;
  const replies=new Map();let alive=true,loaded=false,busy=false,cursor=null,target=null,commentsRequest=null;
  const post=contentCard(item,{summary:true,onLike,onReply:()=>reply(),onComments:()=>toggle(),commentsId:panel.id});
  panel.append(list,message,more,form);element.append(post,panel);

  /** 仍在当前页面与当前身份下才允许绘制响应。 */
  function active(epoch){return alive&&epoch===client.epoch;}

  /** 展开状态始终与按钮 aria-expanded 同步。 */
  function show(){panel.hidden=false;post.querySelector('.forum-count').setAttribute('aria-expanded','true');}

  /** 打开时才取首批评论，已加载内容反复收起/展开不会重复查询。 */
  function toggle(){
    if(panel.hidden){show();if(!loaded)void load();}
    else {panel.hidden=true;post.querySelector('.forum-count').setAttribute('aria-expanded','false');}
  }

  /** 评论与回复沿用同一套安全文本、图标和两层关系渲染。 */
  function commentCard(comment){return contentCard(comment,{kind:'comments',onLike,onReply:reply,onReplies:loadReplies});}

  /** 有限游标页失败保留原位置，重试不重复追加已有评论。 */
  async function load(append=false){
    if(!alive||busy)return;busy=true;const epoch=client.epoch;
    message.textContent='正在读取评论…';more.disabled=true;
    try{
      commentsRequest=client.read(`${path}${append&&cursor?`?cursor=${cursor}`:''}`);
      const result=await commentsRequest;if(!active(epoch))return;
      if(!append){list.replaceChildren();replies.clear();}
      for(const comment of result.items)if(!list.querySelector(`:scope > [data-id="${comment.id}"]`))list.append(commentCard(comment));
      for(const card of [...list.children].sort((a,b)=>Number(a.dataset.id)-Number(b.dataset.id)))list.append(card);
      loaded=true;cursor=result.next_cursor;more.hidden=!cursor;more.textContent='加载更多评论';
      message.textContent=list.children.length?'':'还没有评论，点右侧回复图标聊聊吧。';
    }catch(error){if(active(epoch)&&!error.stale){message.textContent=error.message;more.hidden=false;more.textContent='读取失败，重新加载';onError(error);}}
    finally{if(active(epoch)){busy=false;commentsRequest=null;more.disabled=false;}}
  }

  /** 每个根评论独立分页，回复展开后保持编号正序且不重复插入定位目标。 */
  async function loadReplies(root,container){
    let state=replies.get(root.id);
    if(state?.busy||state?.loaded&&!state.cursor)return;
    if(!state){state={cursor:null,busy:false,loaded:false};replies.set(root.id,state);}
    state.busy=true;const epoch=client.epoch;
    let button=container.querySelector(':scope > button');
    if(!button){button=node('button','forum-load','加载回复');button.type='button';container.append(button);button.addEventListener('click',()=>void loadReplies(root,container));}
    button.disabled=true;button.textContent='正在读取回复…';
    try{
      const result=await client.read(`comments/${root.id}/replies${state.cursor?`?cursor=${state.cursor}`:''}`);if(!active(epoch))return;
      for(const comment of result.items)if(!container.querySelector(`:scope > [data-id="${comment.id}"]`))container.insertBefore(commentCard(comment),button);
      for(const card of [...container.querySelectorAll(':scope > article')].sort((a,b)=>Number(a.dataset.id)-Number(b.dataset.id)))container.insertBefore(card,button);
      state.loaded=true;state.cursor=result.next_cursor;button.hidden=!state.cursor;button.textContent='加载更多回复';
      if(!container.querySelector('article'))container.insertBefore(node('p','forum-hint','还没有回复。'),button);
    }catch(error){if(active(epoch)&&!error.stale){message.textContent=error.message;button.textContent='读取失败，重试回复';onError(error);}}
    finally{if(active(epoch)){state.busy=false;button.disabled=false;}}
  }

  /** 列表原地回复帖子或任意评论，游客登录后由父页面续接当前帖子。 */
  function reply(comment=null){
    if(!alive)return;
    if(!client.user){onLogin?.(item.id,comment);return;}
    if(client.pending.has(path)){show();form.hidden=false;formStatus.textContent='原评论尚未确认，请先使用发送按钮重试。';body.focus();return;}
    target=comment;label.textContent=comment?`回复 ${comment.username}`:`回复 ${item.username} 的帖子`;
    show();form.hidden=false;formStatus.textContent='';body.focus();
    form.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    if(!loaded)void load();
  }

  /** 成功发布的评论直接定位，后续页的根上下文也通过单次接口取得。 */
  async function reveal(comment){
    let root=list.querySelector(`:scope > [data-id="${comment.root_comment_id||comment.id}"]`);
    let context=null;
    if(comment.root_comment_id){
      context=await client.read(`posts/${item.id}/comments/${comment.id}`);if(!alive)return;
      if(!root){root=commentCard(context.root);list.append(root);}
    }
    if(!root){root=commentCard(comment);list.append(root);}
    if(comment.root_comment_id){
      const container=root.querySelector('.forum-replies');container.hidden=false;root.querySelector('.forum-expand').setAttribute('aria-expanded','true');
      root.querySelector('.forum-expand').textContent=`查看回复 · ${context.root.reply_count}`;
      if(!container.querySelector(`[data-id="${comment.id}"]`))container.append(commentCard(comment));
    }
    for(const card of [...list.children].sort((a,b)=>Number(a.dataset.id)-Number(b.dataset.id)))list.append(card);
    message.textContent='';
  }

  more.addEventListener('click',()=>void load(loaded));
  cancel.addEventListener('click',()=>{form.hidden=true;post.querySelector('.forum-reply').focus();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(submit.disabled)return;
    if(!client.user){onLogin?.(item.id,target);return;}
    let text;try{text=validateText(body.value,500);}catch(error){formStatus.textContent=error.message;body.focus();return;}
    const epoch=client.epoch;submit.disabled=true;body.readOnly=true;form.setAttribute('aria-busy','true');formStatus.textContent='正在发送…';
    let saved=false;
    try{
      const result=await client.publish(path,{body:text,reply_to_comment_id:target?.id||null});if(!active(epoch)||!result)return;
      saved=true;
      body.value='';updateCount();target=null;label.textContent=`回复 ${item.username} 的帖子`;formStatus.textContent='评论已发送。';
      // 发布成功后即保留确认结果；只刷新当前帖计数，不重建其他帖子的输入。
      if(commentsRequest)await commentsRequest.catch(()=>{});if(!active(epoch))return;
      await reveal(result);
      const confirmed=await client.read(`posts/${item.id}`);if(active(epoch)){item.comment_count=confirmed.comment_count;post.querySelector('.forum-count').textContent=`${item.comment_count} 条评论`;}
    }catch(error){if(active(epoch)&&!error.stale){formStatus.textContent=saved?`评论已发送，显示更新失败：${error.message}`:`${error.message} 原文已保留，请重试。`;onError(error);}}
    finally{if(active(epoch)){submit.disabled=false;body.readOnly=client.pending.has(path);submit.textContent=client.pending.has(path)?'重试发送':'发送';form.setAttribute('aria-busy','false');}}
  });

  // 新帖子发布导致列表刷新时，尚未确认的重试负载仍回到原帖子输入框。
  const pending=client.pending.get(path);
  if(pending){target=pending.reply_to_comment_id?{id:pending.reply_to_comment_id,username:'原评论作者'}:null;body.value=pending.body;updateCount();body.readOnly=true;show();form.hidden=false;formStatus.textContent='原评论尚未确认，请重试发送。';submit.textContent='重试发送';void load();}
  return {element,reply,get hasDraft(){return Boolean(body.value||client.pending.has(path)||client.busy.has(path));},dispose(){alive=false;}};
}
