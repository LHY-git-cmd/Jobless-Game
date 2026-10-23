/** 三款游戏共用的主动退出确认：取消继续本局，服务端确认终止后才返回选关。 */
export function createExitConfirmation({host,scope,getSession,onExit,onError=()=>{}}) {
  const dialog=document.createElement('dialog');
  dialog.className='journey-rules';dialog.dataset.exitConfirmation='';
  const prefix=host.id||'game';
  dialog.setAttribute('aria-labelledby',`${prefix}-exit-title`);
  dialog.setAttribute('aria-describedby',`${prefix}-exit-description`);
  dialog.innerHTML=`<h2 id="${prefix}-exit-title">确认返回选关？</h2><p id="${prefix}-exit-description"></p><p data-exit-status role="alert"></p><div class="journey-actions"><button data-exit-cancel type="button" autofocus>继续游戏</button><button data-exit-confirm class="journey-primary" type="button">确认退出</button></div>`;
  host.append(dialog);
  const description=dialog.querySelector(`#${prefix}-exit-description`),status=dialog.querySelector('[data-exit-status]');
  const cancel=dialog.querySelector('[data-exit-cancel]'),confirm=dialog.querySelector('[data-exit-confirm]');
  let owner=null,version=0,confirming=false,dead=false;
  /** 换号、销毁或下一次弹窗后，旧请求不得关闭新弹窗或切换新账号页面。 */
  function current(session,stamp){return !dead&&owner===session&&getSession()===session&&version===stamp;}
  /** 同步禁用按钮，避免退出写请求期间重复提交或通过Esc切回棋盘。 */
  function busy(value){cancel.disabled=confirm.disabled=value;}
  /** 只在显式取消时解除本弹窗的暂停原因，保留手动暂停等其他原因。 */
  function closed(){
    // 原生close事件异步派发，旧弹窗的迟到事件不能清空刚重新打开的确认。
    if(dialog.open)return;
    const previous=owner;owner=null;version++;confirming=false;
    if(previous&&previous===getSession())void previous.setPaused('exit',false).catch(error=>{if(previous===getSession())onError(error);});
  }
  scope.listen(dialog,'close',closed);
  scope.listen(dialog,'cancel',event=>{if(confirming||cancel.disabled)event.preventDefault();});
  scope.listen(cancel,'click',()=>dialog.close());
  scope.listen(confirm,'click',async()=>{
    const session=owner,stamp=version;
    if(!session||confirming||session.state.busy)return;
    confirming=true;busy(true);status.textContent='正在结束本局…';
    try{
      const ended=await session.abandon();
      if(!current(session,stamp)||ended!==true)return;
      owner=null;dialog.close();onExit();
    }catch(error){
      if(current(session,stamp)){status.textContent=`退出失败：${error.message} 请重试，或继续当前局。`;onError(error);}
    }finally{if(current(session,stamp)){confirming=false;busy(false);}}
  });
  scope.add(()=>{dead=true;owner=null;version++;dialog.remove();});
  return {
    /** 询问期间暂停；暂停同步失败仍可重试退出，草稿不提前清理。 */
    async ask(){
      const session=getSession();if(!session?.state.attempt||session.state.busy||dialog.open)return;
      owner=session;confirming=false;const stamp=++version;status.textContent='';busy(true);
      const active=session.state.attempt.status==='active'&&!session.state.result;
      description.textContent=active?'确认后将按主动退出结束本局，棋盘进度不会保存，无法继续此局。已消耗的体力不返还；历史星数和等级保留。':'本局已结束。确认返回选关后，将清除本局的续玩草稿，已保存的成绩和成长保留。';
      dialog.showModal();
      try{await session.setPaused('exit',true);}
      catch(error){if(current(session,stamp)){status.textContent=`暂停同步失败：${error.message} 可重试退出或继续当前局。`;onError(error);}}
      finally{if(current(session,stamp))busy(false);}
    },
    /** 换号时直接失效弹窗，不对已销毁账号发送继续操作。 */
    reset(){owner=null;version++;confirming=false;dialog.close();},
  };
}
