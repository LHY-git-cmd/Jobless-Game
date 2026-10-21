/** 扫雷页面：五档选关、四步教学、权威棋盘及账号成长结算。 */
import { createMineSession } from '../games/mine/session.js';
import { createScope } from '../lib/lifecycle.js';
import { Events, emit } from '../lib/events.js';
import { getAudioSettings } from '../audio-settings.js';
import { createExplosionSequence, createExplosionSound, explosionOrder } from '../mine-effects.js';
import { availableMineStars, paintMineStars, createStarCollection } from './mine-stars.js';

const DIFFICULTIES=[['tutorial','入门','从零学会'],['easy','简单','轻松起步'],['medium','中等','多想一步'],['hard','困难','步步推理'],['hell','地狱','极限挑战']];
const FLAG='<img src="./assets/minesweeper/v2/flag.webp" width="24" height="24" alt="">';

/** 秒数向下显示，星级仍按服务端毫秒判定。 */
export function mineTime(ms){const seconds=Math.max(0,Math.floor(ms/1000));return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;}

/** auth由页面共享，控制器换号时销毁旧会话及所有动画。 */
export function createMineJourney({host,auth,onReward=()=>{}}) {
  const scope=createScope(),settings=getAudioSettings();
  let model,identity,selectionOnly=false,lastId=null,lastOutcome=null,animation=null,finished=true,dead=false,errorMessage='';
  let renderedBoard='';
  let identityReady=Promise.resolve();
  const sound=createExplosionSound(new URL('../../assets/audio/explosion.wav',import.meta.url));
  // 模板只包含开发者静态结构；接口文本和用户状态统一使用textContent。
  host.innerHTML=`
    <div id="mine-selector" class="mine-selector">
      <div class="mine-intro"><div><p class="eyebrow">MINESWEEPER · 每一步，都有线索</p><h2>选一个难度，开始推理。</h2><p>找到所有安全格，把星星带回旅程。</p></div><img src="./assets/minesweeper/v2/theme.webp" width="84" height="84" alt=""></div>
      <div id="mine-difficulties" class="mine-difficulties" role="group" aria-label="扫雷难度"></div>
      <div class="mine-options-heading"><h3 id="mine-options-title">选择棋盘</h3><span>全部难度自由选择</span></div>
      <div id="mine-specs" class="mine-specs" role="group" aria-labelledby="mine-options-title"></div>
      <div class="mine-start-row"><p id="mine-reward-note">正在加载难度…</p><button id="mine-start" class="journey-primary" type="button" disabled>开始游戏 <span aria-hidden="true">→</span></button></div>
    </div>
    <section id="mine-play" class="mine-play" aria-labelledby="mine-play-title" hidden>
      <div class="mine-play-heading"><button id="mine-back" type="button">← 返回选关</button><div><p id="mine-play-kicker" class="eyebrow"></p><h2 id="mine-play-title"></h2></div><div class="journey-actions"><button id="mine-rules" type="button">规则</button><button id="mine-sound" type="button">音效：开</button><button id="mine-restart" type="button">重新开始</button></div></div>
      <div class="mine-stats"><div><span>剩余雷标记</span><strong id="mine-left">0</strong></div><div><span>可得星数</span><span id="mine-available-stars" class="mine-rating mine-stat-stars" aria-live="polite"></span></div><div><span>本局用时</span><strong id="mine-clock">00:00</strong></div></div>
      <div id="mine-tutorial" class="mine-tutorial" hidden><span id="mine-tutorial-count" class="eyebrow"></span><h3 id="mine-tutorial-title"></h3><p id="mine-tutorial-text"></p><button id="mine-understood" type="button" class="journey-primary" hidden>明白了，试试标记 →</button></div>
      <div id="mine-viewport" class="mine-viewport" tabindex="0" role="region" aria-label="扫雷棋盘，可上下左右滚动"><div id="mine-board" class="mine-board" role="group" aria-label="扫雷棋盘"></div></div>
      <div class="mine-operation"><p id="mine-selection">先点选一个格子</p><div class="journey-actions"><button id="mine-flag" type="button">${FLAG}标记</button><button id="mine-reveal" class="journey-primary" type="button">排雷</button></div></div>
      <p class="mine-help">点选格子，再选择标记或排雷。<span class="mine-keyboard-hint">方向键移动 · Enter 选中 · </span>棋盘内可滑动。</p>
      <div id="mine-result" class="mine-result" role="status" hidden><p class="eyebrow" id="mine-result-kicker"></p><h3 id="mine-result-title"></h3><div id="mine-result-stars" class="mine-rating mine-result-stars"></div><p id="mine-result-description"></p><button id="mine-retry-settlement" type="button" hidden>重试保存奖励</button></div>
    </section>
    <div class="mine-feedback"><p id="mine-message" role="status" aria-live="polite"></p><button id="mine-reload" type="button" hidden>重新加载</button></div>
    <dialog id="mine-rules-dialog" class="journey-rules" aria-labelledby="mine-rules-title"><h2 id="mine-rules-title">扫雷怎么玩</h2><p>揭开所有没有地雷的格子，即可通关。</p><ol><li>数字表示周围八个格子中的地雷数量。</li><li>怀疑有雷时，先标记；标记格不会被排开。</li><li>空白格会自动展开，普通关首次揭格保证安全。</li></ol><p id="mine-rules-reward"></p><p id="mine-rules-timing"></p><button id="mine-rules-confirm" class="journey-primary" type="button">开始游戏</button></dialog>
    <dialog id="mine-restart-dialog" class="journey-rules" aria-labelledby="mine-restart-title"><h2 id="mine-restart-title">重新开始本关？</h2><p>当前棋局将被放弃，其他关卡的进度会保留。</p><div class="journey-actions"><button id="mine-restart-cancel" type="button">继续当前局</button><button id="mine-restart-confirm" type="button" class="journey-primary">确认重开</button></div></dialog>`;
  const $=id=>host.querySelector(`#${id}`);
  let rulesStarting=false;
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
    if(!level){$('mine-start').disabled=true;return;}
    for(const button of $('mine-difficulties').children){button.setAttribute('aria-pressed',String(button.dataset.difficulty===level.difficulty));button.disabled=state.busy;}
    const specs=state.levels.filter(v=>v.difficulty===level.difficulty);
    $('mine-specs').replaceChildren();
    for(const item of specs){
      const button=document.createElement('button');button.type='button';button.className='mine-spec';button.dataset.level=item.level_id;
      button.setAttribute('aria-pressed',String(item.level_id===state.selected));button.disabled=state.busy;
      const size=document.createElement('strong'),caption=document.createElement('span'),rating=document.createElement('span'),best=document.createElement('small');
      const footer=document.createElement('span'),stars=document.createElement('span');footer.className='mine-spec-footer';stars.className='mine-rating';
      size.textContent=item.difficulty==='tutorial'?'跟着提示，学会扫雷':`${item.cols} × ${item.rows}`;
      caption.textContent=`${item.mine_count} 颗地雷 · ${item.difficulty==='tutorial'?'四步引导，轻松上手':`${item.rows*item.cols-item.mine_count} 个安全格`}`;
      rating.className='mine-spec-reward';rating.textContent=item.difficulty==='tutorial'?'完成得 1 星 · 2 经验':`三星 ${mineTime(item.t3_ms)} 内 · ${item.star_xp.at(-1)} 经验`;
      const progress=state.progress.find(v=>v.level_id===item.level_id);
      best.textContent=progress?.best_stars?'已通关':progress?.current_attempt?'有进行中的棋局':'尚未通关';
      paintMineStars(stars,progress?.best_stars||0,`历史最高${progress?.best_stars||0}星${item.max_stars===1?'，入门教学最高1星':''}`);
      footer.append(best,stars);button.append(size,caption,rating,footer);$('mine-specs').append(button);
    }
    const progress=state.progress.find(v=>v.level_id===level.level_id);
    $('mine-options-title').textContent=level.difficulty==='tutorial'?'你的第一堂扫雷课':'选择棋盘';
    $('mine-reward-note').textContent=level.difficulty==='tutorial'?'认识数字、学会标记，再独立完成一盘。完成后获得 1 星、2 经验。':`三星 ≤ ${mineTime(level.t3_ms)} · 二星 ≤ ${mineTime(level.t2_ms)} · 其余通关一星。经验 ${level.star_xp.join(' / ')}，提升星级补差额。`;
    $('mine-start').textContent=state.busy?'正在准备…':progress?.current_attempt?'继续游戏 →':model.hasSaved(level.level_id)?'查看上局 →':'开始游戏 →';
    $('mine-start').disabled=state.busy||!state.enabled;
  }
  /** 复用44px格子，已揭数字和终盘雷区来自服务端。 */
  function renderBoard(state){
    const attempt=state.attempt;if(!attempt)return;
    const {rows,cols}=attempt.puzzle,board=attempt.board;
    const key=JSON.stringify([attempt.attempt_id,board,state.flags,state.cell,state.busy,finished]);
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
      cell.disabled=state.busy||board.outcome!=='active';
      cell.setAttribute('aria-label',`第 ${Math.floor(index/cols)+1} 行第 ${index%cols+1} 列，${description}${target?'，教学目标':''}`);
      // 已揭格仍可聚焦读取数字；其余输入由会话判断，终盘统一禁用操作按钮。
      cell.setAttribute('aria-disabled',String(state.busy||board.outcome!=='active'||value!==undefined));
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
  /** 明确区分本局星级与本次新增奖励。 */
  function renderResult(state){
    const board=state.attempt.board,lost=board.outcome==='lost',won=board.outcome==='won';
    $('mine-result').hidden=(!lost&&!won)||(lost&&!finished);
    $('mine-retry-settlement').hidden=!won||Boolean(state.result);
    $('mine-retry-settlement').disabled=state.busy;
    if(!lost&&!won)return;
    $('mine-result-kicker').textContent=lost?'下一次，再近一点':state.result?'本关成绩已保存':'通关成功';
    $('mine-result-title').textContent=lost?'碰到地雷了，再试一次吧。':state.result?'安全格全部找到！':'正在保存奖励…';
    $('mine-result-stars').hidden=!state.result;
    if(state.result)paintMineStars($('mine-result-stars'),state.result.stars,`本局获得${state.result.stars}星`);
    $('mine-result-description').textContent=lost?'雷区已显示。重新开始会生成新棋盘，其他关卡的进度会保留。':state.result
      ?`用时 ${mineTime(state.result.duration_ms)} · 历史最高 ${state.result.best_stars} 星 · 本次新增 ${state.result.awarded_stars} 星、${state.result.awarded_xp} 经验。`
      :'终盘和用时已保留。若网络失败，点击重试保存奖励。';
  }
  /** 轻量时钟与可得星数同源计算，阅读规则/离开期间照常递减，终盘后冻结。 */
  function renderTiming(){
    const state=model?.state,attempt=state?.attempt;if(!attempt)return;
    const level=state.levels.find(item=>item.level_id===attempt.level_id),elapsed=model.elapsed();
    $('mine-clock').textContent=mineTime(elapsed);
    const count=availableMineStars(level,elapsed,attempt.board.outcome,state.result?.stars);
    paintMineStars($('mine-available-stars'),count,attempt.puzzle.tutorial?'入门教学固定可得1星':`本局可得${count}星`);
  }
  /** 只有服务端状态变化才重建棋盘；计时显示由独立低频定时器更新。 */
  function render(state){
    if(dead)return;
    renderSelection(state);
    const playing=Boolean(state.attempt)&&!selectionOnly&&state.attempt.level_id===state.selected;
    $('mine-selector').hidden=playing;$('mine-play').hidden=!playing;
    if(state.attempt){
      const attempt=state.attempt,board=attempt.board;
      if(attempt.attempt_id!==lastId){stopAnimation();lastId=attempt.attempt_id;lastOutcome=null;renderedBoard='';}
      const animate=playing&&board.outcome==='lost'&&lastOutcome==='active'&&!matchMedia('(prefers-reduced-motion: reduce)').matches;
      if(animate){animation={visible:new Set(),exploded:new Set(),settled:new Set()};finished=false;}
      lastOutcome=board.outcome;
      const level=state.levels.find(v=>v.level_id===attempt.level_id);
      $('mine-play-title').textContent=level?.name||'扫雷';$('mine-play-kicker').textContent=`${attempt.puzzle.cols} × ${attempt.puzzle.rows} · ${attempt.puzzle.mine_count} 颗地雷`;
      $('mine-left').textContent=attempt.puzzle.mine_count-state.flags.length;
      renderTiming();
      const active=board.outcome==='active'&&!state.busy&&finished;
      const chosen=state.cell!==null&&!board.revealed.some(v=>v.index===state.cell);
      $('mine-flag').disabled=!active||!chosen;$('mine-reveal').disabled=!active||!chosen||state.flags.includes(state.cell);
      $('mine-flag').innerHTML=FLAG+(state.flags.includes(state.cell)?'取消标记':'标记');
      $('mine-restart').disabled=state.busy||!finished;$('mine-rules').disabled=state.busy||!finished;
      $('mine-selection').textContent=state.cell===null?'先点选一个格子':`已选第 ${Math.floor(state.cell/attempt.puzzle.cols)+1} 行，第 ${state.cell%attempt.puzzle.cols+1} 列`;
      renderBoard(state);renderTutorial(attempt);renderResult(state);
      if(animate){
        const game={status:'lost',explodedAt:board.revealed.find(v=>v.value===-1)?.index,level:{cols:attempt.puzzle.cols},cells:Array.from({length:attempt.puzzle.rows*attempt.puzzle.cols},(_,index)=>({mine:board.mines.includes(index)}))};
        sequence.start(explosionOrder(game));
      }
    }
    $('mine-message').textContent=errorMessage||state.message||(!state.enabled&&state.levels.length?'扫雷暂未开放，请稍后重试。':'');
    $('mine-reload').hidden=!errorMessage||Boolean(state.attempt);$('mine-reload').disabled=state.busy;
  }
  /** 规则阅读完成前不发开局请求，已有棋局重看不停止计时。 */
  function openRules(starting){
    rulesStarting=starting;
    const level=model.state.levels.find(v=>v.level_id===model.state.selected);
    $('mine-rules-reward').textContent=level?.difficulty==='tutorial'?'跟随四步引导完成，获得1星、2经验。':`三星 ≤ ${mineTime(level.t3_ms)}，二星 ≤ ${mineTime(level.t2_ms)}。重复成绩不重复奖励，提升星级补差额。`;
    $('mine-rules-timing').textContent=starting?'点击“开始游戏”后开始计时。':'游戏已开始，查看规则和离开页面期间继续计时。';
    $('mine-rules-confirm').textContent=starting?'开始游戏':'继续游戏';$('mine-rules-dialog').showModal();
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
  scope.listen($('mine-specs'),'click',event=>{const button=event.target.closest('[data-level]');if(button)model.select(button.dataset.level);});
  scope.listen($('mine-start'),'click',()=>{
    const selected=model.state.selected;
    void auth.requireLogin(async()=>{
      await identityReady;
      if(dead)return;
      model.select(selected);
      const progress=model.state.progress.find(v=>v.level_id===model.state.selected);
      if(progress?.current_attempt||model.hasSaved(model.state.selected)){selectionOnly=false;return runPlay(()=>model.open());}
      openRules(true);
    });
  });
  scope.listen($('mine-rules'),'click',()=>openRules(false));
  scope.listen($('mine-rules-confirm'),'click',()=>{
    $('mine-rules-dialog').close();
    if(rulesStarting){selectionOnly=false;void runPlay(()=>model.open());}
  });
  scope.listen($('mine-back'),'click',()=>{selectionOnly=true;collection.cancel();stopAnimation();emit(Events.SETTLEMENT_CLOSED);render(model.state);$('mine-start').focus();});
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
  scope.listen($('mine-restart'),'click',()=>{
    collection.cancel();
    if(model.state.attempt?.board.outcome==='active')$('mine-restart-dialog').showModal();
    else {stopAnimation();emit(Events.SETTLEMENT_CLOSED);void runPlay(()=>model.restart());}
  });
  scope.listen($('mine-restart-cancel'),'click',()=>$('mine-restart-dialog').close());
  scope.listen($('mine-restart-confirm'),'click',()=>{$('mine-restart-dialog').close();stopAnimation();emit(Events.SETTLEMENT_CLOSED);void runPlay(()=>model.restart());});
  scope.listen($('mine-reload'),'click',()=>void run(()=>model.load()));
  scope.listen($('mine-sound'),'click',()=>{settings.update({effectsEnabled:!settings.state.effectsEnabled});sound.unlock();});
  scope.add(settings.subscribe(value=>{
    sound.setMuted(!value.effectsEnabled);sound.setVolume(value.effectsVolume);
    $('mine-sound').textContent=`音效：${value.effectsEnabled?'开':'关'}`;$('mine-sound').setAttribute('aria-pressed',String(!value.effectsEnabled));
  }));
  const timer=setInterval(renderTiming,250);
  scope.add(()=>clearInterval(timer));
  scope.listen(document,'visibilitychange',()=>{if(document.hidden)collection.cancel();});
  scope.listen(matchMedia('(prefers-reduced-motion: reduce)'),'change',event=>{if(event.matches)collection.cancel();});
  return {
    /** 换号先销毁旧请求和棋盘，再加载新账号自己的目录进度。 */
    async setUser(uid){
      if(identity===uid&&model)return;collection.cancel(false);identity=uid;model?.destroy();stopAnimation();selectionOnly=false;lastId=null;lastOutcome=null;errorMessage='';
      $('mine-rules-dialog').close();$('mine-restart-dialog').close();
      let storage;try{storage=window.localStorage;}catch{/* 存储禁用仍可依靠服务端续玩。 */}
      const next=createMineSession({uid,storage,onChange:state=>render(state),onReward:result=>{
        render(next.state);
        void collection.play({key:next.state.attempt.attempt_id,userId:uid,progression:result.progression,awardedStars:result.awarded_stars,
          source:$('mine-result-stars'),target:document.querySelector('.player-stars')});
        emit(Events.SETTLEMENT_OPENED,{runId:next.state.attempt.attempt_id});onReward();
      }});
      model=next;identityReady=run(()=>next.load());await identityReady;
    },
    /** 主动刷新只重读当前账号资料；界面重载时也会GET核验原局。 */
    async refresh(){if(model&&!model.state.busy)await run(()=>model.load());},
    /** 清理全部事件、音效和待返回请求。 */
    destroy(){dead=true;collection.cancel(false);model?.destroy();stopAnimation();scope.dispose();emit(Events.SETTLEMENT_CLOSED);},
  };
}
