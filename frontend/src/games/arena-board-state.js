/** 竞技输入状态：复用闯关照明与数独规则，扫雷揭格只经服务器。 */
import { createAkari, toggleBulb, inspectAkari } from './akari/rules.js';
import { createSudoku, setSudokuValue, toggleSudokuNote, normalizeSudokuNotes } from './sudoku/rules.js';

/** 草稿仅包含本人输入；onComplete是提交提示，实际胜负由服务器确认。 */
export function createArenaBoardState(game,puzzle,saved={},authority=null,{onChange=()=>{},onReveal=()=>{},onComplete=()=>{}}={}) {
  let disabled=false;
  const count=puzzle.rows*puzzle.cols;
  const validIndex=index=>Number.isInteger(index)&&index>=0&&index<count;
  const state={game,puzzle,selected:validIndex(saved.selected)?saved.selected:null,flags:[...new Set((Array.isArray(saved.flags)?saved.flags:[]).filter(validIndex))],
    mine:Array.isArray(authority?.revealed)?authority:{revealed:[],outcome:'active'},grid:null,akari:null};
  const history=[];
  if(game==='sudoku') {
    state.grid=createSudoku(puzzle);
    if(Array.isArray(saved.values)&&saved.values.length===count)state.grid.values=saved.values.map((v,i)=>state.grid.givens[i]||(Number.isInteger(v)&&v>=0&&v<=puzzle.rows?v:0));
    state.grid.notes=Array.isArray(saved.notes)?[...saved.notes]:[];state.grid.notesMode=saved.notesMode===true;state.grid.selected=state.selected;
    normalizeSudokuNotes(state.grid);
    // 与闯关保持一致：最多100步，刷新保留实际编辑历史，给定数不接受草稿覆盖。
    for(const item of (Array.isArray(saved.history)?saved.history:[]).slice(-100)){
      if(!Array.isArray(item?.values)||item.values.length!==count||!Array.isArray(item.notes)||item.notes.length!==count)continue;
      const previous=createSudoku(puzzle);
      previous.values=item.values.map((v,i)=>previous.givens[i]||(Number.isInteger(v)&&v>=0&&v<=puzzle.rows?v:0));
      previous.notes=[...item.notes];previous.notesMode=item.notesMode===true;previous.selected=validIndex(item.selected)?item.selected:null;normalizeSudokuNotes(previous);
      history.push({values:previous.values,notes:previous.notes,notesMode:previous.notesMode,selected:previous.selected});
    }
  }
  if(game==='akari') {
    state.akari=createAkari(puzzle);
    state.akari.bulbs=new Set((Array.isArray(saved.bulbs)?saved.bulbs:[]).filter(i=>validIndex(i)&&puzzle.map.join('')[i]==='.'));
  }
  /** 快照排除服务器雷图与答案，给定数优先于存档。 */
  function snapshot(){return game==='sudoku'?{...gridSnapshot(),history:structuredClone(history)}:game==='akari'?{bulbs:[...state.akari.bulbs]}:{flags:[...state.flags],selected:state.selected};}
  /** 撤回条目只保存单次编辑前状态，避免历史递归嵌套。 */
  function gridSnapshot(){return {values:[...state.grid.values],notes:[...state.grid.notes],notesMode:state.grid.notesMode,selected:state.grid.selected};}
  /** 回调保存草稿，合法终盘才提示提交，笔记不触发完成。 */
  function changed(check=false){onChange(snapshot());if(check&&((game==='akari'&&inspectAkari(state.akari).complete)||(game==='sudoku'&&state.grid.complete)))onComplete();}
  /** 按格选择或开关灯泡，扫雷点格不会直接揭开。 */
  function choose(index){
    if(disabled||!validIndex(index))return;
    state.selected=index;
    if(game==='sudoku')state.grid.selected=index;
    if(game==='akari'){state.akari.complete=false;if(!toggleBulb(state.akari,index))return;}
    changed(game==='akari');
  }
  /** 记录有限撤回栈，避免长局操作无限占用内存。 */
  function remember(){history.push(gridSnapshot());if(history.length>100)history.shift();}
  /** 数字键和触屏键盘使用同一个输入规则，固定题目数字不能更改。 */
  function digit(value){
    const grid=state.grid;
    if(disabled||!grid||grid.selected===null||grid.givens[grid.selected]||!Number.isInteger(value)||value<0||value>grid.size)return;
    remember();grid.complete=false;
    if(grid.notesMode&&value)toggleSudokuNote(grid,value);else setSudokuValue(grid,value);
    changed(true);
  }
  /** 笔记不修改正式答案。 */
  function toggleNotes(){if(disabled||!state.grid)return;state.grid.notesMode=!state.grid.notesMode;changed();}
  /** 撤回本地输入，不撤回服务器已接受的终盘。 */
  function undo(){if(disabled||!state.grid||!history.length)return;const last=history.pop();Object.assign(state.grid,{values:last.values,notes:last.notes,notesMode:last.notesMode,selected:last.selected,complete:false});changed();}
  /** 已揭格不能标记，和闯关一样需先选择未揭格。 */
  function mark(){const i=state.selected;if(disabled||game!=='mine'||i===null||state.mine.outcome!=='active'||state.mine.revealed.some(c=>c.index===i))return;state.flags=state.flags.includes(i)?state.flags.filter(v=>v!==i):[...state.flags,i];changed();}
  /** 只发索引，不在本地推断隐藏地雷或判胜。 */
  function reveal(){const i=state.selected;if(disabled||game!=='mine'||i===null||state.mine.outcome!=='active'||state.flags.includes(i)||state.mine.revealed.some(c=>c.index===i))return;onReveal(i);}
  return Object.assign(state,{choose,digit,toggleNotes,undo,mark,reveal,snapshot,
    /** 冻结在途提交，避免重试时答案变化。 */
    setDisabled(value){disabled=value;state.disabled=value;},
    /** 显示及控制器读取相同的输入锁。 */
    disabled:false,
    /** 撤回按钮状态来自真实操作栈。 */
    canUndo(){return history.length>0;},
    /** 服务端接受的字段不包含笔记、选择或标记。 */
    payload(){return game==='akari'?{bulbs:[...state.akari.bulbs]}:game==='sudoku'?{values:[...state.grid.values]}:{};},
    /** 揭格响应覆盖本人可见棋盘，旗标保留在本地。 */
    setMine(value){if(Array.isArray(value?.revealed))state.mine=value;},
  });
}
