/** 正文发帖契约：表单仅提供正文，旧标题不出现在卡片，正文安全显示且可进入详情。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {contentCard} from '../src/forum-view.js';

/** 最小渲染 DOM，只记录文本/节点/属性，验证正文链接与历史标题的可见性。 */
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.textContent='';this.classList={remove(){},add(){}};}
  append(...children){this.children.push(...children);}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(){}
}

/** 按真实树结构收集纯文本及可导航链接，避免靠源码匹配判断展示行为。 */
function flatten(node){return [node,...node.children.flatMap(flatten)];}

test('发布表单只有正文输入，不再要求标题',async()=>{
  const html=await readFile(new URL('../forum.html',import.meta.url),'utf8');
  assert.doesNotMatch(html,/id="forum-title-input"|name="title"/);
  assert.match(html,/<label for="forum-body-input">/);
});

test('列表以正文进入详情，详情不显示历史标题或重复正文',t=>{
  const original=globalThis.document;t.after(()=>{globalThis.document=original;});
  globalThis.document={createElement:tag=>new Element(tag)};
  const item={id:1,title:'旧标题不应出现',body:'正文\n<script>安全文字</script>',excerpt:'正文\n<script>安全文字</script>',username:'玩家',avatar_id:1,created_at:'2026-10-20T12:00:00',like_count:0,liked_by_me:false,comment_count:0};
  const list=flatten(contentCard(item,{summary:true}));
  assert.equal(list.some(node=>node.textContent.includes(item.title)),false);
  const link=list.find(node=>node.tagName==='a'&&node.className==='forum-post-link');
  assert.equal(link.textContent,item.excerpt);assert.equal(link.href,'./forum-post.html?id=1');
  const detail=flatten(contentCard(item));
  assert.equal(detail.some(node=>node.textContent.includes(item.title)),false);
  assert.equal(detail.filter(node=>node.textContent===item.body).length,1);
});
