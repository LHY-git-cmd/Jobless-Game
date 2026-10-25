/** 扫雷页面：五档选关、四步教学、权威棋盘及账号成长结算。 */
import { createMineSession } from './session.js';
import { createScope } from '../../shared/lifecycle.js';
import { energyHint } from '../../features/progression/attempt-energy.js';
import { Events, emit } from '../../shared/events.js';
import { getAudioSettings } from '../../features/audio/settings.js';
import { createExplosionSequence, createExplosionSound, explosionOrder } from './effects.js';
import { availableMineStars, paintMineStars, createStarCollection } from './stars.js';
import { createExitConfirmation } from '../exit-confirmation.js';
import { remainingSafeCells, nextMineLevel, mineCellSize } from './presentation.js';

const DIFFICULTIES=[['tutorial','入门','从零学会'],['easy','简单','轻松起步'],['medium','中等','多想一步'],['hard','困难','步步推理'],['hell','地狱','极限挑战']];
const FLAG='<img src="./assets/minesweeper/v2/flag.webp" width="24" height="24" alt="">';
// 顶部操作图标统一线宽，文字保留为按钮名称，图形仅作辅助提示。
const RESTART_ICON='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M19 12a7 7 0 0 0-12-5L4 10m1 2a7 7 0 0 0 12 5l3-3"/></svg>';
const SETTINGS_ICON='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9.5 3-.7 2.1-2 .9-2-.4-2 3.4 1.4 1.7v2.6L2.8 15l2 3.4 2-.4 2 .9.7 2.1h4l.7-2.1 2-.9 2 .4 2-3.4-1.4-1.7v-2.6L20.2 9l-2-3.4-2 .4-2-.9-.7-2.1Z"/><circle cx="11.5" cy="12" r="3"/></svg>';

/** 秒数向下显示，星级仍按服务端毫秒判定。 */
export function mineTime(ms){const seconds=Math.max(0,Math.floor(ms/1000));return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;}

/** auth由页面共享，控制器换号时销毁旧会话及所有动画。 */
export function createMineJourney({host,auth,onReward=()=>{}}) {
  const scope=createScope(),settings=getAudioSettings();
  let model,identity,selectionOnly=false,lastId=null,lastOutcome=null,animation=null,finished=true,dead=false,errorMessage='';
  let renderedBoard='',resultShown=null;
  const page=host.closest('.journey-page');
  let identityReady=Promise.resolve();
  let pendingLevel=null;
  const sound=createExplosionSound(new URL('../../../assets/audio/explosion.wav',import.meta.url));
  // 模板只包含开发者静态结构；接口文本和用户状态统一使用textContent。
  host.innerHTML=`
    <div id="mine-selector" class="mine-selector">
      <div class="mine-intro"><div><p class="eyebrow">MINESWEEPER · 每一步，都有线索</p><h2>选一个难度，开始推理。</h2><p>找到所有安全格，把星星带回旅程。</p></div><img src="./assets/minesweeper/v2/theme.webp" width="84" height="84" alt=""></div>
      <div id="mine-difficulties" class="mine-difficulties" role="group" aria-label="扫雷难度"></div>
      <div class="mine-options-heading"><h3 id="mine-options-title">选择棋盘</h3><span>全部难度自由选择</span></div>
      <div id="mine-specs" class="mine-specs" role="group" aria-labelledby="mine-options-title"></div>
      <div class="mine-start-row"><p id="mine-reward-note">正在加载难度…</p></div>
    </div>
    <section id="mine-play" class="mine-play" aria-label="扫雷游戏" hidden>
      <div class="mine-play-heading"><button id="mine-back" type="button">← 返回选关</button><button id="mine-settings" type="button" aria-label="游戏设置，打开时暂停" title="游戏设置" aria-haspopup="dialog" aria-controls="game-settings">${SETTINGS_ICON}</button><button id="mine-restart" class="journey-primary" type="button">${RESTART_ICON}重新开始</button></div>
      <div class="mine-stats"><div><span>还差排查格数</span><strong id="mine-left">0</strong></div><div><span>可得星数</span><span id="mine-available-stars" class="mine-rating mine-stat-stars" aria-live="polite"></span></div><div><span id="mine-clock-label">本局用时</span><strong id="mine-clock">00:00</strong></div></div>
      <div id="mine-tutorial" class="mine-tutorial" hidden><span id="mine-tutorial-count" class="eyebrow"></span><h3 id="mine-tutorial-title"></h3><p id="mine-tutorial-text"></p><button id="mine-understood" type="button" class="journey-primary" hidden>明白了，试试标记 →</button></div>
      <div id="mine-viewport" class="mine-viewport" tabindex="0" role="region" aria-label="扫雷棋盘，可上下左右滚动"><div id="mine-board" class="mine-board" role="group" aria-label="扫雷棋盘"></div></div>
      <div class="mine-operation"><div class="journey-actions"><button id="mine-flag" type="button">${FLAG}标记</button><button id="mine-reveal" class="journey-primary" type="button">排雷</button></div></div>
    </section>
    <div class="mine-feedback"><p id="mine-message" role="status" aria-live="polite"></p><button id="mine-reload" type="button" hidden>重新加载</button><button id="mine-clock-retry" type="button" hidden>重试继续游戏</button></div>
    <dialog id="mine-enter-dialog" class="journey-rules" aria-labelledby="mine-enter-title" aria-describedby="mine-enter-description"><h2 id="mine-enter-title">是否闯关？</h2><p id="mine-enter-description"></p><div class="journey-actions"><button id="mine-enter-cancel" type="button" autofocus>暂不闯关</button><button id="mine-enter-confirm" class="journey-primary" type="button">确认闯关</button></div></dialog>
    <dialog id="mine-result" class="journey-rules mine-result" aria-labelledby="mine-result-title" aria-describedby="mine-result-description"><p class="eyebrow" id="mine-result-kicker">通关成功</p><h2 id="mine-result-title">安全格全部找到！</h2><div id="mine-result-stars" class="mine-rating mine-result-stars"></div><p id="mine-result-description" role="status"></p><button id="mine-retry-settlement" type="button" hidden>重试保存奖励</button><div class="journey-actions"><button id="mine-result-back" type="button">返回选关</button><button id="mine-next" class="journey-primary" type="button">下一关 →</button></div></dialog>
    <dialog id="mine-restart-dialog" class="journey-rules" aria-labelledby="mine-restart-title"><h2 id="mine-restart-title">重新开始本关？</h2><p>当前棋局将被放弃，其他关卡的进度会保留。</p><div class="journey-actions"><button id="mine-restart-cancel" type="button">继续当前局</button><button id="mine-restart-confirm" type="button" class="journey-primary">确认重开</button></div></dialog>`;
  const $=id=>host.querySelector(`#${id}`);
  const exitConfirmation=createExitConfirmation({host,scope,getSession:()=>model,
    onExit:back,
    onError:error=>{errorMessage=error.message;if(error.status===401)emit(Events.AUTH_EXPIRED);if(model)render(model.state);}});
  const collection=createStarCollection({onComplete:reward=>{
    if(dead||reward.userId!==identity)return;
    emit(Events.PROGRESSION_CONFIRMED,{userId:reward.userId,progression:reward.progression});
    emit(Events.RECORDS_UPDATED);
  }});

  /** 所有请求错误都保留可恢复状态，401交由共享登录模块处理。 */
  async function run(work){
    const expected=model;
    errorMessage='';
    try{await work();}catch(error){
      if(dead||model!==expected)return;
      errorMessage=error.message;
      if(error.status===401)emit(Events.AUTH_EXPIRED);
    }
    if(!dead&&model===expected)render(model.state);
  }
  /** 返回选关仅清理展示；已结算成绩及失败可重试的终盘由会话保持。 */
  function back(){
    selectionOnly=true;collection.cancel();stopAnimation();$('mine-result').close();emit(Events.SETTLEMENT_CLOSED);
    lastId=null;lastOutcome=null;renderedBoard='';$('mine-board').replaceChildren();render(model.state);focusSelected();
  }
  /** 根据浏览器可视高度及面板实际开销计算小棋盘尺寸，大盘仍以44px滚动。 */
  function fitBoard(){
    const attempt=model?.state.attempt;if(!attempt||$('mine-play').hidden)return;
    const viewport=$('mine-viewport'),play=$('mine-play');
    const rows=attempt.puzzle.rows,cols=attempt.puzzle.cols;
    const style=getComputedStyle(play);
    const overhead=host.querySelector('.mine-play-heading').offsetHeight+host.querySelector('.mine-stats').offsetHeight+
      ($('mine-tutorial').hidden?0:$('mine-tutorial').offsetHeight)+host.querySelector('.mine-operation').offsetHeight+
      parseFloat(style.paddingTop)+parseFloat(style.paddingBottom)+64;
    const height=(window.visualViewport?.height||window.innerHeight)-overhead;
    const cell=mineCellSize({rows,cols,width:viewport.clientWidth-12,height});
    $('mine-board').style.setProperty('--mine-cell',`${cell}px`);
    viewport.classList.toggle('mine-fit',rows<=10&&cols<=10);
  }
  /** 手机显式开局/重开后定位游戏顶部，避免选关面板收起后停在页面底部。 */
  async function runPlay(work){
    const expected=model;
    await run(work);
    if(!dead&&model===expected&&!errorMessage&&!selectionOnly&&model.state.attempt&&matchMedia('(max-width: 700px)').matches)
      $('mine-play').scrollIntoView({behavior:'instant',block:'start'});
  }
  /** 切离棋盘立即停止动画与尾音，恢复终盘时直接显示已知雷区。 */
  function stopAnimation(){sequence.stop();sound.stop();finished=true;animation=null;}
  const sequence=createExplosionSequence({
    /** 每一颗雷仅在时间线到达时显示。 */
    reveal(index){animation?.visible.add(index);paintMine(index);},
    /** 爆炸共享站点音量，重开/离开时可停止。 */
    explode(index,step){animation?.exploded.add(index);paintMine(index);void sound.play(step);},
    /** 动画尾声去掉瞬时闪烁。 */
    settle(index){animation?.settled.add(index);paintMine(index);},
    /** 全部雷结束后才展示失败提示。 */
    finish(){finished=true;render(model.state);},
  });
  /** 只修改指定地雷的视图，不把隐藏雷图写到DOM。 */
  function paintMine(index){
    const cell=$('mine-board').children[index];if(!cell)return;
    cell.replaceChildren();cell.classList.add('mine-visible');
    cell.classList.toggle('mine-exploded',animation?animation.exploded.has(index):true);
    cell.classList.toggle('mine-blasting',Boolean(animation?.exploded.has(index)&&!animation?.settled.has(index)));
    cell.classList.toggle('mine-spent',Boolean(animation?.settled.has(index)));
    cell.setAttribute('aria-label',cell.getAttribute('aria-label').split('，')[0]+'，地雷');
  }
  /** 显示当前候选难度和规格，筛选动作不创建服务端尝试。 */
  function renderSelection(state){
    const level=state.levels.find(v=>v.level_id===state.selected);
    if(!level)return;
    for(const button of $('mine-difficulties').children){button.setAttribute('aria-pressed',String(button.dataset.difficulty===level.difficulty));button.disabled=state.busy;}
    const specs=state.levels.filter(v=>v.difficulty===level.difficulty);
    $('mine-specs').replaceChildren();
    for(const item of specs){
      const button=document.createElement('button');button.type='button';button.className='mine-spec';button.dataset.level=item.level_id;
      button.setAttribute('aria-pressed',String(item.level_id===state.selected));button.disabled=state.busy||!state.enabled;
      button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-controls','mine-enter-dialog');
      const size=document.createElement('strong'),caption=document.createElement('span'),rating=document.createElement('span'),best=document.createElement('small');
      const footer=document.createElement('span'),stars=document.createElement('span');footer.className='mine-spec-footer';stars.className='mine-rating';
      size.textContent=item.difficulty==='tutorial'?'跟着提示，学会扫雷':`${item.cols} × ${item.rows}`;
      caption.textContent=`${item.mine_count} 颗地雷 · ${item.difficulty==='tutorial'?'四步引导，轻松上手':`${item.rows*item.cols-item.mine_count} 个安全格`}`;
      rating.className='mine-spec-reward';rating.textContent=item.difficulty==='tutorial'?'完成得 1 星 · 2 经验':`三星 ${mineTime(item.t3_ms)} 内 · ${item.star_xp.at(-1)} 经验`;
      const progress=state.progress.find(v=>v.level_id===item.level_id);
      best.textContent=progress?.best_stars?'已通关':progress?.current_attempt?'有进行中的棋局':'尚未通关';
      paintMineStars(stars,progress?.best_stars||0,`历史最高${progress?.best_stars||0}星${item.max_stars===1?'，入门教学最高1星':''}`,item.max_stars);
      footer.append(best,stars);button.append(size,caption,rating,footer);$('mine-specs').append(button);
    }
    $('mine-options-title').textContent=level.difficulty==='tutorial'?'你的第一堂扫雷课':'选择棋盘';
    $('mine-reward-note').textContent=level.difficulty==='tutorial'?'认识数字、学会标记，再独立完成一盘。完成后获得 1 星、2 经验。':`三星 ≤ ${mineTime(level.t3_ms)} · 二星 ≤ ${mineTime(level.t2_ms)} · 其余通关一星。经验 ${level.star_xp.join(' / ')}，提升星级补差额，首次三星当局新增经验翻倍，历史不补发。`;
    $('mine-enter-confirm').disabled=state.busy||!state.enabled;
  }
  /** 复用44px格子，已揭数字和终盘雷区来自服务端。 */
  function renderBoard(state){
    const attempt=state.attempt;if(!attempt)return;
    const {rows,cols}=attempt.puzzle,board=attempt.board;
    const key=JSON.stringify([attempt.attempt_id,board,state.flags,state.cell,state.busy,state.paused,finished]);
    if(key===renderedBoard)return;renderedBoard=key;
    const focus=$('mine-board').contains(document.activeElement)?document.activeElement?.dataset.index:null;
    $('mine-board').style.setProperty('--mine-cols',cols);
    const visible=new Map(board.revealed.map(v=>[v.index,v.value])),fragment=document.createDocumentFragment();
    for(let index=0;index<rows*cols;index++){
      const cell=document.createElement('button');cell.type='button';cell.className='mine-square';cell.dataset.index=index;
      const value=visible.get(index),flagged=state.flags.includes(index),selected=index===state.cell;
      let description='未揭开';
      if(value!==undefined&&value!==-1){cell.classList.add('mine-open');cell.dataset.number=value;cell.textContent=value>3?String(value):'';description=`周围 ${value} 颗雷`;}
      else if(flagged){cell.classList.add('mine-flagged');description='已标记';}
      cell.classList.toggle('mine-selected',selected);cell.setAttribute('aria-pressed',String(selected));
      const step=board.tutorial_step;
      const target=attempt.puzzle.tutorial&&((step===0&&index===0)||(step===1&&index===0)||(step===2&&index===6));
      cell.classList.toggle('mine-target',Boolean(target));
      cell.disabled=state.busy||state.paused||board.outcome!=='active';
      cell.setAttribute('aria-label',`第 ${Math.floor(index/cols)+1} 行第 ${index%cols+1} 列，${description}${target?'，教学目标':''}`);
      // 已揭格仍可聚焦读取数字；其余输入由会话判断，终盘统一禁用操作按钮。
      cell.setAttribute('aria-disabled',String(state.busy||state.paused||board.outcome!=='active'||value!==undefined));
      fragment.append(cell);
    }
    $('mine-board').replaceChildren(fragment);
    if(board.outcome==='lost')for(const index of board.mines||[]){if(!animation||animation.visible.has(index))paintMine(index);}
    if(focus!==null)$('mine-board').querySelector(`[data-index="${focus}"]`)?.focus({preventScroll:true});
  }
  /** 四步教学只高亮当前目标，误操作提示不会提前发奖。 */
  function renderTutorial(attempt){
    $('mine-tutorial').hidden=!attempt.puzzle.tutorial;
    if(!attempt.puzzle.tutorial)return;
    const step=attempt.board.tutorial_step;
    const content=[['揭开第一个格子','点选左上角高亮格，再按“排雷”。这里是安全的。'],
      ['数字告诉你什么？','数字 1 表示周围八个格子里有 1 颗雷。本教学中，地雷就在它右下方的第2行第2列。'],
      ['给地雷做个标记','点选高亮的第2行第2列，再按“标记”。标记可以提醒自己不要误点。'],
      ['把剩下的安全格找出来','继续观察数字，排开所有安全格。已标记格的右下方第4行第4列，以及第5行第5列也是地雷，请避开。']][Math.min(step,3)];
    $('mine-tutorial-count').textContent=`入门引导 · ${Math.min(step+1,4)} / 4`;
    $('mine-tutorial-title').textContent=content[0];$('mine-tutorial-text').textContent=content[1];
    $('mine-understood').hidden=step!==1;$('mine-understood').disabled=model.state.busy;
  }
  /** 通关只在弹窗展示，保存失败保留原局重试；同一终盘只自动打开一次。 */
  function renderResult(state){
    const won=state.attempt.board.outcome==='won'&&!selectionOnly&&state.attempt.level_id===state.selected;
    $('mine-retry-settlement').hidden=!won||Boolean(state.result);
    $('mine-retry-settlement').disabled=state.busy;
    $('mine-result-back').disabled=state.busy;
    if(!won){resultShown=null;$('mine-result').close();return;}
    const next=nextMineLevel(state.levels,state.attempt.level_id);
    $('mine-next').disabled=state.busy||!state.result;
    $('mine-next').textContent=next?`下一关：${next.name} →`:'已完成最后一关，返回选关';
    $('mine-result-kicker').textContent=state.result?'本关成绩已保存':'通关成功';
    $('mine-result-title').textContent=state.result?'安全格全部找到！':state.busy?'正在保存奖励…':'奖励尚未保存，请重试';
    $('mine-result-stars').hidden=!state.result;
    if(state.result)paintMineStars($('mine-result-stars'),state.result.stars,`本局获得${state.result.stars}星`,state.attempt.puzzle.tutorial?1:3);
    $('mine-result-description').textContent=state.result
      ?`用时 ${mineTime(state.result.duration_ms)} · 历史最高 ${state.result.best_stars} 星 · 本次新增 ${state.result.awarded_stars} 星、${state.result.awarded_xp} 经验。${state.result.first_three_star_bonus?`其中首次三星加成 ${state.result.first_three_star_bonus} 经验。`:""}`
      :'终盘和用时已保留。若网络失败，点击重试保存奖励。';
    if(resultShown!==state.attempt.attempt_id&&!document.querySelector('dialog[open]')){
      resultShown=state.attempt.attempt_id;$('mine-result').showModal();
    }
  }
  /** 轻量时钟与可得星数同源计算，暂停期间冻结，终盘以服务端结果为准。 */
  function renderTiming(){
    const state=model?.state,attempt=state?.attempt;if(!attempt)return;
    const level=state.levels.find(item=>item.level_id===attempt.level_id),elapsed=model.elapsed();
    $('mine-clock').textContent=mineTime(elapsed);
    $('mine-clock-label').textContent=state.paused&&attempt.board.outcome==='active'?'本局用时 · 已暂停':'本局用时';
    const count=availableMineStars(level,elapsed,attempt.board.outcome,state.result?.stars);
    paintMineStars($('mine-available-stars'),count,attempt.puzzle.tutorial?'入门教学固定可得1星':`本局可得${count}星`,level?.max_stars);
  }
  /** 只有服务端状态变化才重建棋盘；计时显示由独立低频定时器更新。 */
  function render(state){
    if(dead)return;
    renderSelection(state);
    const playing=Boolean(state.attempt)&&!selectionOnly&&state.attempt.level_id===state.selected;
    $('mine-selector').hidden=playing;$('mine-play').hidden=!playing;
    page?.classList.toggle('mine-playing',playing);
    const pageHeading=document.getElementById('levels-title')?.closest('.section-heading');
    if(pageHeading)pageHeading.hidden=playing;
    if(!state.attempt){$('mine-board').replaceChildren();renderedBoard='';resultShown=null;$('mine-result').close();}
    if(state.attempt){
      const attempt=state.attempt,board=attempt.board;
      if(attempt.attempt_id!==lastId){stopAnimation();lastId=attempt.attempt_id;lastOutcome=null;renderedBoard='';}
      const animate=playing&&board.outcome==='lost'&&lastOutcome==='active'&&!matchMedia('(prefers-reduced-motion: reduce)').matches;
      if(animate){animation={visible:new Set(),exploded:new Set(),settled:new Set()};finished=false;}
      lastOutcome=board.outcome;
      $('mine-left').textContent=remainingSafeCells(attempt);
      renderTiming();
      const active=board.outcome==='active'&&!state.busy&&!state.paused&&finished;
      const chosen=state.cell!==null&&!board.revealed.some(v=>v.index===state.cell);
      $('mine-flag').disabled=!active||!chosen;$('mine-reveal').disabled=!active||!chosen||state.flags.includes(state.cell);
      $('mine-flag').innerHTML=FLAG+(state.flags.includes(state.cell)?'取消标记':'标记');
      // 重开只在真实请求处理中短暂禁用，爆炸时间线不会阻挡踩雷后的快速重开。
      $('mine-restart').disabled=state.busy;
      $('mine-back').disabled=state.busy;
      renderBoard(state);renderTutorial(attempt);renderResult(state);fitBoard();
      if(animate){
        const game={status:'lost',explodedAt:board.revealed.find(v=>v.value===-1)?.index,level:{cols:attempt.puzzle.cols},cells:Array.from({length:attempt.puzzle.rows*attempt.puzzle.cols},(_,index)=>({mine:board.mines.includes(index)}))};
        sequence.start(explosionOrder(game));
      }
    }
    $('mine-message').textContent=errorMessage||state.message||(!state.enabled&&state.levels.length?'扫雷暂未开放，请稍后重试。':'');
    $('mine-reload').hidden=!errorMessage||Boolean(state.attempt);$('mine-reload').disabled=state.busy;
    $('mine-clock-retry').hidden=!state.paused||state.clockBusy||selectionOnly||document.hidden||Boolean(document.querySelector('dialog[open]'));
    $('mine-clock-retry').disabled=state.busy;
  }
  /** 取消或返回选关时聚焦原卡片，保留键盘操作位置。 */
  function focusSelected(){if(model)$('mine-specs').querySelector(`[data-level="${model.state.selected}"]`)?.focus({preventScroll:true});}
  /** 卡片点击只展示确认与规则门槛，确认前不创建尝试或扣体力。 */
  function askToEnter(id){
    const state=model.state,level=state.levels.find(item=>item.level_id===id);
    if(!level||state.busy||!state.enabled)return;
    model.select(id);pendingLevel=id;
    const continuing=state.progress.some(item=>item.level_id===id&&item.current_attempt)||state.attempt?.level_id===id&&state.attempt.status==='active';
    $('mine-enter-title').textContent=`是否挑战${level.name}？`;
    $('mine-enter-description').textContent=`${level.cols} × ${level.rows} · ${level.mine_count}颗地雷。${continuing?'确认后继续上次的棋局，不重复消耗体力。':energyHint(level.difficulty==='tutorial')}${level.max_stars===1?'完成教学获得1星、2经验。':`三星${mineTime(level.t3_ms)}内，二星${mineTime(level.t2_ms)}内，其余通关1星；经验${level.star_xp.join(' / ')}。`}`;
    $('mine-enter-dialog').showModal();
  }
  /** 登录完成后仍进入用户确认的关卡，只在此处开始或恢复计时。 */
  async function openSelected(id){
    await identityReady;if(dead)return;model.select(id);selectionOnly=false;
    await model.setPaused('selection',false,{sync:false});await runPlay(()=>model.open());
  }
  for(const [key,name,caption] of DIFFICULTIES){
    const button=document.createElement('button');button.type='button';button.dataset.difficulty=key;
    const label=document.createElement('strong'),note=document.createElement('span');label.textContent=name;note.textContent=caption;
    button.append(label,note);$('mine-difficulties').append(button);
  }
  scope.listen($('mine-difficulties'),'click',event=>{
    const button=event.target.closest('[data-difficulty]');if(!button)return;
    const level=model.state.levels.find(v=>v.difficulty===button.dataset.difficulty);if(level)model.select(level.level_id);
  });
  scope.listen($('mine-specs'),'click',event=>{const button=event.target.closest('[data-level]');if(button)askToEnter(button.dataset.level);});
  scope.listen($('mine-enter-cancel'),'click',()=>$('mine-enter-dialog').close());
  scope.listen($('mine-enter-dialog'),'close',()=>{pendingLevel=null;if(!$('mine-selector').hidden)focusSelected();});
  scope.listen($('mine-enter-confirm'),'click',()=>{
    const selected=pendingLevel;if(!selected||model.state.busy)return;
    $('mine-enter-dialog').close();void auth.requireLogin(()=>openSelected(selected));
  });
  // 棋盘顶部与账号栏共用同一个设置窗口，滚动到游戏时仍有可触达的暂停入口。
  scope.listen($('mine-settings'),'click',()=>{$('mine-settings').focus({preventScroll:true});document.querySelector('.auth-settings')?.click();});
  scope.listen(document,Events.GAME_SETTINGS_CHANGED,event=>{if(model)void run(()=>model.setPaused('settings',event.detail.open));});
  scope.listen($('mine-back'),'click',()=>void exitConfirmation.ask());
  scope.listen($('mine-board'),'click',event=>{const cell=event.target.closest('[data-index]');if(cell)model.choose(Number(cell.dataset.index));});
  scope.listen($('mine-board'),'keydown',event=>{
    const cell=event.target.closest('[data-index]');if(!cell||!model.state.attempt)return;
    const cols=model.state.attempt.puzzle.cols,index=Number(cell.dataset.index),col=index%cols;
    const delta={ArrowLeft:col>0?-1:0,ArrowRight:col<cols-1?1:0,ArrowUp:-cols,ArrowDown:cols}[event.key];
    if(delta===undefined)return;
    const next=$('mine-board').children[index+delta];if(next){event.preventDefault();next.focus();model.choose(index+delta);}
  });
  scope.listen($('mine-flag'),'click',()=>void run(()=>model.mark()));
  scope.listen($('mine-reveal'),'click',()=>{sound.unlock();void run(()=>model.reveal());});
  scope.listen($('mine-understood'),'click',()=>void run(()=>model.acknowledge()));
  scope.listen($('mine-retry-settlement'),'click',()=>void run(()=>model.complete()));
  scope.listen($('mine-result-back'),'click',()=>{if(!model.state.busy)back();});
  scope.listen($('mine-result'),'close',()=>{
    if($('mine-result').open)return;
    collection.cancel();emit(Events.SETTLEMENT_CLOSED);
    if(!$('mine-play').hidden)$('mine-back').focus({preventScroll:true});
  });
  // Esc等价于返回选关；保存尚在进行时留在弹窗，避免把未确认奖励当作已完成。
  scope.listen($('mine-result'),'cancel',event=>{event.preventDefault();if(model&&!model.state.busy)back();});
  scope.listen($('mine-next'),'click',()=>{
    if(model.state.busy||!model.state.result)return;
    const next=nextMineLevel(model.state.levels,model.state.attempt.level_id);
    $('mine-result').close();collection.cancel();emit(Events.SETTLEMENT_CLOSED);
    if(next)void openSelected(next.level_id);else back();
  });
  /** 先停止旧爆炸再发原子重开；体力不足时仍保留旧局和可重试状态。 */
  function restart(){collection.cancel();stopAnimation();emit(Events.SETTLEMENT_CLOSED);void runPlay(()=>model.restart());}
  scope.listen($('mine-restart'),'click',()=>{
    if(model.state.busy)return;
    if(model.state.attempt?.board.outcome==='lost'){restart();return;}
    collection.cancel();
    $('mine-restart-dialog').querySelector('p').textContent='当前棋局将被放弃，其他关卡进度保留。'+energyHint(model.state.attempt?.puzzle.tutorial,true);
    $('mine-restart-dialog').showModal();
  });
  scope.listen($('mine-restart-cancel'),'click',()=>$('mine-restart-dialog').close());
  scope.listen($('mine-restart-confirm'),'click',()=>{$('mine-restart-dialog').close();restart();});
  scope.listen($('mine-reload'),'click',()=>void run(()=>model.load()));
  scope.listen($('mine-clock-retry'),'click',()=>void run(()=>model.setPaused('retry',false)));
  scope.add(settings.subscribe(value=>{
    sound.setMuted(!value.effectsEnabled);sound.setVolume(value.effectsVolume);
  }));
  scope.listen(window,'resize',fitBoard);
  if(window.visualViewport)scope.listen(window.visualViewport,'resize',fitBoard);
  // 观察宽度变化即可；延后到下一帧，避免修改格子高度触发ResizeObserver循环。
  let fitFrame=null,lastWidth=0;
  const observer=new ResizeObserver(entries=>{
    const width=entries[0].contentRect.width;if(width===lastWidth)return;lastWidth=width;
    if(fitFrame!==null)cancelAnimationFrame(fitFrame);
    fitFrame=requestAnimationFrame(()=>{fitFrame=null;fitBoard();});
  });
  observer.observe(host);scope.add(()=>{observer.disconnect();if(fitFrame!==null)cancelAnimationFrame(fitFrame);});
  const timer=setInterval(renderTiming,250);
  scope.add(()=>clearInterval(timer));
  scope.listen(document,'visibilitychange',()=>{
    if(document.hidden)collection.cancel();
    if(model)void run(()=>model.setPaused('hidden',document.hidden));
  });
  scope.listen(window,'pagehide',()=>{if(model)void model.setPaused('pagehide',true,{immediate:true}).catch(()=>{});});
  scope.listen(matchMedia('(prefers-reduced-motion: reduce)'),'change',event=>{if(event.matches)collection.cancel();});
  return {
    /** 换号先销毁旧请求和棋盘，再加载新账号自己的目录进度。 */
    async setUser(uid){
      if(identity===uid&&model)return;collection.cancel(false);identity=uid;model?.destroy();stopAnimation();selectionOnly=false;lastId=null;lastOutcome=null;errorMessage='';
      exitConfirmation.reset();
      pendingLevel=null;resultShown=null;$('mine-enter-dialog').close();$('mine-result').close();$('mine-restart-dialog').close();
      let storage;try{storage=window.localStorage;}catch{/* 存储禁用仍可依靠服务端续玩。 */}
      const next=createMineSession({uid,storage,onChange:state=>render(state),onReward:result=>{
        render(next.state);
        void collection.play({key:next.state.attempt.attempt_id,userId:uid,progression:result.progression,awardedStars:result.awarded_stars,
          source:$('mine-result-stars'),target:document.querySelector('.player-stars')});
        emit(Events.SETTLEMENT_OPENED,{runId:next.state.attempt.attempt_id});onReward();
      }});
      model=next;
      if(document.querySelector('#game-settings')?.open)await next.setPaused('settings',true,{sync:false});
      if(document.hidden)await next.setPaused('hidden',true,{sync:false});
      identityReady=run(()=>next.load());await identityReady;
    },
    /** 主动刷新只重读当前账号资料；界面重载时也会GET核验原局。 */
    async refresh(){if(model&&!model.state.busy)await run(()=>model.load());},
    /** 清理全部事件、音效和待返回请求。 */
    destroy(){dead=true;collection.cancel(false);model?.destroy();stopAnimation();$('mine-result').close();page?.classList.remove('mine-playing');scope.dispose();emit(Events.SETTLEMENT_CLOSED);},
  };
}
