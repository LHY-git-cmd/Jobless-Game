/** 扫雷星级展示：时间预览、三颗星绘制及服务器新增星数的汇聚动画。 */
const STAR_ICON='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 2 3 6.2 6.8 1-4.9 4.8 1.2 6.8L12 17.6l-6.1 3.2 1.2-6.8-4.9-4.8 6.8-1Z"/></svg>';

/** 预览遵守服务器含等号的毫秒门槛，结算返回后以权威星数为准。 */
export function availableMineStars(level,elapsedMs,outcome='active',confirmed=null){
  if(outcome==='lost')return 0;
  if(Number.isInteger(confirmed)&&confirmed>=0&&confirmed<=3)return confirmed;
  if(!level)return 0;
  if(level.max_stars===1)return 1;
  const duration=Math.max(0,elapsedMs);
  return duration<=level.t3_ms?3:duration<=level.t2_ms?2:1;
}

/** 固定三颗空心轮廓，按成绩填色；只在数量或读屏描述变化时更新。 */
export function paintMineStars(host,count,label=`${count}颗星，共3颗`){
  const value=Math.max(0,Math.min(3,Math.trunc(count)||0));
  if(host.dataset.stars===String(value)&&host.getAttribute('aria-label')===label)return;
  if(host.children.length!==3)host.innerHTML=STAR_ICON.repeat(3);
  [...host.children].forEach((star,index)=>star.classList.toggle('is-lit',index<value));
  host.dataset.stars=String(value);host.setAttribute('role','img');host.setAttribute('aria-label',label);
}

/** 动画只接收服务器确认的差额与总数，不在此计算或发放账号权益。 */
export function createStarCollection({dom=document,view=window,onComplete=()=>{}}={}){
  let active=null;
  const seen=new Set(),decorations=new Set();
  /** 判断元素是否处于当前视口，手机端不为动画强行滚动页面。 */
  function visible(rect){return rect&&rect.width>0&&rect.height>0&&rect.left<view.innerWidth&&rect.left+rect.width>0&&rect.top<view.innerHeight&&rect.top+rect.height>0;}
  /** 清理飞行和临时总数，避免返回、隐藏、换号后残留。 */
  function remove(run){
    run.effects.forEach(effect=>effect.cancel());
    if(run.timer&&view.clearTimeout)view.clearTimeout(run.timer);
    run.layer.remove();decorations.delete(run);
  }
  /** commit为false用于换号/销毁；返回或重开则立即展示已确认的成长。 */
  function cancel(commit=true){
    const previous=active;active=null;
    if(previous){remove(previous);if(commit)onComplete(previous.reward);}
    for(const run of [...decorations])remove(run);
  }
  return {
    /** 同一账号同一尝试仅播放一次，重复成绩和减少动画偏好直接同步总数。 */
    async play(reward){
      const total=reward?.progression?.total_stars;
      if(!Number.isSafeInteger(total)||total<0)return;
      const key=`${reward.userId}:${reward.key}`;
      if(seen.has(key))return;
      cancel();seen.add(key);if(seen.size>32)seen.delete(seen.values().next().value);
      const count=Number.isInteger(reward.awardedStars)?Math.min(3,Math.max(0,reward.awardedStars)):0;
      if(!count||dom.hidden||view.matchMedia('(prefers-reduced-motion: reduce)').matches){onComplete(reward);return;}
      const layer=dom.createElement('div');layer.className='mine-star-collection';layer.setAttribute('aria-hidden','true');
      const source=reward.source?.getBoundingClientRect(),target=reward.target?.getBoundingClientRect();
      const origin=visible(source)?{x:source.left+source.width/2,y:source.top+source.height/2}:{x:view.innerWidth/2,y:view.innerHeight*.55};
      const destination=visible(target)?{x:target.left+target.width/2,y:target.top+target.height/2}:{x:view.innerWidth-100,y:36};
      let badgeCount;
      if(!visible(target)){
        const badge=dom.createElement('div'),icon=dom.createElement('span');badgeCount=dom.createElement('strong');
        badge.className='mine-star-total';icon.innerHTML=STAR_ICON;badgeCount.textContent=String(Math.max(0,total-count));
        badge.append(icon,badgeCount);layer.append(badge);
      }
      dom.body.append(layer);
      const run={layer,reward,effects:[],timer:null};active=run;
      for(let index=0;index<count;index++){
        const star=dom.createElement('span');star.className='mine-flying-star';star.innerHTML=STAR_ICON;layer.append(star);
        // 固定24px图形只动画transform/opacity，时间线依次抵达同一总数位置。
        const x=Math.max(12,Math.min(view.innerWidth-36,origin.x-12+(index-(count-1)/2)*28));
        const y=Math.max(12,Math.min(view.innerHeight-36,origin.y-12));
        const endX=destination.x-12,endY=destination.y-12;
        if(!star.animate){cancel();return;}
        run.effects.push(star.animate([
          {transform:`translate3d(${x}px,${y}px,0) scale(.6)`,opacity:0},
          {transform:`translate3d(${x}px,${y-16}px,0) scale(1.2)`,opacity:1,offset:.14},
          {transform:`translate3d(${(x+endX)/2}px,${Math.max(8,Math.min(y,endY)-50)}px,0) scale(1)`,opacity:1,offset:.65},
          {transform:`translate3d(${endX}px,${endY}px,0) scale(.3)`,opacity:0}
        ],{duration:840,delay:index*110,easing:'cubic-bezier(.22,.7,.3,1)',fill:'both'}));
      }
      await Promise.all(run.effects.map(effect=>effect.finished.catch(()=>{})));
      if(active!==run)return;
      active=null;onComplete(reward);
      if(badgeCount&&view.setTimeout){
        badgeCount.textContent=String(total);decorations.add(run);
        run.timer=view.setTimeout(()=>remove(run),700);
      }else remove(run);
    },
    cancel,
  };
}
