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

/** 固定描边图标：拇指、对话气泡及纸飞机；按钮自身提供可访问名称。 */
export function actionIcon(name) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  for(const [key,value] of Object.entries({viewBox:'0 0 24 24',width:'20',height:'20',fill:'none',stroke:'currentColor','stroke-width':'1.7','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(key,value);
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');
  const paths={like:'M7 10v11H3V10h4Zm0 0 4-8a3 3 0 0 1 3 3v4h5a2 2 0 0 1 2 2.4l-1.4 7a3 3 0 0 1-3 2.6H7',reply:'M21 11.5a8.5 8.5 0 0 1-12.6 7.4L3 21l1.9-5.4A8.5 8.5 0 1 1 21 11.5Z',send:'m22 2-7 20-6-7-7-6L22 2ZM22 2 9 15'};
  path.setAttribute('d',paths[name]||paths.reply);
  svg.append(path);return svg;
}

/** 卡片由服务端确认的数据渲染，只有请求成功才更新点赞计数。 */
export function contentCard(item,{kind='posts',summary=false,onLike,onReply,onReplies,onComments,commentsId,commentsExpanded=false}={}) {
  const card=node('article','forum-card');card.dataset.id=item.id;
  if(kind==='comments')card.id=`comment-${item.id}`;
  const author=node('div','forum-author'),identity=node('span','forum-identity');
  identity.append(node('span','forum-username',item.username));
  // 发送者与接收者共用一个不换行的身份组，正文不再被回复关系额外占一行。
  const label=kind==='comments'&&item.reply_to_username?`${item.username} 回复 ${item.reply_to_username}`:item.username;
  if(kind==='comments'&&item.reply_to_username)identity.append(node('span','forum-relation','回复'),node('span','forum-reply-recipient',item.reply_to_username));
  identity.title=label;identity.setAttribute('aria-label',label);
  author.append(createAvatarImage(item.avatar_id),identity,timeLabel(item.created_at));card.append(author);
  const text=node('p',summary?'forum-excerpt':'forum-body');
  if(summary&&kind==='posts'){
    // 正文本身作为详情链接，不从正文另造一个标题，也不重复显示摘要。
    const link=node('a','forum-post-link',item.excerpt);link.href=`./forum-post.html?id=${item.id}`;text.append(link);
  }else text.textContent=summary?item.excerpt:item.body;
  card.append(text);
  const actions=node('div','forum-actions'),icons=node('div','forum-action-icons'),like=node('button','forum-like');like.type='button';
  const likeCount=node('span','forum-like-count');like.append(actionIcon('like'),likeCount);
  /** 当前对象的点赞展示总是来自服务端回包。 */
  function renderLike(){likeCount.textContent=String(item.like_count);like.setAttribute('aria-pressed',String(item.liked_by_me));like.setAttribute('aria-label',`${item.liked_by_me?'取消点赞':'点赞'}，${item.like_count} 个赞`);}
  renderLike();like.addEventListener('click',async()=>{
    if(like.disabled)return;
    like.disabled=true;
    try { const result=await onLike?.(item,kind);if(result){Object.assign(item,result);renderLike();} }
    finally { like.disabled=false; }
  });
  const reply=node('button','forum-reply');reply.type='button';reply.append(actionIcon('reply'));
  reply.setAttribute('aria-label',kind==='posts'?'回复帖子':`回复 ${item.username}`);
  reply.title=kind==='posts'?'回复帖子':`回复 ${item.username}`;
  reply.addEventListener('click',()=>onReply?.(item));icons.append(like,reply);
  if(kind==='posts'){
    const count=node('button','forum-count',`${item.comment_count} 条评论`);count.type='button';
    count.setAttribute('aria-expanded',String(commentsExpanded));if(commentsId)count.setAttribute('aria-controls',commentsId);
    count.addEventListener('click',()=>onComments?.(item,count,card));actions.append(count);
  } else {
    if(!item.root_comment_id) {
      const expand=node('button','forum-expand',`查看回复 · ${item.reply_count}`);expand.type='button';expand.setAttribute('aria-expanded','false');
      const replies=node('div','forum-replies');replies.hidden=true;replies.id=`replies-${item.id}`;expand.setAttribute('aria-controls',replies.id);
      expand.addEventListener('click',()=>{
        const show=replies.hidden;replies.hidden=!show;expand.setAttribute('aria-expanded',String(show));
        if(show)onReplies?.(item,replies,expand);
      });actions.append(expand,icons);card.append(actions,replies);return card;
    }
  }
  actions.append(icons);card.append(actions);return card;
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
