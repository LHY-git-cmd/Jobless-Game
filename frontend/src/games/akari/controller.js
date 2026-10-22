/** 照明页面：入门及15关选关、分步教学、灯光反馈、续玩和下一关。 */
import { createAkariSession } from './session.js';
import { inspectAkari, akariCell } from './rules.js';
import { createScope } from '../../shared/lifecycle.js';
import { Events, emit } from '../../shared/events.js';
import { paintMineStars as paintStars, createStarCollection } from '../mine/stars.js';

/** 秒表不限制游戏时长，正式成绩取服务器活动时间。 */
export function akariTime(ms) {
  const seconds=Math.floor(Math.max(0,ms)/1000);
  return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
}

/** 账号生命周期由journey页面管理；本控制器只拥有照明区域。 */
export function createAkariJourney({host,auth,onReward=()=>{}}) {
  const scope=createScope();
  let model,identity,ready=Promise.resolve(),dead=false,selectionOnly=false,errorMessage='',boardKey='',pendingFocus=null;
  host.innerHTML=`
    <section id="akari-selector" aria-label="照明选关">
      <div class="akari-intro"><div><p class="eyebrow">AKARI / 让光抵达每一个角落</p><h2>从一盏灯，点亮整片世界。</h2><p>入门与十五道谜题，沿着光线，一步步找到答案。</p></div><img src="./assets/bulb.webp" alt="" width="88" height="88"></div>
      <div id="akari-levels" class="akari-levels" role="group" aria-label="选择照明关卡"></div>
      <div class="akari-start-row"><p id="akari-selection-note">正在加载关卡…</p><button id="akari-start" class="journey-primary" type="button" disabled>开始游戏 →</button></div>
    </section>
    <section id="akari-play" class="akari-play" aria-labelledby="akari-title" hidden>
      <div class="akari-topbar"><button id="akari-back" type="button">返回选关</button><span>无职游戏</span><button id="akari-restart" type="button">重新开始</button></div>
      <div class="akari-heading"><img src="./assets/bulb.webp" alt="" width="72" height="72"><div><p id="akari-kicker" class="eyebrow">AKARI</p><h2 id="akari-title">照明</h2><p>让光，抵达每一个角落。</p></div></div>
      <div class="akari-toolbar"><span id="akari-focus"></span><div><span>本关用时</span><strong id="akari-clock">00:00</strong><button id="akari-rules" type="button">规则</button></div></div>
      <div id="akari-guide" class="akari-guide" role="status" hidden></div>
      <p class="akari-instructions">点击白格放灯，再点一次撤灯。黑墙不可放灯；数字只计算上下左右。棋盘可在区域内滑动。</p>
      <div class="akari-board-wrap"><div id="akari-viewport" class="akari-viewport" tabindex="0" role="region" aria-label="可滚动照明棋盘"><div id="akari-board" class="akari-board" role="group" aria-label="照明棋盘"></div></div><div id="akari-pause" class="akari-pause" hidden><strong>棋局已暂停</strong><p>准备好后，继续点亮。</p><button id="akari-resume" class="journey-primary" type="button">继续游戏</button></div></div>
      <p id="akari-status" class="akari-status" role="status"></p><p id="akari-conflicts" class="akari-conflicts" role="status" aria-live="polite"></p>
      <div id="akari-result" class="akari-result" role="status" hidden><p class="eyebrow">每一束光，都算数。</p><h3 id="akari-result-title"></h3><div id="akari-result-stars" class="mine-rating"></div><p id="akari-result-description"></p><div class="journey-actions"><button id="akari-next" class="journey-primary" type="button">下一关 →</button><button id="akari-retry-settlement" class="journey-primary" type="button" hidden>重试保存成绩</button></div></div>
    </section>
    <div class="akari-feedback"><p id="akari-message" role="status" aria-live="polite"></p><button id="akari-reload" type="button" hidden>重新加载</button></div>
    <dialog id="akari-rules-dialog" class="journey-rules" aria-labelledby="akari-rules-title"><h2 id="akari-rules-title">照明规则</h2><ol><li>在白格放灯，灯光沿横竖方向传播，遇黑墙或边界停止。</li><li>照亮全部白格。灯泡之间不能互相照射。</li><li>数字黑墙上下左右的灯泡数量必须恰好等于数字；斜角不计算。</li><li>三个条件同时满足才通关。可随时撤灯修改，不限时，也不要求最少灯泡。</li></ol><p>阅读规则期间暂停计时。</p><button id="akari-rules-close" class="journey-primary" type="button">知道了，继续</button></dialog>
    <dialog id="akari-restart-dialog" class="journey-rules" aria-labelledby="akari-restart-title"><h2 id="akari-restart-title">重新开始本关？</h2><p>本关灯泡将清空，其他关卡的进度会保留。</p><div class="journey-actions"><button id="akari-restart-cancel" type="button">继续当前局</button><button id="akari-restart-confirm" class="journey-primary" type="button">确认重开</button></div></dialog>`;
  const $=id=>host.querySelector('#'+id);
  const collection=createStarCollection({onComplete:reward=>{
    if(dead||reward.userId!==identity)return;
    emit(Events.PROGRESSION_CONFIRMED,{userId:identity,progression:reward.progression});emit(Events.RECORDS_UPDATED);
  }});

  /** 请求错误只写回发起请求的会话，不污染新账号。 */
  async function run(work) {
    const expected=model;errorMessage='';
    try{await work();}catch(error){if(dead||model!==expected)return;errorMessage=error.message;if(error.status===401)emit(Events.AUTH_EXPIRED);}
    if(!dead&&model===expected)render(model.state);
  }
  /** 手机开始后回到棋局顶部，避免选关收起后停在页面底部。 */
  async function play(work) {
    const expected=model;await run(work);
    if(!dead&&model===expected&&!errorMessage&&!selectionOnly&&model.state.attempt)$('akari-play').scrollIntoView({behavior:'instant',block:'start'});
  }
  /** 选关只展示编号、尺寸及历史成绩，不展示内部难度参数。 */
  function renderSelection(state) {
    const focused=$('akari-levels').contains(document.activeElement)?document.activeElement.dataset.level:null;
    const fragment=document.createDocumentFragment();
    for(const level of state.levels) {
      const progress=state.progress.find(v=>v.level_id===level.level_id),button=document.createElement('button');
      button.type='button';button.className='akari-level';button.dataset.level=level.level_id;button.disabled=state.busy;
      button.setAttribute('aria-pressed',String(state.selected===level.level_id));
      const title=document.createElement('strong'),size=document.createElement('span'),stars=document.createElement('span'),note=document.createElement('small');
      title.textContent=level.name;size.textContent=`${level.rows} × ${level.cols}`;stars.className='mine-rating';
      paintStars(stars,progress?.best_stars||0,`历史最高${progress?.best_stars||0}星`,level.max_stars||3);
      note.textContent=progress?.current_attempt?'进行中':progress?.best_stars?'已通关':level.number===0?'放灯与撤灯教学':'尚未通关';
      button.append(title,size,stars,note);fragment.append(button);
    }
    $('akari-levels').replaceChildren(fragment);
    if(focused&&!state.busy)$('akari-levels').querySelector(`[data-level="${focused}"]`)?.focus({preventScroll:true});
    const selected=state.levels.find(v=>v.level_id===state.selected);
    $('akari-selection-note').textContent=selected?`${selected.name} · ${selected.focus}。通关不限时，可随时修改。`:'暂时没有可用关卡。';
    $('akari-start').disabled=state.busy||!state.enabled||!selected;
    $('akari-start').textContent=state.busy?'正在准备…':state.progress.find(v=>v.level_id===state.selected)?.current_attempt?'继续游戏 →':model.hasSaved(state.selected)?'查看上局 →':'开始游戏 →';
  }
  /** 汇总错误文本，明确区分全亮与全部约束满足。 */
  function feedback(inspection,board) {
    if(inspection.conflictingBulbs.size)return '有灯泡互相照射，请撤下或调整标红的灯。';
    if(inspection.wrongClues.size)return '数字黑墙旁的灯太多，请检查标红的数字。';
    if(inspection.lit.size===inspection.whiteCount&&inspection.unmetClues.size){
      const index=inspection.unmetClues.values().next().value,cols=board.level.cols;
      return `棋盘已全亮，但尚未通关：第${Math.floor(index/cols)+1}行第${index%cols+1}列需要${akariCell(index,board)}盏相邻灯，目前${inspection.clueCounts.get(index)}盏。`;
    }
    return '';
  }
  /** 灯泡与错误状态变化时重建格子，250ms时钟更新不重绘棋盘。 */
  function renderBoard(state) {
    const puzzle=state.attempt.puzzle,inspection=inspectAkari(state.board);
    const key=JSON.stringify([state.attempt.attempt_id,[...state.board.bulbs],state.busy,state.pending,state.paused,state.attempt.status]);
    if(key!==boardKey){
      boardKey=key;
      const focused=$('akari-board').contains(document.activeElement)?document.activeElement.dataset.index:null;
      if(focused!==null)pendingFocus=focused;
      const fragment=document.createDocumentFragment();$('akari-board').style.setProperty('--akari-cols',puzzle.cols);
      for(let index=0;index<puzzle.rows*puzzle.cols;index++){
        const type=akariCell(index,state.board),bulb=state.board.bulbs.has(index),cell=document.createElement('button');
        cell.type='button';cell.className='akari-cell';cell.dataset.index=index;
        const label=`第${Math.floor(index/puzzle.cols)+1}行第${index%puzzle.cols+1}列`;
        cell.disabled=type!=='.'||state.busy||state.pending||state.paused||state.attempt.status!=='active';
        if(type!=='.'){
          cell.classList.add('wall');cell.textContent=type==='#'?'':type;
          cell.setAttribute('aria-label',`${label}，${type==='#'?'黑墙':`数字${type}，相邻${inspection.clueCounts.get(index)}盏灯`}`);
        }else{
          cell.classList.toggle('lit',inspection.lit.has(index));cell.classList.toggle('bulb',bulb);cell.setAttribute('aria-pressed',String(bulb));
          cell.setAttribute('aria-label',`${label}，${bulb?'已放灯':inspection.lit.has(index)?'已照亮':'未照亮'}`);
        }
        const wrong=inspection.conflictingBulbs.has(index)||inspection.wrongClues.has(index)||(inspection.lit.size===inspection.whiteCount&&inspection.unmetClues.has(index));
        cell.classList.toggle('error',wrong);if(wrong)cell.setAttribute('aria-invalid','true');
        fragment.append(cell);
      }
      $('akari-board').replaceChildren(fragment);
      if(pendingFocus!==null){const target=$('akari-board').querySelector(`[data-index="${pendingFocus}"]`);if(target&&!target.disabled){target.focus({preventScroll:true});pendingFocus=null;}}
    }
    $('akari-status').textContent=`已照亮：${inspection.lit.size} / ${inspection.whiteCount} 格；已放灯：${state.board.bulbs.size} 盏`;
    $('akari-conflicts').textContent=feedback(inspection,state.board);
  }
  /** 游戏和选关切换只改变本区域，顶部账号由共享页面管理。 */
  function render(state) {
    if(dead)return;
    renderSelection(state);
    const playing=Boolean(state.attempt&&state.board&&!selectionOnly);
    $('akari-selector').hidden=playing;$('akari-play').hidden=!playing;
    $('akari-message').textContent=errorMessage||state.message;
    $('akari-reload').hidden=Boolean(state.levels.length)||state.busy;
    if(!playing)return;
    const level=state.levels.find(v=>v.level_id===state.attempt.level_id);
    $('akari-kicker').textContent=`${level?.name||'照明'} / AKARI`;$('akari-focus').textContent=level?.focus||'';
    $('akari-guide').hidden=!(level?.number<=5)&&!state.attempt.puzzle.tutorial;
    $('akari-guide').textContent=state.attempt.puzzle.tutorial?[
      '第1步：在任意白格放一盏灯，观察光线沿横竖方向传播。',
      '第2步：再次点击刚才的灯泡撤灯。放错位置也能随时修改。',
      '第3步：照亮所有白格，让灯泡不互照，并满足每个数字。数字只计算上下左右。'
    ][state.tutorialStep]:level?.guide||'';
    $('akari-restart').disabled=state.busy||state.pending;$('akari-rules').disabled=state.busy;
    $('akari-pause').hidden=!state.paused||state.pending||Boolean(state.result);
    $('akari-resume').disabled=state.busy;
    renderBoard(state);timing();
    $('akari-result').hidden=!state.result&&!state.pending;
    $('akari-next').hidden=!state.result;$('akari-next').disabled=state.busy;
    $('akari-retry-settlement').hidden=!state.pending;$('akari-retry-settlement').disabled=state.busy;
    const allComplete=state.levels.every(item=>state.progress.some(progress=>progress.level_id===item.level_id&&progress.best_stars>0));
    $('akari-result-title').textContent=state.result?(level?.number===15&&allComplete?'入门与15关，全部点亮！':'本关已点亮！'):'棋盘已完成，正在保存成绩';
    $('akari-result-description').textContent=state.result?`用时 ${akariTime(state.result.duration_ms)} · 本次新增 ${state.result.awarded_stars} 星、${state.result.awarded_xp} 经验。`:'如果网络中断，点击重试即可继续保存本次结果。';
    paintStars($('akari-result-stars'),state.result?.stars||0,'本关成绩',level?.max_stars||3);
    $('akari-next').textContent=level?.number===15?'返回选关 →':`下一关：第${(level?.number||0)+1}关 →`;
  }
  /** 时钟更新不触发棋盘或选关重建。 */
  function timing(){if(model?.state.attempt)$('akari-clock').textContent=akariTime(model.elapsed());}
  /** 返回时保留当前局，独立记录选关暂停原因。 */
  function back(){selectionOnly=true;collection.cancel();emit(Events.SETTLEMENT_CLOSED);void run(()=>model.setPaused('selection',true));render(model.state);$('akari-start').focus();}
  /** 显式选择后打开，登录异步完成仍保留用户刚才选中的关卡。 */
  async function openSelected(id){
    await ready;if(dead)return;model.select(id);selectionOnly=false;
    await model.setPaused('selection',false,{sync:false});await play(()=>model.open());
  }
  scope.listen($('akari-levels'),'click',event=>{const button=event.target.closest('[data-level]');if(button)model.select(button.dataset.level);});
  scope.listen($('akari-start'),'click',()=>{const selected=model.state.selected;void auth.requireLogin(()=>openSelected(selected));});
  scope.listen($('akari-back'),'click',back);
  scope.listen($('akari-board'),'click',event=>{const cell=event.target.closest('[data-index]');if(cell)void run(()=>model.toggle(Number(cell.dataset.index)));});
  scope.listen($('akari-board'),'keydown',event=>{
    const cell=event.target.closest('[data-index]');if(!cell||!model.state.board)return;
    const index=Number(cell.dataset.index),board=model.state.board,cols=board.level.cols;
    const step={ArrowLeft:-1,ArrowRight:1,ArrowUp:-cols,ArrowDown:cols}[event.key];if(!step)return;
    let next=index+step;
    // 左右键停在本行边界，不跨行跳转；上下键保持所在列。
    while(next>=0&&next<board.level.rows*cols&&(Math.abs(step)!==1||Math.floor(next/cols)===Math.floor(index/cols))){
      const target=$('akari-board').querySelector(`[data-index="${next}"]`);if(!target.disabled){event.preventDefault();target.focus();return;}next+=step;
    }
  });
  scope.listen($('akari-rules'),'click',()=>{$('akari-rules-dialog').showModal();void run(()=>model.setPaused('rules',true));});
  scope.listen($('akari-rules-close'),'click',()=>$('akari-rules-dialog').close());
  scope.listen($('akari-rules-dialog'),'close',()=>void run(()=>model.setPaused('rules',false)));
  scope.listen($('akari-resume'),'click',()=>void run(()=>model.setPaused('selection',false)));
  scope.listen($('akari-retry-settlement'),'click',()=>void run(()=>model.complete()));
  scope.listen($('akari-reload'),'click',()=>void run(()=>model.load()));
  scope.listen($('akari-restart'),'click',()=>{if(model.state.attempt.status==='active'){$('akari-restart-dialog').showModal();void run(()=>model.setPaused('restart',true));}else void play(()=>model.restart());});
  scope.listen($('akari-restart-cancel'),'click',()=>$('akari-restart-dialog').close());
  scope.listen($('akari-restart-dialog'),'close',()=>void run(()=>model.setPaused('restart',false)));
  scope.listen($('akari-restart-confirm'),'click',()=>{$('akari-restart-dialog').close();collection.cancel();emit(Events.SETTLEMENT_CLOSED);void play(()=>model.restart());});
  scope.listen($('akari-next'),'click',()=>{
    const number=model.state.levels.find(v=>v.level_id===model.state.attempt.level_id)?.number;
    if(number===15){back();return;}
    const next=model.state.levels.find(v=>v.number===number+1);if(next){collection.cancel();emit(Events.SETTLEMENT_CLOSED);void openSelected(next.level_id);}
  });
  const timer=setInterval(timing,250);scope.add(()=>clearInterval(timer));
  scope.listen(document,'visibilitychange',()=>{if(document.hidden)collection.cancel();if(model)void run(()=>model.setPaused('hidden',document.hidden));});
  scope.listen(window,'pagehide',()=>{if(model)void model.setPaused('pagehide',true,{immediate:true}).catch(()=>{});});
  return {
    /** 换号立刻清空旧账号的棋盘和结算文本，再异步读取新账号资料。 */
    async setUser(uid){
      if(identity===uid&&model)return;
      collection.cancel(false);identity=uid;model?.destroy();selectionOnly=false;boardKey='';pendingFocus=null;errorMessage='';
      $('akari-rules-dialog').close();$('akari-restart-dialog').close();
      $('akari-board').replaceChildren();$('akari-result-title').textContent='';$('akari-result-description').textContent='';$('akari-result-stars').replaceChildren();
      $('akari-play').hidden=true;$('akari-selector').hidden=false;
      let storage;try{storage=window.localStorage;}catch{/* 存储不可用由会话明确提示。 */}
      const next=createAkariSession({uid,storage,onChange:render,onReward:(result,{restored})=>{
        if(dead||identity!==uid)return;render(next.state);
        if(restored)emit(Events.PROGRESSION_CONFIRMED,{userId:uid,progression:result.progression});
        else{void collection.play({key:next.state.attempt.attempt_id,userId:uid,progression:result.progression,awardedStars:result.awarded_stars,source:$('akari-result-stars'),target:document.querySelector('.player-stars')});emit(Events.SETTLEMENT_OPENED,{runId:next.state.attempt.attempt_id});}
        onReward();
      }});model=next;
      if(document.hidden)await next.setPaused('hidden',true,{sync:false});
      ready=run(()=>next.load());await ready;
    },
    /** 刷新资料不创建新局。 */
    async refresh(){if(model&&!model.state.busy)await run(()=>model.load());},
    /** 卸载释放计时器、监听器和飞星效果。 */
    destroy(){dead=true;collection.cancel(false);model?.destroy();scope.dispose();emit(Events.SETTLEMENT_CLOSED);},
  };
}
