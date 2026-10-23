"""作用：一次性前端目录迁移，按已确认映射重写静态引用和CSS资源路径；不更改玩法。

仅适用于整改前目录，检测已迁移布局后拒绝重复执行。所有移动/写入局限于项目。
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
FRONT=ROOT/'frontend'


def relative(source,target):
    """生成浏览器相对URL，并验证目标未逃出项目根目录。"""
    target.resolve().relative_to(ROOT)
    value=os.path.relpath(target,source.parent).replace('\\','/')
    return value if value.startswith('.') else './'+value


def mapping():
    """集中声明新目录，页面/业务/公共/历史实现分别归属。"""
    result={
        'main.js':'pages/home.js','pages/home.js':'legacy/game/home.js',
        'forum-page.js':'pages/forum.js','forum-post-page.js':'pages/forum-post.js','ranking-page.js':'pages/ranking.js',
        'game/mine-journey-controller.js':'games/mine/controller.js','game/mine-stars.js':'games/mine/stars.js',
        'mine-effects.js':'games/mine/effects.js','akari.js':'games/akari/rules.js','sudoku.js':'games/sudoku/rules.js',
        'game.js':'legacy/mine/rules.js','progress.js':'legacy/game/progress.js','session.js':'legacy/game/session.js',
        'auth-game.js':'legacy/auth-game.js','auth-page.js':'legacy/auth-page.js','dev-quick-complete.js':'legacy/game/dev-quick-complete.js',
        'pages/mine-practice.js':'legacy/mine/practice-page.js','games/mine/levels.js':'legacy/mine/levels.js',
        'games/mine/practice-store.js':'legacy/mine/practice-store.js',
        'game/game-controller.js':'legacy/game/controller.js','game/game-ui.js':'legacy/game/ui.js',
        'game/progress-coordinator.js':'legacy/game/progress-coordinator.js','game/result-dialog.js':'legacy/game/result-dialog.js',
        'game/mine-controller.js':'legacy/mine/controller.js','game/mine-practice-controller.js':'legacy/mine/practice-controller.js',
        'game/sudoku-controller.js':'legacy/game/sudoku-controller.js','game/akari-controller.js':'legacy/game/akari-controller.js',
        'auth.js':'features/account/auth.js','auth-client.js':'features/account/client.js','auth-validation.js':'features/account/validation.js',
        'avatar.js':'features/account/avatar.js','avatar-picker.js':'features/account/avatar-picker.js','player-profile.js':'features/account/profile.js',
        'music.js':'features/audio/music.js','audio-settings.js':'features/audio/settings.js','settings.js':'features/audio/dialog.js',
        'notifications.js':'features/notifications/controller.js',
        'forum-client.js':'features/forum/client.js','forum-view.js':'features/forum/view.js','forum-discussion.js':'features/forum/discussion.js',
        'ranking-client.js':'features/ranking/client.js','personal-records.js':'features/ranking/personal-records.js',
        'progression/client.js':'features/progression/client.js','progression/journey-store.js':'features/progression/journey-store.js',
        'pk/events.js':'features/pk/events.js',
    }
    for file in (FRONT/'src/lib').glob('*.js'):
        result['lib/'+file.name]='shared/'+file.name
    return {FRONT/'src'/old:FRONT/'src'/new for old,new in result.items()}


def rewrite_js(text,old,new,moves,redirects):
    """按旧文件真实位置解析导入/new URL，而不是字符串全局替换。"""
    pattern=r"((?:\bfrom\s*|\bimport\s*\(|new URL\()\s*['\"])([^'\"]+)(['\"])"
    def replace(match):
        reference=match[2]
        if not reference.startswith('.'):
            return match[0]
        clean,mark,suffix=reference.partition('?')
        target=(old.parent/clean).resolve()
        target=redirects.get((old,clean),moves.get(target,target))
        return match[1]+relative(new,target)+(mark+suffix if mark else '')+match[3]
    return re.sub(pattern,replace,text)


def rewrite_css(text,old,new):
    """CSS声明与顺序原样保留，只修正相对图片路径。"""
    def replace(match):
        value=match[2]
        if not value.startswith('.'):
            return match[0]
        return 'url('+match[1]+relative(new,(old.parent/value).resolve())+match[1]+')'
    return re.sub(r"url\(\s*(['\"]?)([^)'\"\s]+)\1\s*\)",replace,text)


def normalized_css(text,file):
    """用于记录迁移前CSS哈希，资源引用规范化后可验证全部级联声明未变。"""
    return re.sub(r"url\(\s*(['\"]?)([^)'\"\s]+)\1\s*\)",lambda m:'url(/'+(file.parent/m[2]).resolve().relative_to(FRONT).as_posix()+')' if m[2].startswith('.') else m[0],text).replace('\r\n','\n')


def isolate_legacy_challenge():
    """旧挑战客户端不随当前排行榜一起加载；原函数内容和测试断言保留。"""
    client=FRONT/'src/features/ranking/client.js'
    content=client.read_text(encoding='utf-8')
    marker='/** 保存当前账号本轮状态'
    if marker not in content:
        return
    cut=content.index(marker)
    client.write_text(content[:cut].replace("import { createRequestId } from '../../shared/request-id.js';\n",''),encoding='utf-8')
    target=FRONT/'src/legacy/game/challenge-client.js'
    target.write_text("/** 历史单关挑战客户端，仅用于旧实现及其兼容回归。 */\nimport { rankingRequest } from '../../features/ranking/client.js';\nimport { createRequestId } from '../../shared/request-id.js';\n\n"+content[cut:],encoding='utf-8')
    controller=FRONT/'src/legacy/game/controller.js'
    content=controller.read_text(encoding='utf-8').replace("import { ChallengeClient, rankingRequest } from '../../features/ranking/client.js';","import { rankingRequest } from '../../features/ranking/client.js';\nimport { ChallengeClient } from './challenge-client.js';")
    controller.write_text(content,encoding='utf-8')
    test=FRONT/'test/features/ranking/ranking-client.test.js'
    content=test.read_text(encoding='utf-8').replace('import { ChallengeClient, createRequestId, rankingRequest }','import { createRequestId, rankingRequest }')
    content=content.replace('/** 返回符合接口约定',"import { ChallengeClient } from '../../../src/legacy/game/challenge-client.js';\n\n/** 返回符合接口约定")
    # 此文件保护旧挑战协议，归档到legacy；真正排行榜读取仍由其中的契约覆盖。
    new=FRONT/'test/legacy/ranking-client.test.js'
    new.write_text(rewrite_js(content,test,new,{},{}),encoding='utf-8');test.unlink()


def migrate():
    """先冻结输入，再逐一搬移和更新引用，避免页面home与历史home重名覆盖。"""
    if (FRONT/'src/features').exists():
        raise SystemExit('已存在新结构，拒绝重复迁移')
    moves=mapping()
    tests={
        'auth':'features/account','avatar':'features/account','player-profile':'features/account',
        'audio-settings':'features/audio','music':'features/audio','notifications':'features/notifications',
        'forum':'features/forum','forum-body':'features/forum','ranking-client':'features/ranking','personal-records':'features/ranking',
        'progression-client':'features/progression','http':'shared','dom-events':'shared',
        'mine-session':'games/mine','mine-stars':'games/mine','mine-effects':'games/mine',
        'akari':'games/akari','akari-instance':'games/akari','sudoku':'games/sudoku','game-catalog':'games',
        'completion':'legacy','controller-contracts':'legacy','game':'legacy','mine-levels':'legacy','progress':'legacy','session':'legacy'
    }
    for name,folder in tests.items():
        moves[FRONT/'test'/f'{name}.test.js']=FRONT/'test'/folder/f'{name}.test.js'
    # 真正公共的格式化/UUID能力先从旧模块抽出，现有测试通过重导出继续保护兼容。
    session=(FRONT/'src/session.js').read_text(encoding='utf-8')
    fmt=session[session.index('/** 计时统一显示'):]
    client=(FRONT/'src/ranking-client.js').read_text(encoding='utf-8')
    begin=client.index('/** 生成 UUID');end=client.index('/** 排行接口')
    request_id=client[begin:end]
    snapshots={file:file.read_text(encoding='utf-8') for file in (FRONT/'src').rglob('*.js')}
    snapshots.update({file:file.read_text(encoding='utf-8') for file in (FRONT/'test').glob('*.test.js')})
    snapshots[FRONT/'src/session.js']=session[:session.index('/** 计时统一显示')]+"export { formatTime } from './lib/time.js';\n"
    snapshots[FRONT/'src/ranking-client.js']=client[:begin]+"import { createRequestId } from './lib/request-id.js';\nexport { createRequestId } from './lib/request-id.js';\n\n"+client[end:]
    redirects={}
    for file in ('forum-client.js',):
        redirects[(FRONT/'src'/file,'./ranking-client.js')]=FRONT/'src/shared/request-id.js'
    for file,ref in [('pages/pk.js','../session.js'),('ranking-page.js','./session.js'),('personal-records.js','./session.js')]:
        redirects[(FRONT/'src'/file,ref)]=FRONT/'src/shared/time.js'
    redirects[(FRONT/'src/session.js','./lib/time.js')]=FRONT/'src/shared/time.js'
    for ref in ('./lib/request-id.js',):
        redirects[(FRONT/'src/ranking-client.js',ref)]=FRONT/'src/shared/request-id.js'
    for old in moves:
        if old.suffix=='.js' and old.exists():
            old.resolve().relative_to(FRONT)
            old.unlink()
    for old,text in snapshots.items():
        new=moves.get(old,old)
        new.parent.mkdir(parents=True,exist_ok=True)
        new.write_text(rewrite_js(text,old,new,moves,redirects),encoding='utf-8')
    (FRONT/'src/shared/time.js').write_text(fmt,encoding='utf-8')
    (FRONT/'src/shared/request-id.js').write_text(request_id,encoding='utf-8')
    isolate_legacy_challenge()
    # main.js只保留旧缓存/静态探测路径；当前HTML直接使用pages入口。
    (FRONT/'src/main.js').write_text("/** 旧模块URL兼容入口，当前首页直接加载pages/home.js。 */\nimport './pages/home.js';\n",encoding='utf-8')
    # 新test目录更深，修正读HTML/夹具的非模块URL。
    for file in (FRONT/'test').rglob('*.js'):
        text=file.read_text(encoding='utf-8')
        if file.name=='completion.test.js':
            text=text.replace('new URL("./fixtures/legacy-game.html"','new URL("../fixtures/legacy-game.html"')
        if file.name=='forum-body.test.js':
            text=text.replace("new URL('../forum.html'","new URL('../../../forum.html'")
        file.write_text(text,encoding='utf-8')
    original=FRONT/'styles.css'
    css=original.read_text(encoding='utf-8')
    lines=css.splitlines(keepends=True)
    # 连续分段而非重新排序选择器，严格保持媒体查询和组件覆盖的先后。
    chunks=[(0,115,'layout.css'),(115,235,'legacy-games.css'),(235,308,'responsive.css'),
            (308,402,'account.css'),(402,465,'ranking.css'),(465,496,'personal-records.css'),
            (496,568,'settings-avatar.css'),(568,len(lines),'forum.css')]
    manifest={'styles':sha256(normalized_css(css,original).encode()).hexdigest(),'other':[]}
    parts=[]
    for first,last,name in chunks:
        target=FRONT/'styles/components'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(rewrite_css(''.join(lines[first:last]),original,target),encoding='utf-8')
        parts.append('./components/'+name)
    (FRONT/'styles/base.css').write_text('/* 按整改前顺序装配，保持已有层叠与响应式覆盖。 */\n'+''.join(f'@import "{part}";\n' for part in parts),encoding='utf-8')
    original.write_text('/* 旧CSS地址兼容入口，当前页面直接使用styles/base.css。 */\n@import "./styles/base.css";\n',encoding='utf-8')
    css_moves={}
    for name,new_name in [('journey.css','pages/journey.css'),('mine-journey.css','pages/mine.css'),('navigation.css','components/navigation.css'),('mine-practice.css','legacy/mine-practice.css')]:
        old=FRONT/name;new=FRONT/'styles'/new_name;text=old.read_text(encoding='utf-8')
        manifest['other'].append({'target':new.relative_to(FRONT).as_posix(),'hash':sha256(normalized_css(text,old).encode()).hexdigest()})
        css_moves[old]=new;new.parent.mkdir(parents=True,exist_ok=True);new.write_text(rewrite_css(text,old,new),encoding='utf-8');old.unlink()
        # 服务端主题元数据或已缓存页面可能仍引用旧CSS地址，保留轻量转接。
        old.write_text(f'/* 旧样式URL兼容入口，规则已归入styles。 */\n@import "{relative(old,new)}";\n',encoding='utf-8')
    (FRONT/'test/fixtures/css-baseline.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    html_moves={**moves,**css_moves,FRONT/'styles.css':FRONT/'styles/base.css'}
    for html in FRONT.glob('*.html'):
        text=html.read_text(encoding='utf-8')
        def html_ref(match):
            old=(html.parent/match[2]).resolve();new=html_moves.get(old)
            return match[1]+relative(html,new)+match[3] if new else match[0]
        text=re.sub(r"((?:src|href)=['\"])([^'\"]+)(['\"])",html_ref,text)
        html.write_text(text,encoding='utf-8')
    # 清除仅由本次搬空的目录，使用rmdir拒绝删除非空目录。
    for parent in sorted({old.parent for old in moves},key=lambda p:len(p.parts),reverse=True):
        if parent.exists() and parent not in (FRONT/'src',FRONT/'test') and not any(parent.iterdir()):parent.rmdir()
    print(f'迁移完成：{len(moves)}个模块/测试映射，CSS顺序基线已冻结')


if __name__=='__main__':
    migrate()
