/** 作用：验证零体力提示仅响应业务错误、不可点击、两秒淡出及重复触发/换号清理。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createEnergyNotice } from '../../../src/features/progression/energy-notice.js';

/** 记录显示、动画和到期清理；不依赖浏览器定时抖动或真实等待。 */
function fixture(){
  let serial=0;const nodes=[],timers=new Map(),animations=[];
  const dom={body:{append:node=>nodes.push(node)},createElement:tag=>({tagName:tag,style:{},attributes:{},
    setAttribute(key,value){this.attributes[key]=value;},remove(){nodes.splice(nodes.indexOf(this),1);},
    animate(frames,options){const animation={frames,options,cancelled:false,cancel(){this.cancelled=true;}};animations.push(animation);return animation;}})};
  const view={setTimeout(fn,delay){const id=++serial;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)};
  return {dom,view,nodes,timers,animations};
}

test('服务端确认零体力时显示指定小字，不拦截点击，2秒内从可见淡出并移除',()=>{
  const f=fixture(),notice=createEnergyNotice(f);
  assert.equal(notice.handle({code:'energy_insufficient'}),true);
  assert.equal(f.nodes.length,1);
  assert.equal(f.nodes[0].textContent,'当前体力为零，请稍后重试');
  assert.equal(f.nodes[0].style.pointerEvents,'none');
  assert.equal(f.nodes[0].attributes.role,'status');
  assert.equal(f.animations[0].frames[0].opacity,1);
  assert.equal(f.animations[0].frames.at(-1).opacity,0);
  assert.equal(f.animations[0].options.duration,2000);
  const timer=[...f.timers.values()][0];assert.equal(timer.delay,2000);
  timer.fn();assert.equal(f.nodes.length,0);
});

test('普通网络/版本错误不显示零体力提示，重复点击只有一条，销毁清理动画及计时器',()=>{
  const f=fixture(),notice=createEnergyNotice(f);
  assert.equal(notice.handle({code:'version_mismatch'}),false);
  assert.equal(notice.handle(new Error('网络中断')),false);
  assert.equal(f.nodes.length,0);
  notice.handle({code:'energy_insufficient'});notice.handle({code:'energy_insufficient'});
  assert.equal(f.nodes.length,1);assert.equal(f.timers.size,1);assert.equal(f.animations[0].cancelled,true);
  notice.clear();assert.equal(f.nodes.length,0);assert.equal(f.timers.size,0);
  notice.handle({code:'energy_insufficient'});notice.destroy();
  assert.equal(f.nodes.length,0);assert.equal(f.timers.size,0);
  notice.handle({code:'energy_insufficient'});assert.equal(f.nodes.length,0);
});
