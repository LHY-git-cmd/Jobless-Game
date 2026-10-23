"""作用：开发机离线构建照明16关，记录确定性逻辑推理并独立验证唯一解。

运行 python -m backend.akari_content --generate 创建新版本；已存在的冻结文件不可覆盖。
在线服务不得调用本工具。反证只接受某个假设推出矛盾，不接受猜中完整答案。
"""
import argparse
import json
from pathlib import Path
import random
from .app.services.game_rules import adjacent, ray, validate_akari
from .content_check import akari_solutions, checksum

ROOT = Path(__file__).resolve().parent
SIZES = [4,4,5,5,6,6,6,7,7,7,8,8,8,9,9,10]
FOCUS = ['放灯与撤灯','照亮每个角落','0的禁放区域','1的准确位置','2的相邻约束','3与4的明确落点',
         '数字之间的联动','共享邻格','寻找唯一光源','交叉通道','连锁照明','观察外围线索','减少数字提示','跨区联动','完整推理链','最终灯塔']
GUIDES = ['点击白格放灯，再点一次撤灯。灯光沿横竖传播，遇到黑墙停止。',
          '先寻找明确的放灯位置；灯泡之间不能互相照射，数字只计算上下左右。',
          '0周围不能放灯，但这些白格仍要由其他位置的灯照亮。',
          '1周围必须恰好有一盏灯。结合黑墙、边界与光线排除多余位置。',
          '2周围必须恰好有两盏灯，先看看还有哪些相邻格可以放灯。',
          '3或4也只计算上下左右。可用位置刚好够时，就能确定这些灯位。']


def constraints_for(grid):
    """把数字等式、横竖互斥和白格覆盖分别编译为0/1数量上下界。"""
    cols = len(grid[0]); cells = ''.join(grid)
    white = frozenset(i for i, c in enumerate(cells) if c == '.')
    segments = set(); constraints = []
    for index, cell in enumerate(cells):
        if cell in '01234':
            constraints.append((frozenset(adjacent(index,len(grid),cols)) & white,int(cell),int(cell),'number'))
    for index in sorted(white):
        visible = ray(index, grid)
        segments.add(frozenset(i for i in visible if i//cols == index//cols))
        segments.add(frozenset(i for i in visible if i%cols == index%cols))
    constraints.extend((s,0,1,'sight') for s in sorted(segments,key=lambda s:tuple(sorted(s))))
    constraints.extend((frozenset(ray(i,grid)),1,len(ray(i,grid)),'coverage') for i in sorted(white))
    return white, constraints


def deductions(values, constraints, joint=False):
    """返回下一组必然赋值；交集上下界仅作合法排除，不猜测灯位。"""
    reduced=[]
    for indices, low, high, kind in constraints:
        total=sum(values.get(i,0) for i in indices)
        pending=indices-values.keys(); low=max(0,low-total); high=min(len(pending),high-total)
        if high<low:
            return False
        if not pending:
            continue
        if high==0 or low==len(pending):
            return (sorted(pending), int(low==len(pending)), kind)
        reduced.append((pending,low,high,kind))
    if joint:
        # A与B共享位置时，共享部分至多承载B的上界；由此约束A剩余位置。
        for a,low_a,high_a,kind_a in reduced:
            for b,low_b,high_b,kind_b in reduced:
                if a==b or not a&b:
                    continue
                rest=a-b
                low=max(0,low_a-min(high_b,len(a&b)))
                high=min(len(rest),high_a-max(0,low_b-len(b-a)))
                if high<low:
                    return False
                if rest and (high==0 or low==len(rest)):
                    return (sorted(rest),int(low==len(rest)),'joint')
    return None


def propagate(values, constraints, joint):
    """反证中的确定性传播，只有发现矛盾才允许推出原位置的相反状态。"""
    current=dict(values)
    while True:
        found=deductions(current,constraints,joint)
        if found is False:
            return False
        if found is None:
            return True
        indices,value,_=found
        current.update((i,value) for i in indices)


def solve(grid, tier=2):
    """固定顺序运用直接约束、交集推理和单层矛盾反证，生成可复现审计。"""
    white,constraints=constraints_for(grid)
    values={};trace=[];used=0
    while len(values)<len(white):
        found=deductions(values,constraints)
        if found is False:
            break
        if found is None and tier>=1:
            found=deductions(values,constraints,True)
        if found is False:
            break
        if found is None and tier>=2:
            for index in sorted(white-values.keys()):
                for assumed in (1,0):
                    if not propagate({**values,index:assumed},constraints,True):
                        found=([index],1-assumed,'contradiction')
                        break
                if found:
                    break
        if found is None:
            break
        indices,value,technique=found
        used=max(used, {'joint':1,'contradiction':2}.get(technique,0))
        values.update((i,value) for i in indices)
        trace.append({'technique':technique,'indices':indices,'value':value})
    bulbs=sorted(i for i,value in values.items() if value)
    solved=len(values)==len(white) and validate_akari({'map':grid},bulbs)
    # 仅用于离线排序：技巧层级优先，其次是连续推理步数及白格操作量。
    return {'solved':solved,'bulbs':bulbs,'tier':used,'score':used*100000+len(trace)*100+len(white),'trace':trace}


def candidate(rng, size, number):
    """由合法灯光布局反推数字，再稀疏化提示；不把答案存入公开题目。"""
    density=.30 if number<7 else .25
    grid=[['#' if rng.random()<density else '.' for _ in range(size)] for _ in range(size)]
    raw=[''.join(row) for row in grid]; white=[i for i,c in enumerate(''.join(raw)) if c=='.']
    if not white:
        return None
    rng.shuffle(white);bulbs=set();lit=set()
    for index in white:
        if index not in lit:
            bulbs.add(index);lit |= ray(index,raw)
    max_digit=1 if number<4 else 2 if number==4 else 4
    retain=.92 if number<5 else .82 if number<7 else .62 if number<11 else .46
    for index,cell in enumerate(''.join(raw)):
        if cell=='#':
            count=sum(i in bulbs for i in adjacent(index,size,size))
            if count<=max_digit and rng.random()<retain:
                grid[index//size][index%size]=str(count)
    return [''.join(row) for row in grid]


def generate():
    """固定种子筛选实际递进题，冻结目录、推理审计和Flyway新增定义。"""
    target=ROOT/'content/akari-catalog-v2.json'
    audit_target=ROOT/'content/akari-audit-v2.json'
    migration=ROOT/'migrations/V13__publish_akari_levels.sql'
    if any(p.exists() for p in (target,audit_target,migration)):
        raise ValueError('冻结文件已存在，禁止覆盖')
    rng=random.Random(20261022016);levels=[];audit={};previous=-1
    for number,size in enumerate(SIZES):
        best=None
        # 前七题直接约束，随后交集联动，末三题加入可验证的矛盾排除。
        required=0 if number<7 else 1 if number<13 else 2
        for attempt in range(16000):
            grid=candidate(rng,size,number)
            if not grid:
                continue
            chars=''.join(grid)
            if number==2 and '0' not in chars or number==3 and '1' not in chars or number==4 and '2' not in chars or number==5 and not set('34')&set(chars):
                continue
            # 先用便宜的两解搜索淘汰多解盘，避免对无资格候选执行昂贵反证。
            if number>=7 and len(akari_solutions(grid))!=1:
                continue
            result=solve(grid,required)
            if not result['solved'] or result['tier']!=required or result['score']<=previous:
                continue
            if best is None or result['score']<best[1]['score']:
                best=(grid,result)
            if best and attempt>=120:
                break
        if best is None:
            raise ValueError(f'第{number}关未找到递进题，前分值{previous}')
        grid,result=best
        if number==0:
            # 教学仅保留两个必要的数字1，避免冗余数字墙淹没放灯/撤灯目标。
            grid=['#.##','1.##','###1','##..'];result=solve(grid)
        if len(akari_solutions(grid))!=1:
            raise ValueError('逻辑题未通过独立唯一性检查')
        puzzle={'rows':size,'cols':size,'map':grid,**({'tutorial':True} if number==0 else {})}
        puzzle['checksum']=checksum(puzzle)
        level={'level_id':'akari-v2-tutorial' if number==0 else f'akari-v2-{number:03}',
               'game_id':'akari','level_version':1,'rules_version':2,'reward_policy_version':1,
               'order':number+1,'number':number,'name':'入门' if number==0 else f'第{number}关',
               'difficulty':'tutorial' if number==0 else 'campaign','focus':FOCUS[number],
               'guide':GUIDES[number] if number<len(GUIDES) else '',
               'minimum_level':1,'prerequisite_level_id':None,'modes':['campaign'],
               **({'max_stars':1,'star_xp':[2]} if number==0 else {}),
               't3_ms':size*size*4000,'t2_ms':size*size*8000,'puzzle':puzzle}
        levels.append(level);audit[level['level_id']]=result;previous=result['score']
        print(f'{level["name"]}: {size}x{size}, tier={result["tier"]}, steps={len(result["trace"])}',flush=True)
    target.write_text(json.dumps({'version':2,'levels':levels},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    audit_target.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['-- 作用：新增照明入门及15项冻结关卡，保留旧题目、历史成绩与资格。','']
    for level in levels:
        identity=level['level_id'];definition=json.dumps(level,ensure_ascii=False,separators=(',',':')).replace("'","''")
        lines.append(f"INSERT INTO game_levels (level_id, game_id, order_index) VALUES ('{identity}', 'akari', {level['order']});")
        lines.append(f"INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('{identity}', 1, '{definition}');")
    migration.write_text('\n'.join(lines)+'\n',encoding='utf-8')


def revise_tutorial_and_boards():
    """追加v3：保留旧定义，教学和第10～15关用同一权益身份的版本2。"""
    target=ROOT/'content/akari-catalog-v3.json'
    audit_target=ROOT/'content/akari-audit-v3.json'
    migration=ROOT/'migrations/V14__expand_akari_tutorial_and_boards.sql'
    if any(p.exists() for p in (target,audit_target,migration)):
        raise ValueError('新版本已存在，禁止覆盖冻结题目')
    catalog=json.loads((ROOT/'content/akari-catalog-v2.json').read_text(encoding='utf-8'))
    audit=json.loads((ROOT/'content/akari-audit-v2.json').read_text(encoding='utf-8'))
    levels=catalog['levels'];rng=random.Random(20261023014)
    tutorial=levels[0]
    # 左上光路能同时观察横竖传播，三个独立区域分别练习光线和数字墙。
    steps=[
        {'title':'点亮第一束光','text':'点击高亮格放灯。灯光沿横竖传播，不会穿过黑墙；暖黄色表示已照亮。','index':0,'bulb':True,'focus':[0,1,5]},
        {'title':'放错也能修改','text':'再次点击同一盏灯，把它撤下。任何未通关的棋盘都可以这样修改。','index':0,'bulb':False,'focus':[0]},
        {'title':'观察光线与黑墙','text':'再放回这盏灯。右侧和下方的黑墙挡住光线，黑墙本身不能放灯。','index':0,'bulb':True,'focus':[0,2,10]},
        {'title':'体验灯泡互照','text':'点击高亮格再放一盏灯，观察两盏灯互相照射时出现的红色提示。','index':1,'bulb':True,'focus':[0,1]},
        {'title':'消除互照冲突','text':'撤下刚才新增的灯，消除红色冲突。两束光可以交叉，但灯泡不能照到另一盏灯。','index':1,'bulb':False,'focus':[0,1]},
        {'title':'读懂数字墙','text':'0的上下左右不能放灯；1～4要求相邻灯数恰好等于数字，斜角不算。点击高亮格，让右上角的1恰好邻接一盏灯。','index':9,'bulb':True,'focus':[2,4,9,10]},
        {'title':'独立点亮最后一区','text':'照亮剩余白格，并同时满足所有数字、灯泡不互照。已照亮的格子仍可点击；只有三个条件全部满足才通关。','focus':[17,18,22,23]},
    ]
    puzzle={'rows':5,'cols':5,'map':['..0#1','.###.','0####','##10#','##..#'],'tutorial':True,'tutorial_steps':steps}
    puzzle['checksum']=checksum(puzzle)
    tutorial.update(level_version=2,puzzle=puzzle,focus='七步认识照明规则')
    audit[tutorial['level_id']]=solve(puzzle['map'])
    previous=audit[levels[9]['level_id']]['score'];pools={1:{},2:{}}
    def shape(grid):
        """以墙体位置识别拓扑，六关不用同一张墙图的数字变体充数。"""
        return tuple(''.join('.' if c=='.' else '#' for c in row) for row in grid)

    def guided_variant(grid,result):
        """只在离线已验证唯一题上增加真实数字，寻找联合约束可解的较易变体。"""
        bulbs=set(result['bulbs']);walls=[i for i,c in enumerate(''.join(grid)) if c=='#']
        random.Random(checksum({'map':grid})).shuffle(walls)
        for accumulate in (False,True):
            revised=[list(row) for row in grid]
            for index in walls:
                if not accumulate:revised=[list(row) for row in grid]
                revised[index//10][index%10]=str(sum(i in bulbs for i in adjacent(index,10,10)))
                current=[''.join(row) for row in revised];logical=solve(current,1)
                if logical['solved'] and logical['tier']==1 and logical['score']>previous:
                    return current,logical
        return None
    # 先收集同尺寸候选再整体排序，避免某一关先选得过难而堵住后续递进。
    for attempt in range(20000):
        grid=candidate(rng,10,10 if rng.random()<.65 else 13)
        if not grid or any('.' not in row for row in grid) or any(all(row[col]!='.' for row in grid) for col in range(10)):
            continue
        if len(akari_solutions(grid))!=1:
            continue
        direct=solve(grid,1)
        if direct['solved']:
            result=direct
        elif len(pools[2])<8:
            result=solve(grid,2)
        else:
            continue
        tier=result['tier']
        if result['solved'] and tier in pools and result['score']>previous and result['score'] not in pools[tier]:
            pools[tier][result['score']]=(grid,result)
            print(f'10x10候选: tier={tier}, steps={len(result["trace"])}, pool={len(pools[tier])}',flush=True)
            if tier==2 and len(pools[1])<8:
                easier=guided_variant(grid,result)
                if easier and easier[1]['score'] not in pools[1] and all(shape(v[0])!=shape(easier[0]) for v in pools[1].values()):
                    pools[1][easier[1]['score']]=easier
        if len(pools[1])>=8 and len(pools[2])>=8:
            break
    if any(len(pool)<3 for pool in pools.values()):
        raise ValueError('未收集足够的10×10逻辑递进题')
    chosen=[]
    for tier in (1,2):
        used={shape(grid) for grid,_ in chosen}
        ordered=sorted((score,pair) for score,pair in pools[tier].items() if shape(pair[0]) not in used)
        if len(ordered)<3:
            raise ValueError('不同墙体布局不足三题')
        chosen.extend(ordered[i][1] for i in (0,len(ordered)//2,len(ordered)-1))
    for number,(grid,result) in enumerate(chosen,10):
        puzzle={'rows':10,'cols':10,'map':grid};puzzle['checksum']=checksum(puzzle)
        levels[number].update(level_version=2,puzzle=puzzle)
        audit[levels[number]['level_id']]=result;previous=result['score']
        print(f'第{number}关: 10x10, tier={result["tier"]}, steps={len(result["trace"])}',flush=True)
    target.write_text(json.dumps({'version':3,'levels':levels},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    audit_target.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['-- 作用：追加照明七步入门与第10～15关10×10的版本2，保留旧定义、尝试和权益。','']
    for level in levels:
        if level['level_version']!=2:
            continue
        definition=json.dumps(level,ensure_ascii=False,separators=(',',':')).replace("'","''")
        lines.append(f"INSERT INTO game_level_versions (level_id, level_version, definition) VALUES ('{level['level_id']}', 2, '{definition}');")
    migration.write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate',action='store_true')
    parser.add_argument('--revise',action='store_true',help='追加七步教学与10～15关10×10的新冻结版本')
    args=parser.parse_args()
    if args.generate:
        generate()
    if args.revise:
        revise_tutorial_and_boards()
