/** 正文发帖契约：表单仅提供正文，旧标题不出现在卡片，正文安全显示且可进入详情。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {contentCard} from '../../../src/features/forum/view.js';

/** 最小渲染 DOM，只记录文本/节点/属性，验证正文链接与历史标题的可见性。 */
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.listeners={};this.textContent='';this.classList={remove(){},add(){}};}
  append(...children){this.children.push(...children);}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(type,callback){this.listeners[type]=callback;}
  async click(){if(!this.disabled)return this.listeners.click?.();}
}

/** 按真实树结构收集纯文本及可导航链接，避免靠源码匹配判断展示行为。 */
function flatten(node){return [node,...node.children.flatMap(flatten)];}

test('发布表单只有正文输入，不再要求标题',async()=>{
  const html=await readFile(new URL('../../../forum.html',import.meta.url),'utf8');
  assert.doesNotMatch(html,/id="forum-title-input"|name="title"/);
  assert.match(html,/<label for="forum-body-input">/);
});

test('列表以正文进入详情，详情不显示历史标题或重复正文',t=>{
  const original=globalThis.document;t.after(()=>{globalThis.document=original;});
  globalThis.document={createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)};
  const item={id:1,title:'旧标题不应出现',body:'正文\n<script>安全文字</script>',excerpt:'正文\n<script>安全文字</script>',username:'玩家',avatar_id:1,created_at:'2026-10-20T12:00:00',like_count:0,liked_by_me:false,comment_count:0};
  const list=flatten(contentCard(item,{summary:true}));
  assert.equal(list.some(node=>node.textContent.includes(item.title)),false);
  const link=list.find(node=>node.tagName==='a'&&node.className==='forum-post-link');
  assert.equal(link.textContent,item.excerpt);assert.equal(link.href,'./forum-post.html?id=1');
  const detail=flatten(contentCard(item));
  assert.equal(detail.some(node=>node.textContent.includes(item.title)),false);
  assert.equal(detail.filter(node=>node.textContent===item.body).length,1);
});

test('帖子左侧评论数可点击，右侧拇指点赞与回复图标独立操作',async t=>{
  const original=globalThis.document;t.after(()=>{globalThis.document=original;});
  globalThis.document={createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)};
  const item={id:7,excerpt:'正文',username:'玩家',created_at:'2026-10-20T12:00:00',like_count:2,liked_by_me:false,comment_count:5};
  let expanded=0,replied=0,finish;
  const card=contentCard(item,{summary:true,onComments:()=>expanded++,onReply:()=>replied++,onLike:()=>new Promise(resolve=>{finish=resolve;})});
  const nodes=flatten(card),actions=nodes.find(node=>node.className==='forum-actions');
  const count=nodes.find(node=>node.className==='forum-count');
  assert.equal(count.tagName,'button');assert.equal(count.textContent,'5 条评论');
  assert.equal(actions.children[0],count);assert.equal(count.attributes['aria-expanded'],'false');
  await count.click();assert.equal(expanded,1);
  const right=actions.children.find(node=>node.className==='forum-action-icons');assert.ok(right);
  const like=right.children.find(node=>node.className==='forum-like'),reply=right.children.find(node=>node.className==='forum-reply');
  assert.ok(flatten(like).some(node=>node.tagName==='svg'&&node.attributes['aria-hidden']==='true'));
  assert.ok(flatten(reply).some(node=>node.tagName==='svg'));
  assert.equal(reply.attributes['aria-label'],'回复帖子');await reply.click();assert.equal(replied,1);
  const request=like.click();assert.equal(like.disabled,true);assert.equal(like.attributes['aria-pressed'],'false');
  finish({like_count:3,liked_by_me:true});await request;
  assert.equal(like.attributes['aria-pressed'],'true');assert.match(like.attributes['aria-label'],/取消点赞.*3/);
});

test('回复者、回复关系和接收者同属头像旁的一行，正文保持独立',t=>{
  const original=globalThis.document;t.after(()=>{globalThis.document=original;});
  globalThis.document={createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)};
  const card=contentCard({id:9,username:'first',reply_to_username:'test',root_comment_id:3,body:'正文',created_at:'2026-10-21T00:00:00',like_count:0,liked_by_me:false},{kind:'comments'});
  const author=card.children.find(node=>node.className==='forum-author');
  const identity=author.children.find(node=>node.className==='forum-identity');assert.ok(identity);
  assert.deepEqual(identity.children.map(node=>node.textContent),['first','回复','test']);
  assert.equal(identity.attributes['aria-label'],'first 回复 test');
  assert.equal(card.children.some(node=>node.className==='forum-reply-label'),false);
  assert.equal(card.children.find(node=>node.className==='forum-body').textContent,'正文');
});

test('主帖与评论标记独立层级，主帖头像比评论大4px',t=>{
  const original=globalThis.document;t.after(()=>{globalThis.document=original;});
  globalThis.document={createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)};
  const item={id:4,username:'玩家',body:'文字',created_at:'2026-10-21T00:00:00',like_count:0,liked_by_me:false};
  const post=contentCard(item),comment=contentCard({...item,root_comment_id:1},{kind:'comments'});
  assert.equal(post.dataset.kind,'posts');assert.equal(comment.dataset.kind,'comments');
  const image=card=>flatten(card).find(node=>node.tagName==='img');
  assert.equal(image(post).width-image(comment).width,4);
});
