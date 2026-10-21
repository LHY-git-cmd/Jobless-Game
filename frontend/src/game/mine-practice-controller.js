/** 多关卡练习页面：连接关卡目录、独立存档和复用的扫雷棋盘，不提交正式成绩。 */
import { cacheIds } from '../lib/dom.js';
import { Events } from '../lib/events.js';
import { createScope } from '../lib/lifecycle.js';
import { getAudioSettings } from '../audio-settings.js';
import { formatTime } from '../session.js';
import { MINE_LEVELS, mineLevel } from '../games/mine/levels.js';
import { createMinePracticeStore } from '../games/mine/practice-store.js';
import { createMineController } from './mine-controller.js';

/** user 为会话确认后的身份；游客无需登录，身份切换由既有认证事件驱动。 */
export function createMinePracticeController({ dom = document, view = window, user = null, storage, settings } = {}) {
  const scope=createScope();
  const ui=cacheIds({ cards:'practice-levels',change:'practice-change',owner:'practice-owner',panel:'practice-game',empty:'practice-empty',
    title:'practice-game-title',description:'practice-game-description',kicker:'practice-game-kicker',restart:'practice-restart',
    rulesButton:'practice-rules',rules:'practice-rules-dialog',rulesTitle:'practice-rules-title',rulesDescription:'practice-rules-description',
    rulesTiming:'practice-rules-timing',start:'practice-start',safeTotal:'practice-safe-total',timer:'practice-timer',
    outcome:'practice-outcome',outcomeTitle:'practice-outcome-title',outcomeDescription:'practice-outcome-description',
    next:'practice-next',storageStatus:'practice-storage-status',board:'practice-board',viewport:'practice-viewport',
    caption:'practice-caption',minesLeft:'practice-mines',cleared:'practice-cleared',selection:'practice-selection',
    flag:'practice-flag',reveal:'practice-reveal',message:'practice-message',mineSound:'practice-sound' },dom);
  if(storage===undefined) { try { storage=view.localStorage; } catch { /* 使用内存继续练习。 */ } }
  const store=createMinePracticeStore({storage,userId:user?.id??null});
  const cardNodes=new Map();
  let destroyed=false;
  const mine=createMineController({ui,dom,settings:settings??getAudioSettings(view),canPlay,
    onChange:changed,onComplete:showOutcome,onBusyChange:updateActions});

  /** 规则确认前及终盘期间不可操作，切换不暂停已开始棋局的绝对计时。 */
  function canPlay() {
    return !destroyed && Boolean(store.current) && store.current.game.startedAt!==null &&
      !ui.rules.open && !['won','lost'].includes(store.current.game.status) && !mine.busy;
  }

  /** 存储失败只显示提示，保留棋盘和当前内存进度。 */
  function save() {
    if(destroyed)return;
    const saved=store.save();
    ui.storageStatus.textContent=saved?'':'当前浏览器无法保存进度，本次仍可练习；关闭页面后可能无法恢复。';
  }

  /** 状态文案同时用于选关卡和读屏，结束与进行中不只靠颜色区分。 */
  function stateLabel(entry) {
    if(!entry)return '开始练习';
    if(entry.game.status==='won')return '已通关';
    if(entry.game.status==='lost')return '本局结束';
    return entry.game.startedAt===null?'待开始':'继续练习';
  }

  /** 卡片每秒只更新文字和状态，不重建按钮，避免键盘焦点丢失。 */
  function updateCards() {
    for(const level of MINE_LEVELS) {
      const nodes=cardNodes.get(level.id),entry=store.entries[level.id];
      nodes.button.setAttribute('aria-pressed',String(store.activeId===level.id));
      nodes.button.setAttribute('aria-label',`${level.name}，${level.difficulty}，${level.mineCount}颗雷，${stateLabel(entry)}`);
      nodes.state.textContent=stateLabel(entry);
      nodes.time.textContent=entry?formatTime(store.seconds(level.id)):'尚未开始';
    }
  }

  /** 只刷新显示计时；不每秒写盘、重画棋盘或请求后端。 */
  function tick() {
    if(destroyed)return;
    ui.timer.textContent=store.activeId?formatTime(store.seconds(store.activeId)):'00:00';
    updateCards();
  }

  /** 渲染后同步保存当前引用，并按规则窗口状态限制操作按钮。 */
  function changed() { save();tick();updateActions(); }

  /** 复用控制器会更新基础按钮状态，此处补充页面级可操作限制。 */
  function updateActions() {
    if(!store.current)return;
    const playable=canPlay(),game=store.current.game;
    ui.flag.disabled=!playable||game.selected===null;
    ui.reveal.disabled=!playable||game.selected===null||game.cells[game.selected]?.flagged;
    ui.rulesButton.disabled=mine.busy;
  }

  /** 结果采用棋盘下方反馈，玩家可继续查看终盘或切换其他关。 */
  function showOutcome(focus=true) {
    const entry=store.current;
    if(!entry)return;
    const game=entry.game,ended=['won','lost'].includes(game.status);
    ui.outcome.hidden=!ended;
    if(!ended)return;
    const level=mineLevel(store.activeId),won=game.status==='won';
    ui.outcomeTitle.textContent=won?'这片雷区，已被你解开。':'踩到地雷，下一次再试试。';
    ui.outcomeDescription.textContent=won
      ?`${level.name}已通关，排开 ${game.cells.length-game.level.mineCount} 个安全格，用时 ${formatTime(store.seconds(level.id))}。可以继续查看棋盘，或试试下一关。`
      :`${level.mineCount} 颗地雷已显示，本局用时 ${formatTime(store.seconds(level.id))}。可以重开本关，也可以换个档位。`;
    const index=MINE_LEVELS.findIndex(item=>item.id===level.id);
    ui.next.textContent=index===MINE_LEVELS.length-1?'回到入门关':'试试下一关';
    save();tick();updateActions();
    if(focus)ui.outcome.focus({preventScroll:true});
  }

  /** 原生 dialog 限制焦点，首次规则明确确认后才开始计时。 */
  function openRules() {
    if(!store.current||mine.busy)return;
    store.showRules();
    const level=mineLevel(store.activeId),game=store.current.game,ended=['won','lost'].includes(game.status);
    ui.rulesTitle.textContent=`${level.name} · ${level.difficulty}`;
    ui.rulesDescription.textContent=`${level.rows} × ${level.cols} 棋盘，${level.mineCount} 颗地雷，排开 ${level.rows*level.cols-level.mineCount} 个安全格即可通关。`;
    ui.rulesTiming.textContent=ended?'本局已结束，用时已固定。':game.startedAt===null?'点击“开始本关”后才开始计时。':'本关已经开始，查看规则期间继续计时。';
    ui.start.textContent=ended?'返回棋盘':game.startedAt===null?'开始本关':'继续本关';
    if(!ui.rules.open)ui.rules.showModal();
    ui.start.focus();save();updateActions();
  }

  /** 开始动作与按钮、已开始后的 Esc 共用，重复调用不重置起点。 */
  function closeRules() {
    if(!store.current)return;
    store.start();ui.rules.close();mine.start(store.current.game.startedAt);
    focusGame();changed();
  }

  /** 手机上开始后把棋盘带入视野；减少动态效果时使用即时滚动。 */
  function focusGame() {
    ui.panel.scrollIntoView({block:'start',behavior:view.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    ui.viewport.focus({preventScroll:true});
  }

  /** 保存旧关并停止其动画，恢复新关已有棋盘，不复制三套控制器。 */
  function select(id,{focus=false}={}) {
    save();
    if(ui.rules.open)ui.rules.close();
    const entry=store.select(id),level=mineLevel(id);
    mine.restore(entry.game);
    ui.empty.hidden=true;ui.panel.hidden=false;ui.outcome.hidden=true;ui.message.textContent='';
    ui.title.textContent=level.name;ui.description.textContent=level.description;
    ui.kicker.textContent=`${level.difficulty} / ${level.mineCount} 颗雷`;
    ui.safeTotal.textContent=` / ${level.rows*level.cols-level.mineCount}`;
    mine.render();showOutcome(false);
    if(entry.rulesOpen)openRules();
    else if(focus)focusGame();
    changed();
  }

  /** 当前关重开重置计时，其他关进度完整保留。 */
  function restart() {
    if(!store.current)return;
    store.restart();select(store.activeId);openRules();
  }

  /** 用户身份决定本地命名空间，游客进度不自动合并到账号。 */
  function showOwner(value) {
    ui.owner.textContent=value?`${value.username}的练习进度 · 本浏览器保存`:'游客练习 · 无需登录，进度保存在本浏览器';
  }

  /** 身份变更先落盘，再清理旧棋盘和弹窗，防止展示上个账号数据。 */
  function setUser(value) {
    if(ui.rules.open)ui.rules.close();
    store.setUser(value?.id??null);mine.clear();ui.panel.hidden=true;ui.empty.hidden=false;
    showOwner(value);updateCards();
    if(store.activeId)select(store.activeId);
  }

  // 关卡按钮使用原生 button 和 aria-pressed，同时提供名称、密度与可恢复状态。
  for(const [index,level] of MINE_LEVELS.entries()) {
    const button=dom.createElement('button');button.type='button';button.className='practice-level';button.dataset.level=level.id;
    const head=dom.createElement('span');head.className='practice-level-head';
    const number=dom.createElement('span');number.textContent=`0${index+1} / ${level.difficulty}`;
    const density=dom.createElement('span');density.textContent=`${level.mineCount} 颗雷`;head.append(number,density);
    const title=dom.createElement('span');title.className='practice-level-title';title.textContent=level.name;
    const description=dom.createElement('span');description.className='practice-level-description';description.textContent=level.description;
    const footer=dom.createElement('span');footer.className='practice-level-footer';
    const state=dom.createElement('span');state.className='practice-level-state';
    const time=dom.createElement('span');footer.append(state,time);button.append(head,title,description,footer);ui.cards.append(button);
    button.setAttribute('aria-controls','practice-game');
    cardNodes.set(level.id,{button,state,time});
    scope.listen(button,'click',()=>select(level.id,{focus:true}));
  }
  scope.listen(ui.start,'click',closeRules);
  scope.listen(ui.rulesButton,'click',openRules);
  scope.listen(ui.rules,'cancel',event=>{
    event.preventDefault();
    if(store.current?.game.startedAt!==null)closeRules();
  });
  scope.listen(ui.rules,'keydown',event=>{
    // 首次规则拦截 Esc 的默认关闭请求，避免关闭窗口却没有确认起计时。
    if(event.key!=='Escape')return;
    event.preventDefault();
    if(store.current?.game.startedAt!==null)closeRules();
  });
  scope.listen(ui.restart,'click',restart);
  scope.listen(ui.change,'click',()=>{
    ui.cards.scrollIntoView({block:'start',behavior:'instant'});
    cardNodes.get(store.activeId)?.button.focus({preventScroll:true});
  });
  scope.listen(ui.next,'click',()=>{
    const index=MINE_LEVELS.findIndex(level=>level.id===store.activeId);
    select(MINE_LEVELS[(index+1)%MINE_LEVELS.length].id,{focus:true});
  });
  scope.listen(dom,Events.AUTH_CHANGED,event=>setUser(event.detail?.user??null));
  scope.listen(dom,'click',save);
  scope.listen(dom,'visibilitychange',()=>{save();tick();});
  scope.listen(view,'pagehide',save);
  scope.listen(view,'pageshow',tick);
  const timer=view.setInterval(tick,1000);scope.add(()=>view.clearInterval(timer));
  showOwner(user);tick();
  if(store.activeId)select(store.activeId);
  return {
    /** 页面卸载先落盘，随后释放所有页面/棋盘资源和音频订阅。 */
    destroy() { if(destroyed)return;save();destroyed=true;scope.dispose();mine.destroy();if(ui.rules.open)ui.rules.close(); },
  };
}
