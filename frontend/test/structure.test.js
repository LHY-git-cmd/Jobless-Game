/** 作用：迁移前定义目录和资源契约，防止断链、生产加载遗留实现及CSS层叠漂移。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir, access } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
/** 递归目录仅用于静态引用审计，不执行页面入口。 */
async function files(folder){return (await Promise.all((await readdir(folder,{withFileTypes:true})).map(entry=>entry.isDirectory()?files(path.join(folder,entry.name)):[path.join(folder,entry.name)]))).flat();}
/** 静态导入和new URL素材共用解析；保留测试专用查询参数。 */
function localRefs(source){return [...source.matchAll(/(?:\bfrom\s*|\bimport\s*\(|new URL\()\s*['"]([^'"]+)['"]/g)].map(match=>match[1]).filter(value=>value.startsWith('.'));}
/** 样式内容的URL规范成根相对路径，允许搬目录但不允许改变规则或级联顺序。 */
function normalizeCss(content,file){return content.replace(/url\(\s*(['"]?)([^)'"\s]+)\1\s*\)/g,(all,quote,value)=>value.startsWith('.')?`url(/${path.relative(root,path.resolve(path.dirname(file),value)).replaceAll('\\','/')})`:all).replaceAll('\r\n','\n');}

test('页面入口统一pages，共享模块没有业务反向依赖，当前页面不加载legacy',async()=>{
  const htmlFiles=(await readdir(root)).filter(name=>name.endsWith('.html'));
  const pending=[];
  for(const name of htmlFiles){
    const source=await readFile(path.join(root,name),'utf8');
    for(const match of source.matchAll(/<script[^>]+src=['"]([^'"]+)['"]/g)){
      assert.match(match[1],/^\.\/src\/pages\//,name);pending.push(path.resolve(root,match[1]));
    }
  }
  const visited=new Set();
  while(pending.length){
    const file=pending.pop();if(visited.has(file))continue;visited.add(file);
    assert.ok(!file.includes(`${path.sep}legacy${path.sep}`),`当前入口加载历史模块：${file}`);
    const source=await readFile(file,'utf8');
    for(const ref of localRefs(source)){if(ref.endsWith('.js'))pending.push(path.resolve(path.dirname(file),ref));}
  }
  for(const file of await files(path.join(root,'src/shared'))){
    const source=await readFile(file,'utf8');
    for(const ref of localRefs(source))assert.ok(path.resolve(path.dirname(file),ref).startsWith(path.join(root,'src/shared')+path.sep),`共享模块反向引用业务：${file}`);
  }
  const rootModules=(await readdir(path.join(root,'src'))).filter(name=>name.endsWith('.js'));
  assert.deepEqual(rootModules,['main.js'],'根目录仅保留旧缓存探测地址的兼容入口');
});

test('HTML/JS/CSS相对引用全部有效，URL不得越过frontend根目录',async()=>{
  const targets=(await files(root)).filter(file=>/\.(html|js|css)$/.test(file)&&!file.includes(`${path.sep}test${path.sep}`));
  for(const file of targets){
    const source=await readFile(file,'utf8'),refs=[];
    if(file.endsWith('.js'))refs.push(...localRefs(source));
    if(file.endsWith('.html'))refs.push(...[...source.matchAll(/(?:src|href)=['"]([^'"?#]+)(?:[?#][^'"]*)?['"]/g)].map(match=>match[1]));
    if(file.endsWith('.css'))refs.push(...[...source.matchAll(/(?:url\(\s*|@import\s+)['"]?([^\s)'";]+)/g)].map(match=>match[1]));
    for(const ref of refs.filter(value=>!value.startsWith('#')&&!/^(?:https?:|data:|mailto:|\/api\/)/.test(value))){
      const target=ref.startsWith('/')?path.join(root,ref):path.resolve(path.dirname(file),ref);
      assert.ok(target.startsWith(root+path.sep)||target===root,`越界资源 ${file}: ${ref}`);
      await assert.doesNotReject(access(target),`断链 ${file}: ${ref}`);
    }
  }
});

test('样式拆分与旧版本声明顺序完全一致，已发布CSS探测地址保留兼容',async()=>{
  const manifest=JSON.parse(await readFile(path.join(root,'test/fixtures/css-baseline.json'),'utf8'));
  const entry=path.join(root,'styles/base.css');
  const aggregator=await readFile(entry,'utf8');
  const parts=[...aggregator.matchAll(/@import ['"]([^'"]+)['"]/g)].map(match=>path.resolve(path.dirname(entry),match[1]));
  const content=(await Promise.all(parts.map(async file=>normalizeCss(await readFile(file,'utf8'),file)))).join('');
  assert.equal(createHash('sha256').update(content).digest('hex'),manifest.styles,'CSS规则或层叠顺序发生变化');
  for(const item of manifest.other){
    const file=path.join(root,item.target);
    assert.equal(createHash('sha256').update(normalizeCss(await readFile(file,'utf8'),file)).digest('hex'),item.hash,item.target);
  }
  assert.match(await readFile(path.join(root,'styles.css'),'utf8'),/@import ['"]\.\/styles\/base\.css/);
});

test('Docker与离线包包含新样式，测试夹具不进入发布',async()=>{
  const ignore=await readFile(path.join(root,'../.dockerignore'),'utf8');
  assert.match(ignore,/!frontend\/styles\/\*\*/);
  assert.ok(!/^!frontend\/\*\*\s*$/m.test(ignore),'不能无差别把测试目录开放给构建');
  assert.match(ignore,/^frontend\/test\/\*\*$/m,'必须显式排除嵌套HTML测试夹具');
  const builder=await readFile(path.join(root,'../backend/deploy/server/build_release.py'),'utf8');
  assert.match(builder,/ignore_patterns\([^)]*"test"/);
});
