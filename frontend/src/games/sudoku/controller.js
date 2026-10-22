/** 数独页面：五档选题、分步教学、参考图棋盘及正式成长反馈。 */
import { createSudokuSession } from './session.js';
import { sudokuConflicts } from './rules.js';
import { createScope } from '../../shared/lifecycle.js';
import { energyHint } from '../../features/progression/attempt-energy.js';
import { Events,emit } from '../../shared/events.js';
// 轻量复用已有星级和汇聚视图；不依赖扫雷会话或控制器。
import { availableMineStars as availableStars,paintMineStars as paintStars,createStarCollection } from '../mine/stars.js';

const DIFFICULTIES=[['tutorial','入门','认识九宫'],['easy','简单','寻找唯一'],['medium','中等','隐藏线索'],['hard','困难','候选排除'],['hell','地狱','推理成链']];
const DESCRIPTIONS={tutorial:'4 × 4 教学 · 从行、列与宫开始',easy:'唯一候选 · 从确定的数字开始',medium:'隐藏单数 · 找到数字唯一的位置',hard:'数对与区块 · 在候选之间做排除',hell:'鱼形、翼形与强链 · 让线索彼此连接'};
const TUTORIAL=[['行里少了谁？','第一行已有 1、3、4。选择第1行第2列，填入缺少的数字 2。',1],
  ['学会修改','选择刚刚填写的格子，点击“清除选中格”。填错也可以随时修改。',1],
  ['记录一个候选数','开启“笔记”，选择第1行第2列，再点击 2，记录你的推理。',1],
  ['看看这一列','关闭笔记。第3列已有 3、4、2，选择第2行第3列，填入 1。',6],
  ['完成最后一个宫','左上方2×2宫还缺少 2。选择第1行第2列，填入 2，完成这一盘。',1]];

/** 按分钟和秒显示，评分仍以服务器毫秒为准。 */
export function sudokuTime(ms){const seconds=Math.floor(Math.max(0,ms)/1000);return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;}

/** auth由页面共享；每次换号销毁旧会话、弹窗和奖励动画。 */
export function createSudokuJourney({host,auth,onReward=()=>{}}){
  const scope=createScope();let model,identity,ready=Promise.resolve(),dead=false,selectionOnly=false,errorMessage='',boardKey='',pendingFocus=null,pendingLevel=null;
  host.innerHTML=`
    <div id="sudoku-selector" class="sudoku-selector">
      <div class="sudoku-intro"><div><p class="eyebrow">SUDOKU / 数字之间，自有秩序</p><h2>一格一格，解开谜题。</h2><p>从第一个确定的数字，到属于你的完整答案。</p></div><div class="sudoku-emblem" aria-hidden="true"><span>1</span><span></span><span>3</span><span></span><span>5</span><span></span><span>7</span><span></span><span>9</span></div></div>
      <div id="sudoku-difficulties" class="sudoku-difficulties" role="group" aria-label="数独难度"></div>
      <div class="sudoku-options-heading"><h3 id="sudoku-options-title">选择题目</h3><span>全部难度自由选择</span></div>
      <div id="sudoku-specs" class="sudoku-specs" role="group" aria-labelledby="sudoku-options-title"></div>
      <div class="sudoku-start-row"><p id="sudoku-reward-note">正在加载题目…</p></div>
    </div>
    <section id="sudoku-play" class="sudoku-play" aria-label="数独游戏" hidden>
      <div class="sudoku-topbar"><button id="sudoku-back" type="button">返回选关</button><span>无职游戏</span><button id="sudoku-restart" type="button">重新开始</button></div>
      <div class="sudoku-heading"><p class="eyebrow" id="sudoku-kicker">SUDOKU</p><h2>数独</h2></div>
      <div class="sudoku-toolbar"><div class="sudoku-difficulty"><span>难度</span><strong id="sudoku-difficulty-label"></strong></div><div class="sudoku-available"><span>可得星数</span><span id="sudoku-available-stars" class="mine-rating" aria-live="polite"></span></div><div class="sudoku-tools-right"><p><span id="sudoku-clock-label">本局用时</span><strong id="sudoku-clock">00:00</strong></p><button id="sudoku-pause-toggle" type="button" aria-pressed="false" aria-label="暂停游戏" title="暂停游戏"><svg class="sudoku-pause-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14"/></svg><svg class="sudoku-resume-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m8 4 12 8-12 8Z"/></svg></button></div></div>
      <div id="sudoku-tutorial" class="sudoku-tutorial" hidden><p id="sudoku-tutorial-count" class="eyebrow"></p><h3 id="sudoku-tutorial-title"></h3><p id="sudoku-tutorial-text"></p></div>
      <div class="sudoku-board-wrap"><div id="sudoku-board" class="sudoku-board" role="group" aria-label="数独棋盘"></div><div id="sudoku-pause" class="sudoku-pause" hidden><strong>棋局已暂停</strong><p>准备好后，继续这一盘。</p><button id="sudoku-clock-retry" type="button" class="journey-primary">继续游戏</button></div></div>
      <div class="sudoku-input"><div id="sudoku-keypad" class="sudoku-keypad" role="group" aria-label="填写数字"></div><div class="sudoku-actions"><button id="sudoku-undo" type="button" disabled>撤回上一步</button><button id="sudoku-clear" type="button">清除选中格</button><button id="sudoku-notes" type="button" aria-pressed="false">笔记：关</button></div><p class="sudoku-keyboard-help">方向键选格 · 数字键填写 · Delete 清除</p></div>
      <div id="sudoku-result" class="sudoku-result" role="status" hidden><p class="eyebrow">每一步推理，都算数。</p><h3 id="sudoku-result-title"></h3><div id="sudoku-result-stars" class="mine-rating"></div><p id="sudoku-result-description"></p><button id="sudoku-retry-settlement" type="button" class="journey-primary" hidden>重试保存奖励</button></div>
    </section>
    <div class="sudoku-feedback"><p id="sudoku-message" role="status" aria-live="polite"></p><button id="sudoku-reload" type="button" hidden>重新加载</button></div>
    <dialog id="sudoku-enter-dialog" class="journey-rules" aria-labelledby="sudoku-enter-title" aria-describedby="sudoku-enter-description"><h2 id="sudoku-enter-title">是否闯关？</h2><p id="sudoku-enter-description"></p><div class="journey-actions"><button id="sudoku-enter-cancel" type="button" autofocus>暂不闯关</button><button id="sudoku-enter-confirm" class="journey-primary" type="button">确认闯关</button></div></dialog>
    <dialog id="sudoku-restart-dialog" class="journey-rules" aria-labelledby="sudoku-restart-title"><h2 id="sudoku-restart-title">重新开始本题？</h2><p>本题的填写和笔记将清空，其他题目的进度会保留。</p><div class="journey-actions"><button id="sudoku-restart-cancel" type="button">继续当前局</button><button id="sudoku-restart-confirm" type="button" class="journey-primary">确认重开</button></div></dialog>`;
  const $=id=>host.querySelector('#'+id);
  const collection=createStarCollection({onComplete:reward=>{
    if(dead||reward.userId!==identity)return;
    emit(Events.PROGRESSION_CONFIRMED,{userId:identity,progression:reward.progression});emit(Events.RECORDS_UPDATED);
  }});

  /** 捕捉当前会话错误，迟到的旧账号响应不影响新页面。 */
  async function run(work){
    const expected=model;errorMessage='';
    try{await work();}catch(error){if(dead||model!==expected)return;errorMessage=error.message;if(error.status===401)emit(Events.AUTH_EXPIRED);}
    if(!dead&&model===expected)render(model.state);
  }
  /** 窄屏开始后定位顶部，不让收起选关导致用户停留在游戏下方。 */
  async function play(work){
    const expected=model;await run(work);
    if(!dead&&model===expected&&!errorMessage&&!selectionOnly&&model.state.attempt&&matchMedia('(max-width:700px)').matches)$('sudoku-play').scrollIntoView({behavior:'instant',block:'start'});
  }
  /** 卡片显示历史最高星和关卡自有参数，筛选不创建正式尝试。 */
  function renderSelection(state){
    const level=state.levels.find(v=>v.level_id===state.selected);
    $('sudoku-enter-confirm').disabled=state.busy||!state.enabled||!level;
    if(!level)return;
    for(const button of $('sudoku-difficulties').children){button.setAttribute('aria-pressed',String(button.dataset.difficulty===level.difficulty));button.disabled=state.busy;}
    $('sudoku-specs').replaceChildren();
    for(const item of state.levels.filter(v=>v.difficulty===level.difficulty)){
      const button=document.createElement('button');button.type='button';button.className='sudoku-spec';button.dataset.level=item.level_id;button.disabled=state.busy||!state.enabled;
      button.setAttribute('aria-pressed',String(item.level_id===state.selected));
      button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-controls','sudoku-enter-dialog');
      const number=document.createElement('span'),title=document.createElement('strong'),description=document.createElement('span'),rating=document.createElement('span'),footer=document.createElement('span'),best=document.createElement('small'),stars=document.createElement('span');
      number.className='sudoku-spec-number';number.textContent=item.difficulty==='tutorial'?'FIRST STEPS':`PUZZLE ${String(item.order-1-(DIFFICULTIES.findIndex(v=>v[0]===item.difficulty)-1)*3).padStart(2,'0')}`;
      title.textContent=item.difficulty==='tutorial'?'你的第一堂数独课':item.name;
      description.textContent=`${item.cols} × ${item.rows} · ${item.clue_count} 个已给数字`;rating.textContent=item.difficulty==='tutorial'?'五步引导 · 完成获得1星':`三星 ${sudokuTime(item.t3_ms)} 内 · ${item.star_xp.at(-1)} 经验`;
      description.className='sudoku-spec-description';rating.className='sudoku-spec-reward';footer.className='sudoku-spec-footer';stars.className='mine-rating';
      const progress=state.progress.find(v=>v.level_id===item.level_id);
      best.textContent=progress?.best_stars?'已通关':progress?.current_attempt?'有进行中的棋局':'尚未通关';
      paintStars(stars,progress?.best_stars||0,`历史最高${progress?.best_stars||0}星`,item.max_stars);
      footer.append(best,stars);button.append(number,title,description,rating,footer);$('sudoku-specs').append(button);
    }
    $('sudoku-options-title').textContent=DESCRIPTIONS[level.difficulty];
    $('sudoku-reward-note').textContent=(level.max_stars===1?'认识行、列与宫，学会填数和笔记。完成获得1星、2经验。':`三星 ≤ ${sudokuTime(level.t3_ms)} · 二星 ≤ ${sudokuTime(level.t2_ms)} · 其余通关一星。经验 ${level.star_xp.join(' / ')}，提升星级补差额。`)+energyHint(level.difficulty==='tutorial');
  }
  /** 只在布局或操作状态变化时绘制棋盘，保留键盘焦点，时钟不重建格子。 */
  function renderBoard(state){
    const grid=state.grid,size=grid.size,box=grid.box,selected=grid.selected;
    const key=JSON.stringify([state.attempt.attempt_id,grid,state.busy,state.paused,state.pending]);if(key===boardKey)return;boardKey=key;
    const focused=$('sudoku-board').contains(document.activeElement)?document.activeElement.dataset.index:null;
    if(focused!==null)pendingFocus=focused;
    const conflicts=sudokuConflicts(grid),fragment=document.createDocumentFragment();
    $('sudoku-board').style.setProperty('--sudoku-size',size);$('sudoku-board').dataset.size=size;
    grid.values.forEach((value,index)=>{
      const row=Math.floor(index/size),col=index%size,cell=document.createElement('button');cell.type='button';cell.className='sudoku-cell';cell.dataset.index=index;
      cell.tabIndex=index===(selected??0)?0:-1;
      cell.disabled=state.busy||state.paused||state.pending||state.attempt.status!=='active';
      cell.classList.toggle('given',Boolean(grid.givens[index]));
      if(selected!==null){
        const sr=Math.floor(selected/size),sc=selected%size;
        cell.classList.toggle('peer',row===sr||col===sc||(Math.floor(row/box)===Math.floor(sr/box)&&Math.floor(col/box)===Math.floor(sc/box)));
        cell.classList.toggle('same-value',value!==0&&value===grid.values[selected]);
      }
      cell.classList.toggle('selected',index===selected);cell.classList.toggle('conflict',conflicts.has(index));
      cell.classList.toggle('box-right',(col+1)%box===0&&col<size-1);cell.classList.toggle('box-bottom',(row+1)%box===0&&row<size-1);
      cell.classList.toggle('tutorial-target',Boolean(state.attempt.puzzle.tutorial&&TUTORIAL[state.attempt.board.tutorial_step]?.[2]===index));
      let notes=[];
      if(value)cell.textContent=value;
      else if(grid.notes[index]){
        const holder=document.createElement('span');holder.className='sudoku-notes';holder.style.setProperty('--note-cols',box);holder.setAttribute('aria-hidden','true');
        for(let digit=1;digit<=size;digit++){const slot=document.createElement('span');const exists=Boolean(grid.notes[index]&(1<<(digit-1)));slot.textContent=exists?digit:'';if(exists)notes.push(digit);holder.append(slot);}
        cell.append(holder);
      }
      cell.setAttribute('aria-label',`第 ${row+1} 行第 ${col+1} 列，${value|| (notes.length?`候选数 ${notes.join('、')}`:'空格')}${grid.givens[index]?'，题目数字':''}${conflicts.has(index)?'，存在重复':''}`);
      cell.setAttribute('aria-pressed',String(index===selected));fragment.append(cell);
    });
    $('sudoku-board').replaceChildren(fragment);
    // 忙碌时原生disabled会移除焦点；完成重绘后恢复，除非用户已主动聚焦其他控件。
    if(pendingFocus!==null&&!state.busy&&!state.paused&&!state.pending){
      if(document.activeElement===document.body||$('sudoku-board').contains(document.activeElement))$('sudoku-board').querySelector(`[data-index="${pendingFocus}"]`)?.focus({preventScroll:true});
      pendingFocus=null;
    }
  }
  /** 用时及星级以服务器活动时长为锚，每250ms只更新文本。 */
  function timing(){
    const state=model?.state;if(!state?.attempt)return;
    const level=state.levels.find(v=>v.level_id===state.attempt.level_id);$('sudoku-clock').textContent=sudokuTime(model.elapsed());
    $('sudoku-clock-label').textContent=state.paused&&!state.pending&&!state.result?'已暂停':'本局用时';
    paintStars($('sudoku-available-stars'),availableStars(level,model.elapsed(),'active',state.result?.stars),'本局可得星数',level?.max_stars);
  }
  /** 统一更新模式、教学及结果；错误和服务端反馈保持可重试。 */
  function render(state){
    if(dead)return;renderSelection(state);
    const playing=Boolean(state.attempt)&&!selectionOnly&&state.attempt.level_id===state.selected;
    $('sudoku-selector').hidden=playing;$('sudoku-play').hidden=!playing;
    const heading=document.getElementById('levels-title')?.closest('.section-heading');if(heading)heading.hidden=true;
    if(state.attempt&&state.grid){
      const grid=state.grid,selected=grid.selected,level=state.levels.find(v=>v.level_id===state.attempt.level_id),active=!state.busy&&!state.paused&&!state.pending&&state.attempt.status==='active';
      $('sudoku-kicker').textContent=`${level?.name||'数独'} / SUDOKU`;
      $('sudoku-difficulty-label').textContent=DIFFICULTIES.find(([key])=>key===level?.difficulty)?.[1]||'数独';
      $('sudoku-undo').hidden=Boolean(state.attempt.puzzle.tutorial);$('sudoku-undo').disabled=!active||!state.history.length;
      $('sudoku-undo').parentElement.classList.toggle('has-undo',!state.attempt.puzzle.tutorial);
      $('sudoku-notes').textContent=grid.notesMode?'笔记：开':'笔记：关';$('sudoku-notes').setAttribute('aria-pressed',String(grid.notesMode));$('sudoku-notes').disabled=!active;
      const editable=active&&selected!==null&&!grid.givens[selected];
      if($('sudoku-keypad').children.length!==grid.size){$('sudoku-keypad').replaceChildren();for(let digit=1;digit<=grid.size;digit++){const button=document.createElement('button');button.type='button';button.dataset.digit=digit;button.textContent=digit;$('sudoku-keypad').append(button);}}
      for(const button of $('sudoku-keypad').children){button.disabled=!editable||(grid.notesMode&&Boolean(grid.values[selected]));if(grid.notesMode)button.setAttribute('aria-pressed',String(Boolean(grid.notes[selected]&(1<<(Number(button.dataset.digit)-1)))));else button.removeAttribute('aria-pressed');}
      $('sudoku-keypad').setAttribute('aria-label',grid.notesMode?'记录候选数':'填写数字');$('sudoku-keypad').dataset.size=grid.size;
      $('sudoku-clear').disabled=!editable;$('sudoku-clear').textContent=grid.notesMode&&selected!==null&&!grid.values[selected]?'清除本格笔记':'清除选中格';
      $('sudoku-restart').disabled=state.busy||state.clockBusy;
      $('sudoku-pause-toggle').disabled=state.busy||state.clockBusy||state.pending||state.attempt.status!=='active';
      // 图标表达暂停/继续；无障碍名称与悬停说明同步当前动作。
      $('sudoku-pause-toggle').classList.toggle('is-paused',state.paused);$('sudoku-pause-toggle').setAttribute('aria-pressed',String(state.paused));
      $('sudoku-pause-toggle').setAttribute('aria-label',state.paused?'继续游戏':'暂停游戏');$('sudoku-pause-toggle').title=state.paused?'继续游戏':'暂停游戏';
      $('sudoku-pause').hidden=!state.paused||state.pending||Boolean(state.result);$('sudoku-clock-retry').disabled=state.busy||state.clockBusy;
      $('sudoku-tutorial').hidden=!state.attempt.puzzle.tutorial||Boolean(state.result);$('sudoku-tutorial').dataset.step=state.attempt.board.tutorial_step??'';
      if(state.attempt.puzzle.tutorial){const step=state.attempt.board.tutorial_step,content=TUTORIAL[Math.min(step,4)];$('sudoku-tutorial-count').textContent=`入门引导 · ${Math.min(step+1,5)} / 5`;$('sudoku-tutorial-title').textContent=content[0];$('sudoku-tutorial-text').textContent=content[1];}
      $('sudoku-result').hidden=!state.pending&&!state.result;$('sudoku-result-title').textContent=state.result?'本关成绩已保存':'数独完成，正在保存奖励…';
      $('sudoku-result-description').textContent=state.result?`用时 ${sudokuTime(state.result.duration_ms)} · 历史最高 ${state.result.best_stars} 星 · 本次新增 ${state.result.awarded_stars} 星、${state.result.awarded_xp} 经验。`:'终盘已保留，连接恢复后可重试保存。成绩以成功提交时的用时为准。';
      $('sudoku-result-stars').hidden=!state.result;if(state.result)paintStars($('sudoku-result-stars'),state.result.stars,`本局${state.result.stars}星`,level?.max_stars);
      $('sudoku-retry-settlement').hidden=!state.pending||Boolean(state.result);$('sudoku-retry-settlement').disabled=state.busy;
      renderBoard(state);timing();
    }
    $('sudoku-message').textContent=errorMessage||state.message||(!state.enabled&&state.levels.length?'数独暂未开放，请稍后重试。':'');
    $('sudoku-reload').hidden=!errorMessage||Boolean(state.attempt);$('sudoku-reload').disabled=state.busy;
  }
  /** 弹窗取消或返回时回到所选卡片，保留键盘焦点。 */
  function focusSelected(){if(model)$('sudoku-specs').querySelector(`[data-level="${model.state.selected}"]`)?.focus({preventScroll:true});}
  /** 关卡卡片只展示确认，未确认时不创建尝试或扣除体力。 */
  function askToEnter(id){
    const state=model.state,level=state.levels.find(item=>item.level_id===id);
    if(!level||state.busy||!state.enabled)return;
    model.select(id);pendingLevel=id;
    const continuing=state.progress.some(item=>item.level_id===id&&item.current_attempt)||state.attempt?.level_id===id&&state.attempt.status==='active';
    $('sudoku-enter-title').textContent=`是否挑战${level.name}？`;
    $('sudoku-enter-description').textContent=`${level.cols} × ${level.rows} · ${level.clue_count}个已给数字。${continuing?'确认后继续上次的棋局，不重复消耗体力。':energyHint(level.difficulty==='tutorial')}${level.max_stars===1?'完成教学获得1星、2经验。':`三星${sudokuTime(level.t3_ms)}内，二星${sudokuTime(level.t2_ms)}内，其余通关1星；经验${level.star_xp.join(' / ')}。`}`;
    $('sudoku-enter-dialog').showModal();
  }
  /** 登录异步完成后仍使用确认时的关卡，避免回退到默认题目。 */
  async function openSelected(id){
    await ready;if(dead)return;model.select(id);selectionOnly=false;
    await model.setPaused('selection',false,{sync:false});await play(()=>model.open());
  }
  for(const [key,label,caption] of DIFFICULTIES){const button=document.createElement('button'),name=document.createElement('strong'),note=document.createElement('span');button.type='button';button.dataset.difficulty=key;name.textContent=label;note.textContent=caption;button.append(name,note);$('sudoku-difficulties').append(button);}
  scope.listen($('sudoku-difficulties'),'click',event=>{const button=event.target.closest('[data-difficulty]');if(!button)return;const level=model.state.levels.find(v=>v.difficulty===button.dataset.difficulty);if(level)model.select(level.level_id);});
  scope.listen($('sudoku-specs'),'click',event=>{const button=event.target.closest('[data-level]');if(button)askToEnter(button.dataset.level);});
  scope.listen($('sudoku-enter-cancel'),'click',()=>$('sudoku-enter-dialog').close());
  scope.listen($('sudoku-enter-dialog'),'close',()=>{pendingLevel=null;if(!$('sudoku-selector').hidden)focusSelected();});
  scope.listen($('sudoku-enter-confirm'),'click',()=>{
    const selected=pendingLevel;if(!selected||model.state.busy)return;
    $('sudoku-enter-dialog').close();void auth.requireLogin(()=>openSelected(selected));
  });
  scope.listen($('sudoku-pause-toggle'),'click',()=>void run(()=>model.setPaused('manual',!model.state.paused)));
  scope.listen($('sudoku-back'),'click',()=>{selectionOnly=true;collection.cancel();emit(Events.SETTLEMENT_CLOSED);void run(()=>model.setPaused('selection',true));render(model.state);focusSelected();});
  scope.listen($('sudoku-board'),'click',event=>{const cell=event.target.closest('[data-index]');if(cell)model.choose(Number(cell.dataset.index));});
  scope.listen($('sudoku-keypad'),'click',event=>{const button=event.target.closest('[data-digit]');if(button)void run(()=>model.input(Number(button.dataset.digit)));});
  scope.listen($('sudoku-notes'),'click',()=>model.toggleNotes());scope.listen($('sudoku-clear'),'click',()=>void run(()=>model.input(0)));
  scope.listen($('sudoku-undo'),'click',()=>model.undo());
  scope.listen(document,'keydown',event=>{
    if(!model?.state.grid||selectionOnly||$('sudoku-play').hidden||document.querySelector('dialog[open]')||event.ctrlKey||event.altKey||event.metaKey||event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
    const grid=model.state.grid,size=grid.size,index=grid.selected??0,col=index%size;
    if(event.key.startsWith('Arrow')){const change={ArrowLeft:col>0?-1:0,ArrowRight:col<size-1?1:0,ArrowUp:index>=size?-size:0,ArrowDown:index<size*(size-1)?size:0}[event.key];if(change!==undefined){event.preventDefault();model.choose(index+change);$('sudoku-board').querySelector(`[data-index="${index+change}"]`)?.focus({preventScroll:true});}}
    else if(/^[1-9]$/.test(event.key)&&Number(event.key)<=size){event.preventDefault();void run(()=>model.input(Number(event.key)));}
    else if(['Delete','Backspace'].includes(event.key)){event.preventDefault();void run(()=>model.input(0));}
  });
  scope.listen($('sudoku-retry-settlement'),'click',()=>void run(()=>model.complete()));
  scope.listen($('sudoku-clock-retry'),'click',()=>void run(()=>model.setPaused('manual',false)));
  scope.listen($('sudoku-reload'),'click',()=>void run(()=>model.load()));
  scope.listen($('sudoku-restart'),'click',()=>{collection.cancel();$('sudoku-restart-dialog').querySelector('p').textContent='本题的填写和笔记将清空，其他题目进度保留。'+energyHint(model.state.attempt.puzzle.tutorial,true);$('sudoku-restart-dialog').showModal();void run(()=>model.setPaused('restart',true));});
  scope.listen($('sudoku-restart-cancel'),'click',()=>$('sudoku-restart-dialog').close());
  scope.listen($('sudoku-restart-dialog'),'close',()=>void run(()=>model.setPaused('restart',false)));
  scope.listen($('sudoku-restart-confirm'),'click',()=>{$('sudoku-restart-dialog').close();emit(Events.SETTLEMENT_CLOSED);void play(()=>model.restart());});
  const timer=setInterval(timing,250);scope.add(()=>clearInterval(timer));
  scope.listen(document,'visibilitychange',()=>{if(document.hidden)collection.cancel();if(model)void run(()=>model.setPaused('hidden',document.hidden));});
  scope.listen(window,'pagehide',()=>{if(model)void model.setPaused('pagehide',true,{immediate:true}).catch(()=>{});});
  scope.listen(matchMedia('(prefers-reduced-motion: reduce)'),'change',event=>{if(event.matches)collection.cancel();});
  return {
    /** 换号先销毁旧局和动画，避免跨账号异步显示。 */
    async setUser(uid){
      if(identity===uid&&model)return;collection.cancel(false);identity=uid;model?.destroy();selectionOnly=false;boardKey='';pendingFocus=null;errorMessage='';
      pendingLevel=null;$('sudoku-enter-dialog').close();$('sudoku-restart-dialog').close();
      // 身份变化即移除旧账号内容，不能只隐藏带旧答案/笔记的父容器。
      $('sudoku-board').replaceChildren();$('sudoku-keypad').replaceChildren();$('sudoku-result-title').textContent='';$('sudoku-result-description').textContent='';
      $('sudoku-result-stars').replaceChildren();$('sudoku-play').hidden=true;$('sudoku-selector').hidden=false;
      $('sudoku-message').textContent='';
      let storage;try{storage=window.localStorage;}catch{/* 由存储模块提示不可持久化。 */}
      const next=createSudokuSession({uid,storage,onChange:state=>render(state),onReward:(result,{restored})=>{
        if(dead||identity!==uid)return;render(next.state);
        if(restored)emit(Events.PROGRESSION_CONFIRMED,{userId:uid,progression:result.progression});
        else{void collection.play({key:next.state.attempt.attempt_id,userId:uid,progression:result.progression,awardedStars:result.awarded_stars,source:$('sudoku-result-stars'),target:document.querySelector('.player-stars')});emit(Events.SETTLEMENT_OPENED,{runId:next.state.attempt.attempt_id});}
        onReward();
      }});model=next;
      if(document.hidden)await next.setPaused('hidden',true,{sync:false});
      ready=run(()=>next.load());await ready;
    },
    /** 显式刷新重读目录及当前正式资源，不创建新局。 */
    async refresh(){if(model&&!model.state.busy)await run(()=>model.load());},
    /** 卸载清理监听器、时钟、会话和音效事件。 */
    destroy(){dead=true;collection.cancel(false);model?.destroy();scope.dispose();emit(Events.SETTLEMENT_CLOSED);},
  };
}
