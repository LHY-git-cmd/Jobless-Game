/** 论坛共享纯文本渲染：公开作者、码点输入提示、点赞及两层评论卡片。 */
import { createAvatarImage } from './avatar.js?v=20261020-avatars';

/** 通过 textContent 创建节点，用户文字不会进入 HTML 解析器。 */
export function node(tag,className,text='') {
  const element=document.createElement(tag);element.className=className;element.textContent=text;return element;
}

/** UTC 时间转为用户本地可读时间并保留机器可读值。 */
export function timeLabel(value) {
  const time=node('time','forum-time',new Date(value+'Z').toLocaleString('zh-CN'));
  time.dateTime=value+'Z';return time;
}

/** 卡片由服务端确认的数据渲染，只有请求成功才更新点赞计数。 */
export function contentCard(item,{kind='posts',summary=false,onLike,onReply,onReplies}={}) {
  const card=node('article','forum-card');card.dataset.id=item.id;
  if(kind==='comments')card.id=`comment-${item.id}`;
  const author=node('div','forum-author'),name=node('span','',item.username);
  author.append(createAvatarImage(item.avatar_id),name,timeLabel(item.created_at));card.append(author);
  if(kind==='posts') {
    const heading=node(summary?'h2':'h1','forum-post-title');
    if(summary){const link=node('a','forum-post-link',item.title);link.href=`./forum-post.html?id=${item.id}`;heading.append(link);}
    else heading.textContent=item.title;
    card.append(heading);
  } else if(item.reply_to_username)card.append(node('p','forum-reply-label',`回复 ${item.reply_to_username}`));
  card.append(node('p',summary?'forum-excerpt':'forum-body',summary?item.excerpt:item.body));
  const actions=node('div','forum-actions'),like=node('button','forum-like');like.type='button';
  /** 当前对象的点赞展示总是来自服务端回包。 */
  function renderLike(){like.textContent=`${item.liked_by_me?'已赞':'赞'} · ${item.like_count}`;like.setAttribute('aria-pressed',String(item.liked_by_me));like.setAttribute('aria-label',`${item.liked_by_me?'取消点赞':'点赞'}，${item.like_count} 个赞`);}
  renderLike();like.addEventListener('click',async()=>{
    if(like.disabled)return;
    like.disabled=true;
    try { const result=await onLike?.(item,kind);if(result){Object.assign(item,result);renderLike();} }
    finally { like.disabled=false; }
  });actions.append(like);
  if(kind==='posts')actions.append(node('span','forum-count',`${item.comment_count} 条讨论`));
  else {
    const reply=node('button','forum-reply','回复');reply.type='button';reply.addEventListener('click',()=>onReply?.(item));actions.append(reply);
    if(!item.root_comment_id) {
      const expand=node('button','forum-expand',`查看回复 · ${item.reply_count}`);expand.type='button';expand.setAttribute('aria-expanded','false');
      const replies=node('div','forum-replies');replies.hidden=true;replies.id=`replies-${item.id}`;expand.setAttribute('aria-controls',replies.id);
      expand.addEventListener('click',()=>{
        const show=replies.hidden;replies.hidden=!show;expand.setAttribute('aria-expanded',String(show));
        if(show)onReplies?.(item,replies,expand);
      });actions.append(expand);card.append(actions,replies);return card;
    }
  }
  card.append(actions);return card;
}

/** 输入计数采用 Array.from，避免 emoji 被计算为两个字符。 */
export function bindCount(input,output,max) {
  const update=()=>{const count=Array.from(input.value).length;output.textContent=`${count} / ${max}`;input.setAttribute('aria-invalid',String(count>max));};
  input.addEventListener('input',update);update();return update;
}

/** 401 统一清理全站当前身份；晚到响应不显示错误。 */
export function showError(error,status) {
  if(error.stale)return;
  if(error.status===401)document.dispatchEvent(new Event('auth-expired'));
  status.textContent=error.status===401?'登录已失效，请重新登录。':error.message;
}
