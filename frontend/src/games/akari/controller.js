/** 照明页面：入门及15关选关、分步教学、灯光反馈、续玩和下一关。 */
import { createAkariSession } from './session.js';
import { akariTutorialSteps } from './tutorial.js';
import { inspectAkari, akariCell } from './rules.js';
import { createScope } from '../../shared/lifecycle.js';
import { energyHint } from '../../features/progression/attempt-energy.js';
import { createEnergyNotice } from '../../features/progression/energy-notice.js';
import { Events, emit } from '../../shared/events.js';
import { createExitConfirmation } from '../exit-confirmation.js';
import { availableMineStars, paintMineStars as paintStars, createStarCollection } from '../mine/stars.js';

/** 秒表不限制游戏时长，正式成绩取服务器活动时间。 */
export function akariTime(ms) {
  const seconds=Math.floor(Math.max(0,ms)/1000);
  return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
}

/** 星数仅作预览：旧版本沿用固定三星，最终成绩始终使用服务端结算。 */
export function availableAkariStars(level,attempt,elapsed,confirmed=null) {
  if(Number.isInteger(confirmed))return confirmed;
  if(attempt?.puzzle.tutorial||level?.max_stars===1)return 1;
  if(attempt?.reward)return attempt.reward.timed_stars?availableMineStars(attempt.reward,elapsed):3;
  if(level&&attempt&&level.level_version!==attempt.level_version)return 3;
  return availableMineStars(level,elapsed);
}

/** 账号生命周期由journey页面管理；本控制器只拥有照明区域。 */
export function createAkariJourney({host,auth,onReward=()=>{}}) {
  const scope=createScope();
  const energyNotice=createEnergyNotice();scope.add(()=>energyNotice.destroy());
  let model,identity,ready=Promise.resolve(),dead=false,selectionOnly=false,errorMessage='',boardKey='',pendingFocus=null,pendingLevel=null,resultShown=null;
  host.innerHTML=`
    <section id="akari-selector" aria-label="照明选关">
      <div class="akari-intro"><div><p class="eyebrow">AKARI / 让光抵达每一个角落</p><h2>从一盏灯，点亮整片世界。</h2><p>入门与十五道谜题，沿着光线，一步步找到答案。</p></div><img src="./assets/bulb.webp" alt="" width="88" height="88"></div>
      <div id="akari-levels" class="akari-levels" role="group" aria-label="选择照明关卡"></div>
      <p id="akari-selection-note" class="akari-selection-note">正在加载关卡…</p>
    </section>
    <section id="akari-play" class="akari-play" aria-labelledby="akari-title" hidden>
      <div class="akari-topbar"><button id="akari-back" type="button">返回选关</button><span>无职游戏</span><button id="akari-restart" type="button">重新开始</button></div>
      <div class="akari-heading"><img src="./assets/bulb.webp" alt="" width="72" height="72"><div><p id="akari-kicker" class="eyebrow">AKARI</p><h2 id="akari-title">照明</h2><p>让光，抵达每一个角落。</p></div></div>
      <div class="akari-toolbar"><span id="akari-focus" hidden></span><div class="akari-available"><span>可得星数</span><span id="akari-available-stars" class="mine-rating" aria-live="polite"></span></div><div class="akari-tools-right"><p id="akari-three-star" class="akari-three-star"></p><div class="akari-time-row"><span id="akari-clock-label">本关用时</span><strong id="akari-clock">00:00</strong><button id="akari-pause-toggle" type="button" aria-pressed="false" aria-label="暂停游戏" title="暂停游戏"><svg class="akari-pause-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14"/></svg><svg class="akari-resume-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m8 4 12 8-12 8Z"/></svg></button></div></div></div>
      <div class="akari-board-wrap"><div id="akari-viewport" class="akari-viewport" tabindex="0" role="region" aria-label="照明棋盘，已适应屏幕大小"><div id="akari-board" class="akari-board" role="group" aria-label="照明棋盘"></div></div><div id="akari-pause" class="akari-pause" hidden><strong>棋局已暂停</strong><p>准备好后，继续点亮。</p><button id="akari-resume" class="journey-primary" type="button">继续游戏</button></div></div>
      <p id="akari-status" class="akari-status" role="status"></p><p id="akari-conflicts" class="akari-conflicts" role="status" aria-live="polite"></p>
      <div id="akari-guide" class="akari-guide" role="status" hidden><p id="akari-guide-count" class="eyebrow"></p><h3 id="akari-guide-title"></h3><p id="akari-guide-text"></p><p id="akari-guide-target" class="akari-guide-target" hidden></p></div>
      <p id="akari-policy-note" class="akari-guide" role="status" hidden>这局沿用开始时的奖励规则。重新开始后采用当前规则；首次三星仅将该局实际新增经验翻倍，历史已三星不补发。</p>
      <details id="akari-instructions" class="akari-instructions" hidden><summary>玩法说明</summary><p>点击白格放灯，再点一次撤灯。灯光沿横竖传播，遇黑墙或边界停止；黑墙不可放灯。</p><p>照亮全部白格、灯泡之间不互照、每个数字墙上下左右的灯数恰好符合，三个条件同时满足才通关；斜角不计。棋盘会随屏幕大小自动缩放。</p><p>普通关按有效用时评星，点击暂停图标可暂停计时，继续后再计时。入门固定获得1星、2经验。</p></details>
      <button id="akari-result-open" type="button" hidden>查看通关结果</button>
      <div id="akari-save-status" class="akari-save-status" role="status" hidden><p>棋盘已完成，正在保存成绩。网络中断时可以重试。</p><button id="akari-retry-settlement" class="journey-primary" type="button">重试保存成绩</button></div>
    </section>
    <div class="akari-feedback"><p id="akari-message" role="status" aria-live="polite"></p><button id="akari-reload" type="button" hidden>重新加载</button></div>
    <dialog id="akari-result" class="journey-rules akari-result" aria-labelledby="akari-result-title" aria-describedby="akari-result-description"><p class="eyebrow">每一束光，都算数。</p><h2 id="akari-result-title"></h2><div id="akari-result-stars" class="mine-rating"></div><p id="akari-result-description"></p><div class="journey-actions"><button id="akari-result-home" type="button">返回选关</button><button id="akari-next" class="journey-primary" type="button">下一关 →</button></div></dialog>
    <dialog id="akari-enter-dialog" class="journey-rules" aria-labelledby="akari-enter-title" aria-describedby="akari-enter-description"><h2 id="akari-enter-title">是否闯关？</h2><p id="akari-enter-description"></p><div class="journey-actions"><button id="akari-enter-cancel" type="button" autofocus>暂不闯关</button><button id="akari-enter-confirm" class="journey-primary" type="button">确认闯关</button></div></dialog>
    <dialog id="akari-restart-dialog" class="journey-rules" aria-labelledby="akari-restart-title"><h2 id="akari-restart-title">重新开始本关？</h2><p>本关灯泡将清空，其他关卡的进度会保留。</p><p id="akari-restart-energy"></p><div class="journey-actions"><button id="akari-restart-cancel" type="button">继续当前局</button><button id="akari-restart-confirm" class="journey-primary" type="button">确认重开</button></div></dialog>`;
  const $=id=>host.querySelector('#'+id);
  const page=host.closest('.journey-page');
  const exitConfirmation=createExitConfirmation({host,scope,getSession:()=>model,onExit:back,
    onError:error=>{errorMessage=error.message;if(error.status===401)emit(Events.AUTH_EXPIRED);if(model)render(model.state);}});
  const collection=createStarCollection({onComplete:reward=>{
    if(dead||reward.userId!==identity)return;
    emit(Events.PROGRESSION_CONFIRMED,{userId:identity,progression:reward.progression});emit(Events.RECORDS_UPDATED);
  }});

  /** 请求错误只写回发起请求的会话，不污染新账号。 */
  async function run(work) {
    const expected=model;errorMessage='';
    try{await work();}catch(error){if(dead||model!==expected)return;if(!energyNotice.handle(error))errorMessage=error.message;if(error.status===401)emit(Events.AUTH_EXPIRED);}
    if(!dead&&model===expected)render(model.state);
  }
  /** 手机开始后回到棋局顶部，避免选关收起后停在页面底部。 */
  async function play(work) {
    const expected=model;await run(work);
    if(!dead&&model===expected&&!errorMessage&&!selectionOnly&&model.state.attempt)$('akari-play').scrollIntoView({behavior:'instant',block:'start'});
  }
  /** 以实际行列、格线和面板开销计算正方形格子，完整呈现棋盘。 */
  function fitBoard(){
    const attempt=model?.state.attempt,play=$('akari-play');
    if(!attempt||play.hidden)return;
    const viewport=$('akari-viewport'),board=$('akari-board'),wrap=viewport.parentElement;
    const {rows,cols}=attempt.puzzle,style=getComputedStyle(viewport);
    // clientWidth包含内边距；另外扣除棋盘2px边框及每条1px格线。
    const width=viewport.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)-2-(cols-1);
    // 棋盘下方的教学、规则可随页面阅读，不挤占整盘展示的空间。
    const overhead=wrap.getBoundingClientRect().top-play.getBoundingClientRect().top;
    const chrome=wrap.offsetHeight-board.offsetHeight;
    // 按缩放前高度适配，使浏览器原生缩放同时放大格子、数字与灯泡。
    const visual=window.visualViewport;
    const screenHeight=visual?Math.round(visual.height*visual.scale):window.innerHeight;
    const height=screenHeight-overhead-chrome-18-(rows-1);
    const size=Math.min(52,width/cols,Math.max(1,height)/rows);
    board.style.setProperty('--akari-cell-size',`${size>=1?Math.floor(size):size}px`);
  }
  /** 选关只展示编号、尺寸及历史成绩，不展示内部难度参数。 */
  function renderSelection(state) {
    const focused=$('akari-levels').contains(document.activeElement)?document.activeElement.dataset.level:null;
    const fragment=document.createDocumentFragment();
    for(const level of state.levels) {
      const progress=state.progress.find(v=>v.level_id===level.level_id),button=document.createElement('button');
      button.type='button';button.className='akari-level';button.dataset.level=level.level_id;button.disabled=state.busy||!state.enabled;
      button.setAttribute('aria-pressed',String(state.selected===level.level_id));
      button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-controls','akari-enter-dialog');
      const title=document.createElement('strong'),size=document.createElement('span'),stars=document.createElement('span'),note=document.createElement('small');
      title.textContent=level.name;size.textContent=`${level.rows} × ${level.cols}`;stars.className='mine-rating';
      paintStars(stars,progress?.best_stars||0,`历史最高${progress?.best_stars||0}星`,level.max_stars||3);
      note.textContent=progress?.current_attempt?'进行中':progress?.best_stars?'已通关':level.number===0?'放灯与撤灯教学':'尚未通关';
      button.append(title,size,stars,note);fragment.append(button);
    }
    $('akari-levels').replaceChildren(fragment);
    if(focused&&!state.busy)$('akari-levels').querySelector(`[data-level="${focused}"]`)?.focus({preventScroll:true});
    const selected=state.levels.find(v=>v.level_id===state.selected);
    $('akari-selection-note').textContent=selected?`${selected.name} · ${selected.number===0?'七步认识照明规则，完成教学获得1星、2经验。':`三星 ≤ ${akariTime(selected.t3_ms)}，二星 ≤ ${akariTime(selected.t2_ms)}，其余通关1星；经验2 / 4 / 6，升星补差额，首次三星当局新增经验翻倍，历史不补发。`}`:'暂时没有可用关卡。';
    $('akari-enter-confirm').disabled=state.busy||!state.enabled||!selected;
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
    const steps=akariTutorialSteps(puzzle),guide=steps[state.tutorialStep];
    const key=JSON.stringify([state.attempt.attempt_id,[...state.board.bulbs],state.busy,state.pending,state.paused,state.attempt.status,state.tutorialStep]);
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
        if(state.attempt.status==='active'&&!state.pending&&guide){
          const target=index===guide.index;
          cell.classList.toggle('tutorial-focus',Boolean(guide.focus?.includes(index)));
          cell.classList.toggle('tutorial-target',target);
          if(target)cell.setAttribute('aria-label',`${cell.getAttribute('aria-label')}，当前引导目标`);
        }
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
    page?.classList.toggle('akari-playing',playing);
    $('akari-message').textContent=errorMessage||state.message;
    $('akari-reload').hidden=Boolean(state.levels.length)||state.busy;
    if(!playing){$('akari-result').close();$('akari-board').replaceChildren();boardKey='';return;}
    const level=state.levels.find(v=>v.level_id===state.attempt.level_id);
    $('akari-policy-note').hidden=!level||state.attempt.level_version===level.level_version;
    const tutorial=Boolean(state.attempt.puzzle.tutorial);
    $('akari-kicker').textContent=`${level?.name||'照明'} / AKARI`;
    $('akari-focus').hidden=!tutorial;$('akari-focus').textContent=tutorial?level?.focus||'照明入门':'';
    $('akari-guide').hidden=!tutorial;$('akari-instructions').hidden=!tutorial;
    $('akari-three-star').textContent=tutorial?'入门完成固定1星':state.attempt.reward?.timed_stars===false?'本局通关固定三星':`三星条件：${akariTime(state.attempt.reward?.t3_ms??level?.t3_ms??0)} 内完成`;
    const steps=akariTutorialSteps(state.attempt.puzzle),guide=steps[state.tutorialStep];
    $('akari-guide-count').hidden=!guide;$('akari-guide-title').hidden=!guide;
    $('akari-guide-count').textContent=guide?`第${state.tutorialStep+1}步 / 共${steps.length}步`:'';
    $('akari-guide-title').textContent=guide?.title||'';
    $('akari-guide-text').textContent=guide?.text||level?.guide||'';
    $('akari-guide-target').hidden=!Number.isInteger(guide?.index);
    $('akari-guide-target').textContent=Number.isInteger(guide?.index)?`当前操作：第${Math.floor(guide.index/state.attempt.puzzle.cols)+1}行第${guide.index%state.attempt.puzzle.cols+1}列 · ${guide.bulb?'放灯':'撤灯'}（金色粗框）`:'';
    $('akari-restart').disabled=state.busy||state.pending;
    $('akari-back').disabled=state.busy;
    $('akari-pause-toggle').disabled=state.busy||state.pending||state.attempt.status!=='active';
    $('akari-pause-toggle').classList.toggle('is-paused',state.paused);
    $('akari-pause-toggle').setAttribute('aria-pressed',String(state.paused));
    $('akari-pause-toggle').setAttribute('aria-label',state.paused?'继续游戏':'暂停游戏');
    $('akari-pause-toggle').title=state.paused?'继续游戏':'暂停游戏';
    $('akari-restart-energy').textContent=energyHint(state.attempt.puzzle.tutorial,true);
    $('akari-pause').hidden=!state.paused||state.pending||Boolean(state.result);
    $('akari-resume').disabled=state.busy;
    renderBoard(state);timing();
    $('akari-save-status').hidden=!state.pending;
    $('akari-result-open').hidden=!state.result;
    $('akari-next').disabled=state.busy||!state.result||level?.number===15;
    $('akari-retry-settlement').hidden=!state.pending;$('akari-retry-settlement').disabled=state.busy;
    const allComplete=state.levels.every(item=>state.progress.some(progress=>progress.level_id===item.level_id&&progress.best_stars>0));
    $('akari-result-title').textContent=state.result?(level?.number===15&&allComplete?'入门与15关，全部点亮！':'本关已点亮！'):'棋盘已完成，正在保存成绩';
    // 将每项数值与单位保持在一起，窄屏不会把“6”和“经验”拆到两行。
    const details=state.result?[`用时 ${akariTime(state.result.duration_ms)}`,`本次新增 ${state.result.awarded_stars} 星`,`${state.result.awarded_xp} 经验`,...(state.result.first_three_star_bonus?[`含首次三星加成 ${state.result.first_three_star_bonus} 经验`]:[])]:[];
    $('akari-result-description').replaceChildren(...details.flatMap((text,index)=>{
      const span=document.createElement('span');span.className='akari-result-detail';span.textContent=text;
      return index?[' · ',span]:[span];
    }));
    paintStars($('akari-result-stars'),state.result?.stars||0,'本关成绩',level?.max_stars||3);
    $('akari-next').textContent=level?.number===15?'已到最后一关':`下一关：第${(level?.number||0)+1}关 →`;
    if(!state.result){resultShown=null;$('akari-result').close();}
    else if(resultShown!==state.attempt.attempt_id){resultShown=state.attempt.attempt_id;$('akari-result').showModal();}
    fitBoard();
  }
  /** 时钟更新不触发棋盘或选关重建。 */
  function timing(){
    if(!model?.state.attempt)return;
    const state=model.state,elapsed=model.elapsed(),level=state.levels.find(v=>v.level_id===state.attempt.level_id);
    $('akari-clock').textContent=akariTime(elapsed);
    $('akari-clock-label').textContent=state.paused&&!state.pending&&!state.result?'已暂停':'本关用时';
    const count=availableAkariStars(level,state.attempt,elapsed,state.result?.stars);
    paintStars($('akari-available-stars'),count,`本关可得${count}星`,state.attempt.puzzle.tutorial?1:3);
  }
  /** 仅在服务端确认退出后切换选关，移除当前棋盘视图及续玩状态。 */
  function back(){selectionOnly=true;collection.cancel();emit(Events.SETTLEMENT_CLOSED);boardKey='';$('akari-board').replaceChildren();render(model.state);focusSelected();}
  /** 弹窗取消或返回选关后，把键盘焦点放回对应关卡卡片。 */
  function focusSelected(){if(model)$('akari-levels').querySelector(`[data-level="${model.state.selected}"]`)?.focus({preventScroll:true});}
  /** 只展示所选关卡及续玩说明，确认前不创建尝试或开始计时。 */
  function askToEnter(id){
    const state=model.state,level=state.levels.find(item=>item.level_id===id);
    if(!level||state.busy||!state.enabled)return;
    model.select(id);pendingLevel=id;
    const continuing=state.progress.some(item=>item.level_id===id&&item.current_attempt);
    $('akari-enter-title').textContent=`是否挑战${level.name}？`;
    $('akari-enter-description').textContent=`${level.rows} × ${level.cols}。${level.number===0?'七步学习照明规则。':''}${continuing?'确认后继续上次的棋局，不重复消耗体力。':energyHint(level.difficulty==='tutorial')}${level.number===0?'':`三星${akariTime(level.t3_ms)}内，二星${akariTime(level.t2_ms)}内，其余通关1星；经验2 / 4 / 6。`}`;
    $('akari-enter-dialog').showModal();
  }
  /** 显式选择后打开，登录异步完成仍保留用户刚才选中的关卡。 */
  async function openSelected(id){
    await ready;if(dead)return;model.select(id);selectionOnly=false;
    await model.setPaused('selection',false,{sync:false});await play(()=>model.open());
  }
  scope.listen($('akari-levels'),'click',event=>{const button=event.target.closest('[data-level]');if(button)askToEnter(button.dataset.level);});
  scope.listen($('akari-enter-cancel'),'click',()=>$('akari-enter-dialog').close());
  scope.listen($('akari-enter-dialog'),'close',()=>{pendingLevel=null;if(!$('akari-selector').hidden)focusSelected();});
  scope.listen($('akari-enter-confirm'),'click',()=>{
    const selected=pendingLevel;if(!selected||model.state.busy)return;
    $('akari-enter-dialog').close();void auth.requireLogin(()=>openSelected(selected));
  });
  scope.listen($('akari-back'),'click',()=>void exitConfirmation.ask());
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
  scope.listen($('akari-pause-toggle'),'click',()=>void run(()=>model.setPaused('manual',!model.state.paused)));
  scope.listen($('akari-resume'),'click',()=>void run(()=>model.setPaused('manual',false)));
  scope.listen($('akari-retry-settlement'),'click',()=>void run(()=>model.complete()));
  scope.listen($('akari-reload'),'click',()=>void run(()=>model.load()));
  scope.listen($('akari-restart'),'click',()=>{$('akari-restart-dialog').showModal();void run(()=>model.setPaused('restart',true));});
  scope.listen($('akari-restart-cancel'),'click',()=>$('akari-restart-dialog').close());
  scope.listen($('akari-restart-dialog'),'close',()=>void run(()=>model.setPaused('restart',false)));
  scope.listen($('akari-restart-confirm'),'click',()=>{$('akari-restart-dialog').close();collection.cancel();emit(Events.SETTLEMENT_CLOSED);void play(()=>model.restart());});
  /** 通关后关闭弹窗并返回照明选关，保留已保存的成绩。 */
  scope.listen($('akari-result-home'),'click',()=>{$('akari-result').close();back();});
  scope.listen($('akari-result-open'),'click',()=>$('akari-result').showModal());
  scope.listen($('akari-result'),'close',()=>{collection.cancel();emit(Events.SETTLEMENT_CLOSED);if(!$('akari-play').hidden)$('akari-result-open').focus({preventScroll:true});});
  scope.listen($('akari-next'),'click',()=>{
    $('akari-result').close();
    const number=model.state.levels.find(v=>v.level_id===model.state.attempt.level_id)?.number;
    if(number===15){back();return;}
    const next=model.state.levels.find(v=>v.number===number+1);if(next){collection.cancel();emit(Events.SETTLEMENT_CLOSED);void openSelected(next.level_id);}
  });
  scope.listen(window,'resize',fitBoard);
  if(window.visualViewport)scope.listen(window.visualViewport,'resize',fitBoard);
  // 仅观察宽度并在下一帧适配，避免格子高度更新触发观察循环。
  let fitFrame=null,lastWidth=0;
  const observer=new ResizeObserver(entries=>{
    const width=entries[0].contentRect.width;if(width===lastWidth)return;lastWidth=width;
    if(fitFrame!==null)cancelAnimationFrame(fitFrame);
    fitFrame=requestAnimationFrame(()=>{fitFrame=null;fitBoard();});
  });
  observer.observe(host);
  scope.add(()=>{observer.disconnect();if(fitFrame!==null)cancelAnimationFrame(fitFrame);page?.classList.remove('akari-playing');});
  const timer=setInterval(timing,250);scope.add(()=>clearInterval(timer));
  scope.listen(document,'visibilitychange',()=>{if(document.hidden)collection.cancel();if(model)void run(()=>model.setPaused('hidden',document.hidden));});
  scope.listen(window,'pagehide',()=>{if(model)void model.setPaused('pagehide',true,{immediate:true}).catch(()=>{});});
  return {
    /** 换号立刻清空旧账号的棋盘和结算文本，再异步读取新账号资料。 */
    async setUser(uid){
      if(identity===uid&&model)return;
      energyNotice.clear();
      collection.cancel(false);identity=uid;model?.destroy();selectionOnly=false;boardKey='';pendingFocus=null;errorMessage='';resultShown=null;
      exitConfirmation.reset();
      $('akari-result').close();
      pendingLevel=null;$('akari-enter-dialog').close();$('akari-restart-dialog').close();
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
