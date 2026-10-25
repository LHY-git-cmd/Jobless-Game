/** 零体力反馈：仅显示不可交互的居中文字，2秒淡出，不改变棋局、体力或重试请求。 */
export function createEnergyNotice({dom=document,view=window}={}){
  let node=null,timer=null,animation=null,dead=false;

  /** 重复显示、换号或销毁时清理上一条提示，旧计时器不影响新提示。 */
  function clear(){
    if(timer!==null)view.clearTimeout(timer);
    timer=null;animation?.cancel();animation=null;node?.remove();node=null;
  }
  return {
    /** 只消费服务端的体力不足错误；其他错误仍交给原页面反馈。 */
    handle(error){
      if(error?.code!=='energy_insufficient')return false;
      if(dead)return true;
      clear();node=dom.createElement('div');node.className='energy-empty-notice';
      node.textContent='当前体力为零，请稍后重试';
      node.setAttribute('role','status');node.setAttribute('aria-live','polite');
      node.setAttribute('popover','manual');node.style.pointerEvents='none';
      dom.body.append(node);
      // 支持popover时进入顶层，确认弹窗上方也能看到；旧浏览器保留fixed回退。
      if(typeof node.showPopover==='function')node.showPopover();
      animation=node.animate?.([{opacity:1},{opacity:0}],{duration:2000,easing:'linear',fill:'forwards'});
      timer=view.setTimeout(clear,2000);return true;
    },
    clear,
    /** 页面销毁后不再显示迟到请求的提示。 */
    destroy(){dead=true;clear();},
  };
}
