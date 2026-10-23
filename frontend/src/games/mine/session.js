/** 正式扫雷会话：显式开始、权威揭格、账号草稿、教学及可重试结算。 */
import { api } from '../../features/progression/client.js';
import { createJourneyStore } from '../../features/progression/journey-store.js';
import { publishAttemptEnergy,restartAttempt } from '../../features/progression/attempt-energy.js';
import { abandonAttempt } from '../../features/progression/attempt-exit.js';

/** request与时钟可注入测试；本地仅保存选格/旗标和正式尝试的引用。 */
export function createMineSession({uid,storage,request=api,onChange=()=>{},onReward=()=>{},now=Date.now}={}) {
  let epoch=0, dead=false, offset=0;
  let anchor=now(),clockQueue=Promise.resolve(),operationDone=Promise.resolve(),frozen=null,pendingClock=null;
  const pauseReasons=new Set();
  const state={levels:[],progress:[],enabled:false,selected:null,attempt:null,result:null,flags:[],cell:null,busy:false,paused:false,clockBusy:false,message:''};
  const store=createJourneyStore(storage,uid,message=>{state.message=message;});
  /** 渲染订阅只接收当前会话，销毁后的响应不可通知页面。 */
  function publish(){if(!dead) onChange(state);}
  /** 串行写操作并统一恢复按钮；错误交给界面显示可重试状态。 */
  async function perform(work) {
    if(dead||state.busy) return;
    const clockWait=clockQueue;
    let done;operationDone=new Promise(resolve=>{done=resolve;});
    const stamp=epoch;state.busy=true;publish();
    try{await clockWait;return await work(()=>!dead&&stamp===epoch);}
    finally {done();if(!dead&&stamp===epoch){state.busy=false;publish();}}
  }
  /** 采用服务器棋盘并恢复同一次尝试的草稿，旗标永远不替代权威揭格。 */
  function adopt(value) {
    publishAttemptEnergy(uid,value);
    state.attempt=value;state.selected=value.level_id;state.result=null;
    const progress=state.progress.find(v=>v.level_id===value.level_id);
    if(progress)progress.current_attempt=value.status==='active'?value.links.self:null;
    const saved=store.load(value)?.draft;
    const revealed=new Set(value.board.revealed.map(v=>v.index));
    const count=value.puzzle.rows*value.puzzle.cols;
    state.flags=(saved?.flags||[]).filter(v=>Number.isInteger(v)&&v>=0&&v<count&&!revealed.has(v));
    if(value.puzzle.tutorial&&value.board.tutorial_step>=3&&!state.flags.includes(6)) state.flags.push(6);
    state.cell=Number.isInteger(saved?.selected)&&saved.selected>=0&&saved.selected<count?saved.selected:null;
    offset=Date.parse(value.server_now)-now();
    if(!Number.isFinite(offset)) offset=0;
    anchor=now();
    state.paused=pauseReasons.size>0||state.clockBusy||Boolean(value.timing?.paused);
    frozen=state.paused?(value.timing?.elapsed_ms??Math.max(0,(Date.parse(value.ended_at||'')||now()+offset)-Date.parse(value.started_at))):null;
    save();publish();
  }
  /** 当前显示从服务端活动时长递增；暂停意图立即冻结，不等待网络往返。 */
  function elapsed(){
    const attempt=state.attempt;if(!attempt)return 0;
    if(frozen!==null)return frozen;
    if(attempt.timing)return attempt.timing.elapsed_ms+(attempt.ended_at||attempt.timing.paused?0:Math.max(0,now()-anchor));
    return Math.max(0,(Date.parse(attempt.ended_at||'')||now()+offset)-Date.parse(attempt.started_at));
  }
  /** 修订冲突只读取最新权威快照重试，不允许旧离页请求覆盖新会话。 */
  async function writeClock(paused,current){
    const attempt=state.attempt;
    if(!attempt||attempt.status!=='active'||attempt.board.outcome!=='active')return;
    for(let retry=0;retry<3;retry++){
      const command=pendingClock?.rid===attempt.attempt_id?pendingClock:{rid:attempt.attempt_id,paused,revision:state.attempt.timing?.revision||0,command_id:crypto.randomUUID()};
      pendingClock=command;
      try{
        const {rid,...body}=command;
        const response=await request(attempt.links.self+'/clock',{method:'PUT',body,keepalive:true});
        if(!current())return;
        pendingClock=null;adopt(response.data);
        if(command.paused!==paused){retry--;continue;}
        return;
      }catch(error){
        if(!current())return;
        if(error.code!=='clock_conflict')throw error;
        const latest=await request(attempt.links.self);if(!current())return;
        pendingClock=null;adopt(latest.data);
      }
    }
    throw new Error('计时同步失败，请重试继续游戏。');
  }
  /** 保存失败仍可继续操作，正式棋盘可由账号服务端恢复。 */
  function save(){if(state.attempt)store.save(state.attempt,{flags:state.flags,selected:state.cell});}
  /** 完成只提交空体；终盘或请求失败后都保留同一尝试用于重试。 */
  async function settle(current) {
    const attempt=state.attempt;
    store.freeze(attempt,{});
    const response=await request(attempt.links.completion,{method:'PUT',body:{}});
    if(!current())return;
    state.result=response.data;state.attempt.status='completed';store.clearPending(attempt);
    publishAttemptEnergy(uid,response.data);
    const progress=state.progress.find(v=>v.level_id===attempt.level_id);
    if(progress){progress.best_stars=response.data.best_stars;progress.current_attempt=null;}
    onReward(response.data);publish();
  }
  /** GET始终先于恢复，不把本地引用当作服务端事实。 */
  async function restore(path,current) {
    const response=await request(path);
    if(!current())return;
    adopt(response.data);
    await writeClock(pauseReasons.size>0,current);
    if(!current())return;
    if(response.data.status==='completed') {
      const result=await request(response.data.links.completion);
      if(current()){state.result=result.data;publish();}
    } else if(response.data.board.outcome==='won') await settle(current);
  }
  /** 开始POST重试保留原键；其原始响应可能已过时，所以随后GET当前资源。 */
  async function begin(current) {
    const level=state.levels.find(v=>v.level_id===state.selected);
    let response;
    try{
      response=await request('attempts',{method:'POST',body:{level_id:level.level_id,level_version:level.level_version,mode:'campaign'},
        headers:{'Idempotency-Key':store.startKey(level.level_id)}});
    }catch(error){
      const active=error.code==='attempt_active'&&error.problem?.links?.attempt;
      if(!active||!current())throw error;
      await restore(active,current);if(current())store.clearStart(level.level_id);return;
    }
    if(!current())return;
    await restore(response.data.links.self,current);
    if(current())store.clearStart(level.level_id);
  }
  return {
    /** 状态由会话方法修改，界面仅渲染。 */
    get state(){return state;},
    /** 本地只判断是否有上局引用，打开时仍由GET验证资源。 */
    hasSaved(id){return Boolean(store.reference(id));},
    /** 无写请求加载目录，账号用户再读取自己的续玩链接。 */
    async load(){return perform(async current=>{
      const [levels,features]=await Promise.all([request('levels?game_id=mine'),request('features')]);
      if(!current())return;
      state.levels=levels.data.items;state.enabled=features.data.progression;
      state.selected=state.levels.find(v=>v.difficulty==='easy')?.level_id||state.levels[0]?.level_id;
      if(uid&&state.enabled){
        const progress=await request('me/level-progress?game_id=mine&limit=50');
        if(!current())return;
        state.progress=progress.data.items;
        if(state.levels.some(v=>v.level_id===store.selected)) {
          state.selected=store.selected;
          const reference=state.progress.find(v=>v.level_id===store.selected)?.current_attempt||
            (store.reference(store.selected)?`/api/v1/attempts/${store.reference(store.selected)}`:null);
          if(reference)try{await restore(reference,current);}catch(error){
            if(![404,410].includes(error.status))throw error;
            if(current()){state.attempt=null;state.message='上次棋局已结束保存期限，可以重新开始。';}
          }
        }
      }
    });},
    /** 切换只影响候选关卡，不开始计时或修改另一关的尝试。 */
    select(id){if(state.busy||!state.levels.some(v=>v.level_id===id))return;state.selected=id;publish();},
    /** 显式开始或继续，未确认创建请求按原键重试。 */
    async open(){return perform(async current=>{
      if(!uid)throw new Error('请先登录。');
      if(!state.enabled)throw new Error('扫雷暂未开放，请稍后重试。');
      const progress=state.progress.find(v=>v.level_id===state.selected);
      const reference=progress?.current_attempt||store.reference(state.selected);
      if(reference){
        try{
          await restore(reference.startsWith('/api/')?reference:`/api/v1/attempts/${reference}`,current);
          if(current()&&!['abandoned','expired','tombstone'].includes(state.attempt.status))return;
        }catch(error){if(![404,410].includes(error.status))throw error;}
      }
      await begin(current);
    });},
    /** 选择格子不揭开，方便触屏玩家确认操作。 */
    choose(index){
      if(state.busy||state.paused||!state.attempt||state.attempt.board.outcome!=='active')return;
      if(!Number.isInteger(index)||index<0||index>=state.attempt.puzzle.rows*state.attempt.puzzle.cols)return;
      state.cell=index;save();publish();
    },
    /** 普通旗标本地保存；教学标记必须由服务器确认步骤。 */
    async mark(){return perform(async current=>{
      const attempt=state.attempt,index=state.cell;
      if(state.paused||!attempt||index===null||attempt.board.outcome!=='active'||attempt.board.revealed.some(v=>v.index===index))return;
      if(attempt.puzzle.tutorial){
        if(attempt.board.tutorial_step!==2||index!==6){state.message='请按教学提示标记第2行第2列。';return;}
        const response=await request(attempt.links.self+'/tutorial-actions/flag',{method:'PUT',body:{}});
        if(current())adopt(response.data);return;
      }
      state.flags=state.flags.includes(index)?state.flags.filter(v=>v!==index):[...state.flags,index];save();
    });},
    /** 教学确认数字含义后进入标记阶段。 */
    async acknowledge(){return perform(async current=>{
      const attempt=state.attempt;
      if(state.paused||!attempt?.puzzle.tutorial||attempt.board.tutorial_step!==1)return;
      const response=await request(attempt.links.self+'/tutorial-actions/number',{method:'PUT',body:{}});
      if(current())adopt(response.data);
    });},
    /** 揭格响应确认前保留原盘，断网可以重放同一位置。 */
    async reveal(){return perform(async current=>{
      const attempt=state.attempt,index=state.cell;
      if(state.paused||!attempt||index===null||state.flags.includes(index)||attempt.board.outcome!=='active')return;
      if(attempt.puzzle.tutorial&&(attempt.board.tutorial_step<3||[6,18,24].includes(index))){
        if(!(attempt.board.tutorial_step===0&&index===0)){state.message='请先完成高亮的教学步骤。';return;}
      }
      const response=await request(attempt.links.self+`/reveals/${index}`,{method:'PUT',body:{}});
      if(!current())return;
      adopt(response.data);state.message='';
      if(response.data.board.outcome==='won')await settle(current);
    });},
    /** 显式重试结算不会创建尝试或再次排雷。 */
    async complete(){return perform(async current=>{if(state.attempt?.board.outcome==='won'&&!state.result)await settle(current);});},
    /** 主动退出只终止本局，收到成功响应后清除旗标、选格与续玩引用。 */
    async abandon(){return perform(async current=>{
      const attempt=state.attempt;if(!attempt)return true;
      if(attempt.status==='active'&&!state.result)await abandonAttempt({attempt,request});
      if(!current())return false;
      store.discard(attempt);
      const progress=state.progress.find(item=>item.level_id===attempt.level_id);
      if(progress&&(progress.current_attempt===attempt.links.self||progress.current_attempt===attempt.attempt_id))progress.current_attempt=null;
      state.attempt=null;state.result=null;state.flags=[];state.cell=null;state.paused=false;state.clockBusy=false;state.message='';
      pauseReasons.clear();pendingClock=null;frozen=null;publish();return true;
    });},
    /** 界面先确认丢弃当前局；条件PATCH与GET核验避免覆盖别处的状态。 */
    async restart(){return perform(async current=>{
      const attempt=state.attempt;
      if(attempt){
        const restarted=await restartAttempt({attempt,store,request});if(!current())return;
        pendingClock=null;await restore(restarted.response.data.links.self,current);
        if(current())restarted.clear();return;
      }
      await begin(current);
    });},
    /** 服务端时间校准只供显示，正式星级仍由后端计算。 */
    elapsed,
    /** 规则、隐藏、选关各持有暂停原因，全部解除才发送继续；离页请求使用keepalive。 */
    async setPaused(reason,value,{immediate=false,sync=true}={}){
      if(dead)return;
      const before=pauseReasons.size>0,time=elapsed();
      if(value)pauseReasons.add(reason);else pauseReasons.delete(reason);
      const paused=pauseReasons.size>0;
      if(!sync)return;
      if(!state.attempt||state.attempt.board.outcome!=='active')return;
      if(before===paused&&state.paused===paused&&!pendingClock&&!state.clockBusy)return;
      frozen=time;state.paused=true;state.clockBusy=true;publish();
      const waitOperation=immediate?Promise.resolve():operationDone;
      const stamp=epoch,current=()=>!dead&&stamp===epoch;
      const work=async()=>{
        if(!immediate)await waitOperation;
        if(!current()||!state.attempt)return;
        try{
          await writeClock(paused,current);
          if(current()&&state.attempt){state.clockBusy=false;state.paused=pauseReasons.size>0||Boolean(state.attempt.timing?.paused);if(!state.paused)frozen=null;}
        }catch(error){if(current()){state.clockBusy=false;state.paused=true;}throw error;}
        finally{if(current())publish();}
      };
      const next=immediate?work():clockQueue.catch(()=>{}).then(work);
      clockQueue=next.catch(()=>{});return next;
    },
    /** 换号/离开使所有尚未返回的读写失效。 */
    destroy(){dead=true;epoch++;state.attempt=null;state.result=null;state.flags=[];},
  };
}
