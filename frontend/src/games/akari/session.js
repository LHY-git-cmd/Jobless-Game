/** 照明正式会话：变尺寸题目、账号草稿、权威时钟和可恢复的幂等结算。 */
import { api } from '../../features/progression/client.js';
import { createJourneyStore } from '../../features/progression/journey-store.js';
import { publishAttemptEnergy,restartAttempt } from '../../features/progression/attempt-energy.js';
import { createAkari, toggleBulb } from './rules.js';
import { akariTutorialSteps } from './tutorial.js';

/** request、storage、now可注入；客户端不决定奖励或正式用时。 */
export function createAkariSession({uid,storage,request=api,now=Date.now,onChange=()=>{},onReward=()=>{}}={}) {
  const state={levels:[],progress:[],enabled:false,selected:null,attempt:null,board:null,result:null,busy:false,pending:false,paused:false,message:'',tutorialStep:0};
  const store=createJourneyStore(storage,`akari:${uid}`,message=>{state.message=message;});
  const reasons=new Set();
  const outdatedCompleted=new Set();
  let dead=false,anchor=now(),frozen=null,clockQueue=Promise.resolve(),operationDone=Promise.resolve(),pendingClock=null;
  if(!storage&&uid)state.message='本地存储不可用，刷新可能丢失未提交的灯泡布局。';

  /** 销毁后的异步响应不能触发新账号绘制。 */
  function publish(){if(!dead)onChange(state);}
  /** 本地时钟只显示服务器锚点之后的活动时间。 */
  function elapsed(){
    if(state.result)return state.result.duration_ms;
    if(frozen!==null)return frozen;
    return (state.attempt?.timing?.elapsed_ms||0)+(state.attempt?.status==='active'&&!state.attempt.timing?.paused?Math.max(0,now()-anchor):0);
  }
  /** 草稿与教学进度绑定同一账号、尝试、版本及题目摘要。 */
  function save(){if(!dead&&state.attempt&&state.board)store.save(state.attempt,{bulbs:[...state.board.bulbs],tutorialStep:state.tutorialStep});}
  /** 写操作等待先前时钟同步；失败释放busy，保留可重试的负载。 */
  async function perform(work){
    if(dead||state.busy)return;
    const wait=clockQueue;let finish;operationDone=new Promise(resolve=>finish=resolve);state.busy=true;publish();
    try{await wait;if(!dead)return await work();}
    finally{finish();if(!dead){state.busy=false;publish();}}
  }
  /** 只恢复正式地图中的合法白格坐标，不相信草稿中的规则或奖励。 */
  function adopt(attempt){
    if(dead)return;
    publishAttemptEnergy(uid,attempt);
    const saved=store.load(attempt),cells=attempt.puzzle.map.join('');
    state.attempt=attempt;state.selected=attempt.level_id;state.result=null;state.board=createAkari(attempt.puzzle);
    state.board.bulbs=new Set((Array.isArray(saved?.draft?.bulbs)?saved.draft.bulbs:[]).filter(i=>Number.isInteger(i)&&i>=0&&cells[i]==='.'));
    const lastStep=Math.max(0,akariTutorialSteps(attempt.puzzle).length-1);
    state.tutorialStep=Math.min(lastStep,Math.max(0,Math.trunc(Number(saved?.draft?.tutorialStep)||0)));
    state.pending=Boolean(saved?.pending);anchor=now();
    state.paused=reasons.size>0||Boolean(attempt.timing?.paused);
    frozen=state.pending||state.paused?attempt.timing?.elapsed_ms||0:null;
    const progress=state.progress.find(v=>v.level_id===attempt.level_id);
    if(progress)progress.current_attempt=attempt.status==='active'?attempt.links.self:null;
    save();publish();
  }
  /** 时钟重试复用命令；冲突先GET修订号，不接受本地累计时长。 */
  async function writeClock(paused){
    const attempt=state.attempt;if(!attempt||attempt.status!=='active')return;
    for(let retry=0;retry<3;retry++){
      const command=pendingClock?.rid===attempt.attempt_id?pendingClock:{rid:attempt.attempt_id,paused,revision:state.attempt.timing.revision,command_id:crypto.randomUUID()};
      pendingClock=command;
      try{
        const {rid,...body}=command;
        const response=await request(attempt.links.self+'/clock',{method:'PUT',body,keepalive:true});if(dead)return;
        state.attempt={...state.attempt,...response.data};anchor=now();pendingClock=null;
        if(command.paused!==paused){retry--;continue;}
        return;
      }catch(error){
        if(dead)return;
        if(error.code!=='clock_conflict')throw error;
        const response=await request(attempt.links.self);if(dead)return;
        state.attempt={...state.attempt,...response.data};anchor=now();pendingClock=null;
      }
    }
    throw new Error('计时状态已变化，请重试。');
  }
  /** 只有成功快照更新正式成绩；恢复已有结果不重播奖励。 */
  function confirmed(result,restored=false){
    if(dead)return;
    publishAttemptEnergy(uid,result);
    state.result=result;state.pending=false;state.attempt.status='completed';state.board.complete=true;frozen=result.duration_ms;
    store.clearPending(state.attempt);
    let progress=state.progress.find(v=>v.level_id===state.attempt.level_id);
    if(!progress){progress={level_id:state.attempt.level_id};state.progress.push(progress);}
    Object.assign(progress,{best_stars:result.best_stars,current_attempt:null});
    save();onReward(result,{restored});publish();
  }
  /** 完整终盘先落盘再PUT，断网及刷新始终重放同一负载。 */
  async function settle(){
    if(dead||state.result)return;
    const attempt=state.attempt,payload=store.load(attempt)?.pending||{bulbs:[...state.board.bulbs]};
    frozen=elapsed();state.pending=true;save();store.freeze(attempt,payload);publish();
    const response=await request(attempt.links.completion,{method:'PUT',body:payload});if(!dead)confirmed(response.data);
  }
  /** 恢复前核验资源及已完成快照，终盘重试前解除旧暂停。 */
  async function restore(path){
    const response=await request(path);if(dead)return;adopt(response.data);
    if(response.data.status==='completed'){
      const result=await request(response.data.links.completion);if(dead)return;confirmed(result.data,true);
      if(state.levels.find(v=>v.level_id===response.data.level_id)?.level_version!==response.data.level_version){
        // 已完成旧盘保留正式成绩，新的选关入口应开始最新版而不是反复显示旧尺寸。
        outdatedCompleted.add(response.data.level_id);state.attempt=null;state.board=null;state.result=null;state.pending=false;frozen=null;
        state.message='本关已更新，可以开始新版棋盘；旧成绩已保留。';
      }
      return;
    }
    if(response.data.status!=='active')return;
    if(state.pending){await writeClock(false);if(!dead)await settle();return;}
    await writeClock(reasons.size>0);if(dead)return;
    state.paused=reasons.size>0||Boolean(state.attempt.timing?.paused);frozen=state.paused?state.attempt.timing.elapsed_ms:null;
    if(state.levels.find(v=>v.level_id===state.attempt.level_id)?.level_version!==state.attempt.level_version){
      state.message=`正在继续旧版${state.attempt.puzzle.rows}×${state.attempt.puzzle.cols}棋局，重新开始将使用新版棋盘。`;
    }
  }
  /** 创建响应丢失使用同一UUID；服务器已有本关时转为恢复。 */
  async function begin(){
    const level=state.levels.find(v=>v.level_id===state.selected);if(!level)throw new Error('请选择关卡。');
    let response;
    try{response=await request('attempts',{method:'POST',body:{level_id:level.level_id,level_version:level.level_version,mode:'campaign'},headers:{'Idempotency-Key':store.startKey(level.level_id)}});}
    catch(error){
      if(dead)return;
      const active=error.code==='attempt_active'&&error.problem?.links?.attempt;if(!active)throw error;
      await restore(active);if(!dead)store.clearStart(level.level_id);return;
    }
    if(dead)return;
    await restore(response.data.links.self);if(!dead){store.clearStart(level.level_id);outdatedCompleted.delete(level.level_id);state.message='';}
  }
  /** 统一把进度引用和本地引用转换为核验地址。 */
  function reference(){return state.progress.find(v=>v.level_id===state.selected)?.current_attempt||store.reference(state.selected);}
  /** 仅允许活动且时钟同步完成的棋盘编辑。 */
  function editable(){return !dead&&!state.busy&&!state.paused&&!state.pending&&state.attempt?.status==='active';}

  return {
    get state(){return state;},elapsed,
    /** 卡片只把草稿当作导航提示。 */
    hasSaved(id){return Boolean(store.reference(id))&&!outdatedCompleted.has(id);},
    /** 游客可读目录，登录后读取该账号进度并核验上局引用。 */
    async load(){return perform(async()=>{
      const [levels,features]=await Promise.all([request('levels?game_id=akari'),request('features')]);if(dead)return;
      state.levels=levels.data.items;state.enabled=features.data.progression;
      state.selected=state.levels.find(v=>v.level_id===store.selected)?.level_id||state.levels[0]?.level_id;
      if(uid&&state.enabled){
        const progress=await request('me/level-progress?game_id=akari&limit=50');if(dead)return;state.progress=progress.data.items;
        if(store.selected&&reference())try{const ref=reference();await restore(ref.startsWith('/api/')?ref:`/api/v1/attempts/${ref}`);}
        catch(error){if(![404,410].includes(error.status))throw error;if(!dead){state.attempt=null;state.board=null;state.message='上局已到保存期限，请重新开始。';}}
      }
    });},
    /** 切换所选关卡不创建正式尝试。 */
    select(id){if(!state.busy&&state.levels.some(v=>v.level_id===id)){state.selected=id;publish();}},
    /** 显式开始优先恢复，过期或已放弃才创建新局。 */
    async open(){return perform(async()=>{
      if(!uid)throw new Error('请先登录。');if(!state.enabled)throw new Error('照明暂未开放。');
      const ref=reference();
      if(ref)try{await restore(ref.startsWith('/api/')?ref:`/api/v1/attempts/${ref}`);if(dead||['active','completed'].includes(state.attempt?.status))return;}
      catch(error){if(![404,410].includes(error.status))throw error;}
      await begin();
    });},
    /** 放灯/撤灯立即保存；全亮、无互照且数字满足才自动提交。 */
    async toggle(index){
      if(!editable())return;
      return perform(async()=>{
        if(dead||state.paused||state.pending)return;
        const removing=state.board.bulbs.has(index);
        const puzzle=state.attempt.puzzle,steps=akariTutorialSteps(puzzle),step=steps[state.tutorialStep];
        if(puzzle.tutorial_steps&&Number.isInteger(step?.index)&&(step.index!==index||step.bulb===removing)){
          state.message='请按当前引导点击高亮格，完成这一步后再尝试其他位置。';publish();return;
        }
        if(!toggleBulb(state.board,index))return;
        if(puzzle.tutorial){
          if(puzzle.tutorial_steps){
            if(Number.isInteger(step?.index))state.tutorialStep=Math.min(steps.length-1,state.tutorialStep+1);
          }else{
            if(state.tutorialStep===0&&!removing)state.tutorialStep=1;
            else if(state.tutorialStep===1&&removing)state.tutorialStep=2;
          }
          // 入门必须先练习撤灯，全部约束仍由正式规则决定。
          if(state.tutorialStep<steps.length-1)state.board.complete=false;
        }
        state.message='';save();publish();if(state.board.complete)await settle();
      });
    },
    /** 终盘失败只重试当前尝试，不另建局或重算负载。 */
    async complete(){return perform(async()=>{if(state.pending&&!state.result){await writeClock(false);if(!dead)await settle();}});},
    /** 调用方确认后只放弃当前关；使用最新ETag防止覆盖其他标签页结果。 */
    async restart(){return perform(async()=>{
      const attempt=state.attempt;
      if(attempt){
        const restarted=await restartAttempt({attempt,store,request});if(dead)return;
        pendingClock=null;await restore(restarted.response.data.links.self);if(!dead)restarted.clear();return;
      }
      state.pending=false;state.result=null;pendingClock=null;await begin();
    });},
    /** 多个暂停原因全部解除才恢复；页面离开用keepalive尽力同步。 */
    async setPaused(reason,value,{sync=true,immediate=false}={}){
      if(dead)return;
      const before=reasons.size>0,time=elapsed();if(value)reasons.add(reason);else reasons.delete(reason);
      const paused=reasons.size>0;
      if(!sync||!state.attempt||state.attempt.status!=='active'||state.pending)return;
      if(before===paused&&state.paused===paused&&!pendingClock)return;
      frozen=time;state.paused=true;publish();const operation=operationDone;
      const work=async()=>{
        if(!immediate)await operation;if(dead)return;
        try{await writeClock(reasons.size>0);if(dead)return;state.paused=reasons.size>0||Boolean(state.attempt.timing.paused);frozen=state.paused?state.attempt.timing.elapsed_ms:null;}
        catch(error){if(!dead)state.paused=true;throw error;}
        finally{publish();}
      };
      const next=immediate?work():clockQueue.catch(()=>{}).then(work);clockQueue=next.catch(()=>{});return next;
    },
    /** 身份变更立刻移除旧账号内存，草稿仍按账号隔离保留。 */
    destroy(){dead=true;state.attempt=null;state.board=null;state.result=null;},
  };
}
