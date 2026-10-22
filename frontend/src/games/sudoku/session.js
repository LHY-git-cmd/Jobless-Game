/** 数独正式会话：账号草稿、版本化时钟、教学输入及可恢复的幂等终盘提交。 */
import { api } from '../../features/progression/client.js';
import { createJourneyStore } from '../../features/progression/journey-store.js';
import { createSudoku,selectSudokuCell,setSudokuValue,toggleSudokuNote,normalizeSudokuNotes,checkSudoku } from './rules.js';

/** request、storage及now可注入；服务端负责时间和奖励，本地只保存未提交的布局。 */
export function createSudokuSession({uid,storage,request=api,now=Date.now,onChange=()=>{},onReward=()=>{}}={}){
  const state={levels:[],progress:[],enabled:false,selected:null,attempt:null,grid:null,result:null,pending:false,busy:false,paused:false,clockBusy:false,message:''};
  const store=createJourneyStore(storage,`sudoku:${uid}`,message=>{state.message=message;});
  if(!storage&&uid)state.message='本地存储不可用，刷新可能丢失未提交的答案与笔记。';
  const reasons=new Set();
  let dead=false,anchor=now(),frozen=null,clockQueue=Promise.resolve(),operationDone=Promise.resolve(),pendingClock=null;

  /** 销毁后所有订阅与异步写入均失效。 */
  function publish(){if(!dead)onChange(state);}
  /** 显示时间以最近服务器活动时长为锚，暂停或待结算时冻结。 */
  function elapsed(){
    if(!state.attempt)return 0;
    if(state.result)return state.result.duration_ms;
    if(frozen!==null)return frozen;
    return (state.attempt.timing?.elapsed_ms||0)+(state.attempt.timing?.paused||state.attempt.status!=='active'?0:Math.max(0,now()-anchor));
  }
  /** 保存只包含玩家布局与模式，不保存本地伪造的奖励。 */
  function save(){if(!dead&&state.attempt&&state.grid)store.save(state.attempt,{values:state.grid.values,notes:state.grid.notes,notesMode:state.grid.notesMode,selected:state.grid.selected});}
  /** 普通操作等待在途时钟，离页暂停则由独立队列发送keepalive。 */
  async function perform(work){
    if(dead||state.busy)return;
    const wait=clockQueue;let finish;operationDone=new Promise(resolve=>finish=resolve);
    state.busy=true;publish();
    try{await wait;if(!dead)return await work();}
    finally{finish();if(!dead){state.busy=false;publish();}}
  }
  /** 用服务器给定盘重建，忽略草稿中的题目数字和无效值。 */
  function adopt(attempt){
    if(dead)return;
    state.attempt=attempt;state.selected=attempt.level_id;state.result=null;
    const saved=store.load(attempt),draft=saved?.draft;
    const grid=createSudoku(attempt.puzzle),size=grid.size;
    if(attempt.puzzle.tutorial){
      grid.values=[...attempt.board.tutorial_values];grid.notes=[...attempt.board.tutorial_notes];
    }else{
      grid.values=grid.givens.map((given,i)=>given||((Number.isInteger(draft?.values?.[i])&&draft.values[i]>=0&&draft.values[i]<=size)?draft.values[i]:0));
      grid.notes=draft?.notes||grid.notes;
    }
    grid.notesMode=draft?.notesMode===true;
    if(Number.isInteger(draft?.selected)&&draft.selected>=0&&draft.selected<grid.values.length)grid.selected=draft.selected;
    normalizeSudokuNotes(grid);state.grid=grid;state.pending=Boolean(saved?.pending);anchor=now();
    state.paused=reasons.size>0||Boolean(attempt.timing?.paused)||state.clockBusy;
    frozen=state.pending||state.paused?attempt.timing?.elapsed_ms||0:null;
    const progress=state.progress.find(v=>v.level_id===attempt.level_id);
    if(progress)progress.current_attempt=attempt.status==='active'?attempt.links.self:null;
    save();publish();
  }
  /** 时钟比较交换防止旧标签页迟到暂停；失败保留原命令供原键重试。 */
  async function writeClock(paused){
    const attempt=state.attempt;if(!attempt||attempt.status!=='active'||state.pending)return;
    for(let retry=0;retry<3;retry++){
      const command=pendingClock?.rid===attempt.attempt_id?pendingClock:{rid:attempt.attempt_id,paused,revision:state.attempt.timing.revision,command_id:crypto.randomUUID()};
      pendingClock=command;
      try{
        const {rid,...body}=command;
        const response=await request(attempt.links.self+'/clock',{method:'PUT',body,keepalive:true});
        if(dead)return;pendingClock=null;
        // 时钟响应只替换权威计时，不重建玩家正在编辑的草稿。
        state.attempt={...state.attempt,...response.data};anchor=now();
        if(command.paused!==paused){retry--;continue;}
        return;
      }catch(error){
        if(dead)return;
        if(error.code!=='clock_conflict')throw error;
        const response=await request(attempt.links.self);if(dead)return;
        state.attempt={...state.attempt,...response.data};anchor=now();pendingClock=null;
      }
    }
    throw new Error('计时状态变化，请重试继续游戏。');
  }
  /** 成功快照同时更新本地卡片与顶部账号；恢复旧结果不重播奖励动画。 */
  function confirmed(result,restored=false){
    if(dead)return;
    state.result=result;state.pending=false;state.attempt.status='completed';state.grid.complete=true;
    frozen=result.duration_ms;store.clearPending(state.attempt);
    let progress=state.progress.find(v=>v.level_id===state.attempt.level_id);
    if(!progress){progress={level_id:state.attempt.level_id};state.progress.push(progress);}
    Object.assign(progress,{best_stars:result.best_stars,best_duration_ms:result.duration_ms,current_attempt:null});
    save();onReward(result,{restored});publish();
  }
  /** 待提交负载一经保存便固定，网络重试不会重建尝试或改变终盘。 */
  async function settle(){
    if(dead||state.result)return;
    const attempt=state.attempt;
    const payload=store.load(attempt)?.pending||{values:[...state.grid.values]};
    frozen=elapsed();state.pending=true;state.grid.complete=true;save();store.freeze(attempt,payload);publish();
    const response=await request(attempt.links.completion,{method:'PUT',body:payload});
    if(!dead)confirmed(response.data);
  }
  /** 教学末步与离页暂停可能交错；重试先同步运行状态，避免终盘卡在暂停状态。 */
  async function resumeSubmission(){
    state.pending=false;
    try{await writeClock(false);}finally{if(!dead)state.pending=true;}
    if(!dead)await settle();
  }
  /** 先GET核验资源；服务器已完成则读原结果，否则继续相同终盘。 */
  async function restore(path){
    const response=await request(path);if(dead)return;
    adopt(response.data);
    if(response.data.status==='completed'){
      const result=await request(response.data.links.completion);if(!dead)confirmed(result.data,true);return;
    }
    if(response.data.status!=='active')return;
    if(state.pending){
      // 确保失败的旧暂停不会使终盘永久无法重试，恢复时先同步运行状态。
      await resumeSubmission();return;
    }
    await writeClock(reasons.size>0);if(dead)return;
    state.paused=reasons.size>0||Boolean(state.attempt.timing?.paused);frozen=state.paused?state.attempt.timing.elapsed_ms:null;
  }
  /** 创建响应丢失后沿用原UUID，已有活跃局通过服务器链接续玩。 */
  async function begin(){
    const level=state.levels.find(v=>v.level_id===state.selected);if(!level)throw new Error('请选择题目。');
    let response;
    try{response=await request('attempts',{method:'POST',body:{level_id:level.level_id,level_version:level.level_version,mode:'campaign'},headers:{'Idempotency-Key':store.startKey(level.level_id)}});}
    catch(error){
      if(dead)return;
      const active=error.code==='attempt_active'&&error.problem?.links?.attempt;
      if(!active)throw error;
      await restore(active);if(!dead)store.clearStart(level.level_id);return;
    }
    if(dead)return;
    await restore(response.data.links.self);if(!dead)store.clearStart(level.level_id);
  }
  /** 只有活动、已同步且未提交的棋盘允许修改。 */
  function editable(){return !dead&&!state.busy&&!state.paused&&!state.pending&&state.attempt?.status==='active';}

  return {
    get state(){return state;},
    elapsed,
    /** 上局引用只用于定位GET，不能证明账号拥有正式成绩。 */
    hasSaved(id){return Boolean(store.reference(id));},
    /** 目录可公开浏览；只为当前账号加载独立的续玩引用。 */
    async load(){return perform(async()=>{
      const [levels,features]=await Promise.all([request('levels?game_id=sudoku'),request('features')]);if(dead)return;
      state.levels=levels.data.items;state.enabled=features.data.progression;
      state.selected=state.levels.find(v=>v.difficulty==='easy')?.level_id||state.levels[0]?.level_id;
      if(uid&&state.enabled){
        const progress=await request('me/level-progress?game_id=sudoku&limit=50');if(dead)return;state.progress=progress.data.items;
        if(state.levels.some(v=>v.level_id===store.selected)){
          state.selected=store.selected;
          const reference=state.progress.find(v=>v.level_id===state.selected)?.current_attempt||store.reference(state.selected);
          if(reference)try{await restore(reference.startsWith('/api/')?reference:`/api/v1/attempts/${reference}`);}
          catch(error){if(![404,410].includes(error.status))throw error;if(!dead){state.attempt=null;state.grid=null;state.message='上局已结束保存期限，请重新开始。';}}
        }
      }
    });},
    /** 切题不创建局，不触碰其他题的草稿。 */
    select(id){if(state.busy||!state.levels.some(v=>v.level_id===id))return;state.selected=id;publish();},
    /** 已有局先恢复；仅显式开始创建新尝试。 */
    async open(){return perform(async()=>{
      if(!uid)throw new Error('请先登录。');if(!state.enabled)throw new Error('数独暂未开放。');
      const reference=state.progress.find(v=>v.level_id===state.selected)?.current_attempt||store.reference(state.selected);
      if(reference){try{
        await restore(reference.startsWith('/api/')?reference:`/api/v1/attempts/${reference}`);
        if(dead||['active','completed'].includes(state.attempt.status))return;
      }catch(error){if(![404,410].includes(error.status))throw error;}}
      await begin();
    });},
    /** 给定数也可选中观察同行列宫，输入仍保护给定数。 */
    choose(index){if(!editable()||!selectSudokuCell(state.grid,index))return;save();publish();},
    /** 手动笔记模式与答案输入共用数字键，不自动计算候选数。 */
    toggleNotes(){if(!editable())return;state.grid.notesMode=!state.grid.notesMode;save();publish();},
    /** 输入先持久化，完成时立即提交；教学输入必须由服务器逐步核验。 */
    async input(value){
      if(!editable())return;
      return perform(async()=>{
        if(dead||state.paused||state.pending)return;
        const grid=state.grid,index=grid.selected,noting=grid.notesMode&&value!==0;
        if(index===null||grid.givens[index]||!Number.isInteger(value)||value<0||value>grid.size)return;
        if(state.attempt.puzzle.tutorial){
          const step=state.attempt.board.tutorial_step;
          const steps=[['row',1,2,false],['erase',1,0,false],['note',1,2,true],['column',6,1,false],['box',1,2,false]];
          const expected=steps[step];
          if(!expected||index!==expected[1]||value!==expected[2]||(value!==0&&noting!==expected[3])){state.message='请按教学提示选格，并切换到对应的填数或笔记模式。';return;}
          const response=await request(state.attempt.links.self+'/sudoku-tutorial-actions/'+expected[0],{method:'PUT',body:{index,value}});
          if(dead)return;state.attempt=response.data;
          grid.values=[...response.data.board.tutorial_values];grid.notes=[...response.data.board.tutorial_notes];
        }else if(!(noting?toggleSudokuNote(grid,value):setSudokuValue(grid,value)))return;
        state.message='';save();publish();
        if(grid.values.every(v=>v>0)&&checkSudoku(grid).status!=='conflict')await settle();
      });
    },
    /** 检查只报告重复和空格，不提供正确数字。 */
    check(){if(!editable())return;const result=checkSudoku(state.grid);state.message=result.status==='conflict'?'存在重复数字，请检查标红格子。':`没有重复数字，还剩 ${result.blanks} 个空格。`;publish();},
    /** 保存失败只重放已冻结的终盘。 */
    async complete(){return perform(async()=>{if(state.pending&&!state.result)await resumeSubmission();});},
    /** 调用方先确认重开，条件放弃避免覆盖其他页面刚完成的棋局。 */
    async restart(){return perform(async()=>{
      const attempt=state.attempt;
      if(attempt){const latest=await request(attempt.links.self);if(dead)return;
        if(latest.data.status==='active')await request(attempt.links.self,{method:'PATCH',body:{status:'abandoned'},headers:{'If-Match':latest.etag}});
        if(dead)return;state.selected=attempt.level_id;store.clearStart(attempt.level_id);
      }
      state.pending=false;state.result=null;await begin();
    });},
    /** 多原因暂停串行写入，失败保留冻结，可用原命令重试；离页不等待其他操作。 */
    async setPaused(reason,value,{sync=true,immediate=false}={}){
      if(dead)return;
      const before=reasons.size>0,time=elapsed();if(value)reasons.add(reason);else reasons.delete(reason);
      const paused=reasons.size>0;
      if(!sync||!state.attempt||state.attempt.status!=='active'||state.pending)return;
      if(before===paused&&state.paused===paused&&!pendingClock&&!state.clockBusy)return;
      frozen=time;state.paused=true;state.clockBusy=true;publish();
      const operation=operationDone;
      const work=async()=>{
        if(!immediate)await operation;if(dead)return;
        try{
          await writeClock(reasons.size>0);if(dead)return;
          state.clockBusy=false;state.paused=reasons.size>0||Boolean(state.attempt.timing?.paused);frozen=state.paused?state.attempt.timing.elapsed_ms:null;
        }catch(error){if(!dead){state.clockBusy=false;state.paused=true;}throw error;}
        finally{publish();}
      };
      const next=immediate?work():clockQueue.catch(()=>{}).then(work);clockQueue=next.catch(()=>{});return next;
    },
    /** 退出后旧响应不可写回新账号，草稿由既有存储保留。 */
    destroy(){dead=true;state.attempt=null;state.grid=null;state.result=null;},
  };
}
