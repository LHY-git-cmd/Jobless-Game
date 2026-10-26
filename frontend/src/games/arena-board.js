/** 竞技棋盘视图：使用闯关样式、素材及规则，隔离竞技网络与闯关奖励会话。 */
import { createArenaBoardState } from './arena-board-state.js';
import { inspectAkari, akariCell } from './akari/rules.js';
import { sudokuConflicts } from './sudoku/rules.js';
import { mineCellSize } from './mine/presentation.js';

/** 调用者只提供当前局快照及输入回调，棋盘不创建尝试或发放奖励。 */
export function createArenaBoard({host,onChange=()=>{},onReveal=()=>{},onComplete=()=>{}}) {
  let model=null,key=null;
  /** 文案、键盘名和样式类由静态结构提供，玩家输入仅写入textContent。 */
  function button(text,action,primary=false){const node=document.createElement('button');node.type='button';node.textContent=text;node.dataset.action=action;if(primary)node.className='journey-primary';node.disabled=model.disabled;return node;}
  /** 整盘随视口可用宽高缩放，沿用闯关尺寸计算，不产生页面横向滚动。 */
  function fit(){
    if(!model||!host.isConnected)return;
    const {rows,cols}=model.puzzle,width=Math.max(1,host.clientWidth-32);
    const screen=window.visualViewport;
    const height=Math.max(100,(screen?screen.height*screen.scale:window.innerHeight)-host.getBoundingClientRect().top-130);
    if(model.game==='mine')host.querySelector('.mine-board')?.style.setProperty('--mine-cell',`${mineCellSize({rows,cols,width:width-12,height})}px`);
    if(model.game==='akari')host.style.setProperty('--akari-cell-size',`${Math.max(1,Math.floor(Math.min(52,(width-cols-1)/cols,(height-24-rows)/rows)))}px`);
  }
  /** 共享闯关棋盘类，重绘只发生在输入/服务器状态改变，时钟不重绘格子。 */
  function render(){
    if(!model){host.replaceChildren();key=null;return;}
    const next=JSON.stringify([model.snapshot(),model.mine,model.disabled,model.canUndo()]);
    if(next===key){fit();return;}key=next;
    const focused=host.contains(document.activeElement)?document.activeElement?.dataset.index:null;
    const game=model.game,puzzle=model.puzzle;
    host.className=`arena-board-host ${game}-host`;
    const viewport=document.createElement('div');viewport.className=`${game==='mine'?'mine-viewport':game==='akari'?'akari-viewport':'sudoku-board-wrap'} arena-board-viewport`;
    const board=document.createElement('div');board.className=`${game}-board`;
    board.setAttribute('role','group');board.setAttribute('aria-label',`${game==='mine'?'扫雷':game==='akari'?'照明':'数独'}棋盘`);
    board.style.setProperty(game==='mine'?'--mine-cols':game==='akari'?'--akari-cols':'--sudoku-size',puzzle.cols);
    if(game==='sudoku')board.dataset.size=puzzle.rows;
    const inspection=game==='akari'?inspectAkari(model.akari):null;
    const conflicts=game==='sudoku'?sudokuConflicts(model.grid):null;
    const revealed=new Map(model.mine.revealed.map(v=>[v.index,v.value]));
    for(let index=0;index<puzzle.rows*puzzle.cols;index++){
      const row=Math.floor(index/puzzle.cols),col=index%puzzle.cols;
      const cell=document.createElement('button');cell.type='button';cell.dataset.index=index;cell.disabled=model.disabled;
      let description='';
      if(game==='mine'){
        const value=revealed.get(index),flagged=model.flags.includes(index);
        cell.className='mine-square';cell.classList.toggle('mine-selected',model.selected===index);
        if(value!==undefined&&value>=0){cell.classList.add('mine-open');cell.dataset.number=value;cell.textContent=value>3?value:'';description=`周围 ${value} 颗雷`;}
        else if(value===-1){cell.classList.add('mine-exploded');description='踩中地雷';}
        else{cell.classList.toggle('mine-flagged',flagged);description=flagged?'已标记':'未揭开';}
        cell.disabled ||= model.mine.outcome!=='active';
        cell.setAttribute('aria-pressed',String(model.selected===index));
      }else if(game==='akari'){
        const type=akariCell(index,model.akari),bulb=model.akari.bulbs.has(index);
        cell.className='akari-cell';
        cell.classList.toggle('wall',type!=='.');cell.classList.toggle('lit',inspection.lit.has(index));cell.classList.toggle('bulb',bulb);
        const wrong=inspection.conflictingBulbs.has(index)||inspection.wrongClues.has(index)||(inspection.lit.size===inspection.whiteCount&&inspection.unmetClues.has(index));
        cell.classList.toggle('error',wrong);if(wrong)cell.setAttribute('aria-invalid','true');
        if(type!=='.'){cell.disabled=true;cell.textContent=type==='#'?'':type;description=type==='#'?'黑墙':`数字${type}，相邻${inspection.clueCounts.get(index)}盏灯`;}
        else{description=bulb?'已放灯':inspection.lit.has(index)?'已照亮':'未照亮';cell.setAttribute('aria-pressed',String(bulb));}
      }else{
        const grid=model.grid,selected=grid.selected,value=grid.values[index],box=grid.box;
        cell.className='sudoku-cell';cell.tabIndex=index===(selected??0)?0:-1;
        cell.classList.toggle('given',Boolean(grid.givens[index]));cell.classList.toggle('selected',selected===index);cell.classList.toggle('conflict',conflicts.has(index));
        cell.classList.toggle('box-right',(col+1)%box===0&&col<puzzle.cols-1);cell.classList.toggle('box-bottom',(row+1)%box===0&&row<puzzle.rows-1);
        if(selected!==null){const sr=Math.floor(selected/puzzle.cols),sc=selected%puzzle.cols;cell.classList.toggle('peer',row===sr||col===sc||(Math.floor(row/box)===Math.floor(sr/box)&&Math.floor(col/box)===Math.floor(sc/box)));cell.classList.toggle('same-value',value!==0&&value===grid.values[selected]);}
        const notes=[];
        if(value)cell.textContent=value;
        else if(grid.notes[index]){
          const holder=document.createElement('span');holder.className='sudoku-notes';holder.style.setProperty('--note-cols',box);holder.setAttribute('aria-hidden','true');
          for(let digit=1;digit<=puzzle.rows;digit++){const item=document.createElement('span');if(grid.notes[index]&(1<<(digit-1))){item.textContent=digit;notes.push(digit);}holder.append(item);}cell.append(holder);
        }
        description=`${value|| (notes.length?`候选数 ${notes.join('、')}`:'空格')}${grid.givens[index]?'，题目数字':''}${conflicts.has(index)?'，存在重复':''}`;
        cell.setAttribute('aria-pressed',String(selected===index));
      }
      cell.setAttribute('aria-label',`第 ${row+1} 行第 ${col+1} 列，${description}`);board.append(cell);
    }
    viewport.append(board);host.replaceChildren(viewport);
    const controls=document.createElement('div');controls.className=game==='sudoku'?'sudoku-input':'arena-board-controls';
    if(game==='mine'){
      const actions=document.createElement('div');actions.className='journey-actions';
      // 保留闯关的左右两组标记/排雷，手机单手均可操作。
      for(const [text,action] of [['标记','mark'],['排雷','reveal'],['标记','mark'],['排雷','reveal']]){const node=button(text,action,action==='reveal');node.disabled ||= model.selected===null||revealed.has(model.selected)||model.mine.outcome!=='active'||(action==='reveal'&&model.flags.includes(model.selected));actions.append(node);}
      controls.classList.add('mine-operation');controls.append(actions);
    }else if(game==='sudoku'){
      const keypad=document.createElement('div');keypad.className='sudoku-keypad';keypad.setAttribute('aria-label','填写数字');keypad.setAttribute('role','group');
      for(let digit=1;digit<=puzzle.rows;digit++){const node=button(String(digit),'digit');node.dataset.digit=digit;keypad.append(node);}
      const actions=document.createElement('div');actions.className='sudoku-actions has-undo';const undo=button('撤回上一步','undo');undo.disabled ||= !model.canUndo();
      const notes=button(`笔记：${model.grid.notesMode?'开':'关'}`,'notes');notes.setAttribute('aria-pressed',String(model.grid.notesMode));actions.append(undo,button('清除选中格','clear'),notes);controls.append(keypad,actions);
    }
    host.append(controls);
    const status=document.createElement('p');status.className='arena-board-status';status.setAttribute('role','status');
    status.textContent=game==='akari'?`已照亮：${inspection.lit.size} / ${inspection.whiteCount} 格；已放灯：${model.akari.bulbs.size} 盏${inspection.conflictingBulbs.size?' · 灯泡不能互相照射':inspection.wrongClues.size?' · 请检查数字周围灯数':''}`:game==='mine'?`还差排查 ${Math.max(0,puzzle.rows*puzzle.cols-puzzle.mine_count-model.mine.revealed.filter(v=>v.value>=0).length)} 格 · 先选格，再标记或排雷`:'方向键选格 · 数字键填写 · Delete 清除';
    host.append(status);fit();
    if(focused!==null)host.querySelector(`[data-index="${focused}"]`)?.focus({preventScroll:true});
  }
  /** 事件委托保留重绘后的控件绑定。 */
  function click(event){
    if(!model||model.disabled)return;
    const cell=event.target.closest('[data-index]');if(cell){model.choose(Number(cell.dataset.index));return;}
    const action=event.target.closest('[data-action]');if(!action||action.disabled)return;
    const actions={mark:()=>model.mark(),reveal:()=>model.reveal(),undo:()=>model.undo(),clear:()=>model.digit(0),notes:()=>model.toggleNotes(),digit:()=>model.digit(Number(action.dataset.digit))};actions[action.dataset.action]?.();
  }
  /** 沿用闯关键盘习惯，水平移动不跨行，照明跳过墙格。 */
  function keydown(event){
    if(!model||model.disabled||event.altKey||event.metaKey)return;
    if(model.game==='sudoku'){
      if(/^[1-9]$/.test(event.key)){event.preventDefault();model.digit(Number(event.key));return;}
      if(['Delete','Backspace'].includes(event.key)){event.preventDefault();model.digit(0);return;}
      if(event.ctrlKey&&event.key.toLowerCase()==='z'){event.preventDefault();model.undo();return;}
    }
    const current=Number(event.target.closest('[data-index]')?.dataset.index);if(!Number.isInteger(current))return;
    const cols=model.puzzle.cols,step={ArrowLeft:-1,ArrowRight:1,ArrowUp:-cols,ArrowDown:cols}[event.key];if(!step)return;
    let next=current+step;
    while(next>=0&&next<model.puzzle.rows*cols&&(Math.abs(step)!==1||Math.floor(next/cols)===Math.floor(current/cols))){
      const target=host.querySelector(`[data-index="${next}"]`);
      if(target&&!target.disabled){event.preventDefault();if(model.game!=='akari')model.choose(next);host.querySelector(`[data-index="${next}"]`)?.focus({preventScroll:true});return;}next+=step;
    }
  }
  host.addEventListener('click',click);host.addEventListener('keydown',keydown);window.addEventListener('resize',fit);window.visualViewport?.addEventListener('resize',fit);
  return {
    /** 加载新局后清空本地撤回栈，草稿只来自同一房间。 */
    load(game,puzzle,saved={},authority=null){key=null;model=createArenaBoardState(game,puzzle,saved,authority,{onChange:draft=>{onChange(draft);render();},onReveal,onComplete});render();},
    /** 请求和提交期间冻结输入。 */
    setDisabled(value){if(model){model.setDisabled(value);render();}},
    /** 权威扫雷快照不改变本人未揭格旗标。 */
    setMine(value){if(model){model.setMine(value);render();}},
    /** 提交只含服务器允许的终盘字段。 */
    payload(){return model?.payload()||{};},
    /** 草稿支持刷新恢复笔记和选格。 */
    snapshot(){return model?.snapshot()||{};},
    /** 换号时清空全部棋盘状态。 */
    clear(){model=null;render();},
    /** 卸载解绑本页面监听，避免跨页重复响应。 */
    destroy(){model=null;host.removeEventListener('click',click);host.removeEventListener('keydown',keydown);window.removeEventListener('resize',fit);window.visualViewport?.removeEventListener('resize',fit);render();},
  };
}
