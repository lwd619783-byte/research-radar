// Vercel builds only the allowlisted static output, never repository evidence.
const fs = require('node:fs');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
// Mirrored from notion_schema.json; the offline test enforces exact equality.
const BANNED_WORDS = ['买入','卖出','加仓','减仓','抄底','逃顶','目标价','推荐','定投','止损','止盈','建仓','清仓','满仓','重仓','必涨','稳赚','翻倍','牛股','金股','已核实','已审核','人工确认','已验证'];
const DISCLAIMER = '研究内容由 AI 依据公开资料撰写，程序自动检查格式、日期与来源，未经人工审核；行情由定时任务更新。仅供研究参考，不构成投资建议。';
const OLD_UI = /核验|核实|核对|待复核|待核|原评分|原标记|人工评分/;
const PRIVATE_KEYS=new Set(['created_by','last_edited_by','request_id','request_headers','access_token','authorization','notion_token']);
const SECRET_VALUE=/(?:\bntn_[A-Za-z0-9_-]{12,}|\bsecret_[A-Za-z0-9_-]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bBearer\s+[A-Za-z0-9._-]{20,})/i;
function decoded(value) {
  return value.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);?/gi, (all, name) => {
    if (name[0] === '#') {
      const point = name[1].toLowerCase() === 'x' ? parseInt(name.slice(2),16) : Number(name.slice(1));
      return point > 0 && point <= 0x10ffff ? String.fromCodePoint(point) : '\ufffd';
    }
    return {amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:' '}[name.toLowerCase()];
  });
}
function normalized(value) { return value.normalize('NFKC').replace(/\s|\u3000/g,''); }
function needsV3Scan(html,data,manifest={}) {
  return manifest.schemaVersion>=3 || /id=["']heroProv["']/.test(html)
    || Boolean(data?.meta&&Object.hasOwn(data.meta,'notion'));
}
function scanOutput(html, data) {
  if(!data||typeof data!=='object'||Array.isArray(data)||!data.meta||typeof data.meta!=='object'||Array.isArray(data.meta)
    ||['industries','chokepoints','companies'].some(key=>!Array.isArray(data[key])))throw Error('invalid_data_shape');
  const embedded=[...html.matchAll(/<script\b[^>]*>\s*const\s+DATA\s*=\s*(.*?)\s*;\s*<\/script\s*>/gis)];
  if(embedded.length!==1)throw Error('invalid_embedded_data');
  let parsed;try{parsed=JSON.parse(embedded[0][1]);}catch{throw Error('invalid_embedded_data');}
  try{assert.deepEqual(parsed,data);}catch{throw Error('embedded_data_mismatch');}
  const text=[], ui=[], attributes=[], stack=[];
  let disclaimers=0;
  const voids=new Set(['area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr']);
  const attrNames=new Set(['data-tip','title','aria-label','placeholder','alt']);
  const excluded=()=>stack.some(item=>item.tag==='script'||item.tag==='style'||item.tag==='template'||item.hidden);
  const fromNotion=()=>stack.some(item=>item.notion);
  // Tokenize markup while respecting quoted attribute values. Script/style data
  // is excluded; their embedded DATA is checked independently below.
  let pos=0;
  while(pos<html.length) {
    if(html.startsWith('<!--',pos)){const end=html.indexOf('-->',pos+4);pos=end<0?html.length:end+3;continue;}
    if(html[pos]!=='<') {
      let end=html.indexOf('<',pos);if(end<0)end=html.length;
      const value=decoded(html.slice(pos,end));
      if(!excluded()){text.push(value);if(!fromNotion())ui.push(value);}
      pos=end;continue;
    }
    let end=pos+1,quote='';
    for(;end<html.length;end++){const c=html[end];if(quote){if(c===quote)quote='';}else if(c==='"'||c==="'")quote=c;else if(c==='>')break;}
    const token=html.slice(pos,end+1);pos=end+1;
    const match=/^<\s*(\/?)\s*([a-z][\w:-]*)/i.exec(token);if(!match)continue;
    const tag=match[2].toLowerCase();
    if(match[1]){const index=stack.map(item=>item.tag).lastIndexOf(tag);if(index>=0)stack.length=index;continue;}
    const attrs={};const rest=token.slice(match[0].length);
    for(const m of rest.matchAll(/([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g))attrs[m[1].toLowerCase()]=decoded(m[2]??m[3]??m[4]??'');
    if(attrs.id==='disclaimer')disclaimers++;
    if((attrs.class||'').split(/\s+/).includes('mock-note'))throw Error('design_note_in_output');
    const notion=fromNotion()||attrs['data-src']==='notion';
    for(const [name,value] of Object.entries(attrs))if(attrNames.has(name)){attributes.push(value);if(!notion)ui.push(value);}
    if(tag==='a'&&attrs.href&&!attrs.href.startsWith('#')){
      let url;try{url=new URL(attrs.href);}catch{throw Error('unsafe_output_link');}
      if(!['http:','https:'].includes(url.protocol)||url.username||url.password||/[\x00-\x20]/.test(attrs.href))throw Error('unsafe_output_link');
      const rel=new Set((attrs.rel||'').split(/\s+/));
      if(attrs.target!=='_blank'||!rel.has('noopener')||!rel.has('noreferrer'))throw Error('unsafe_output_link');
    }
    if(!voids.has(tag)&&!token.endsWith('/>'))stack.push({tag,notion,hidden:Object.hasOwn(attrs,'hidden')});
    if(tag==='script'||tag==='style'||tag==='template'){
      const close=html.toLowerCase().indexOf('</'+tag,pos);if(close<0)throw Error('invalid_output_markup');pos=close;
    }
  }
  const values=[];
  function walk(value){if(typeof value==='string')values.push(value);else if(value&&typeof value==='object')for(const [key,item] of Object.entries(value)){if(PRIVATE_KEYS.has(key.toLowerCase()))throw Error('sensitive_output');walk(item);}}
  walk(data);
  for(const value of [...text,...attributes,...values,text.join('')])if(BANNED_WORDS.some(word=>normalized(value).includes(word)))throw Error('banned_words_in_output');
  if(ui.some(value=>OLD_UI.test(normalized(value)))||OLD_UI.test(normalized(ui.join(''))))throw Error('legacy_ui_in_output');
  if(text.join('').split(DISCLAIMER).length!==2||disclaimers!==1)throw Error('disclaimer_count');
  if(html.includes('.mock-note'))throw Error('design_note_in_output');
  if(SECRET_VALUE.test(html)||SECRET_VALUE.test(JSON.stringify(data)))throw Error('sensitive_output');
  return true;
}
function verifyRelease() {
const m = JSON.parse(fs.readFileSync('release.json', 'utf8'));
assert.equal(m.schemaVersion, 2);
assert.match(m.sourceSHA, /^[0-9a-f]{40}$/);
assert.match(m.runId, /^[0-9]+$/);
assert.deepEqual(m.blockers, []);
assert.deepEqual(fs.readdirSync('public').sort(), ['index.html', 'robots.txt', 'version.json']);
assert.deepEqual(Object.keys(m.files).sort(), ['index.html', 'robots.txt', 'version.json']);
for (const [name, expected] of Object.entries(m.files)) {
  assert(fs.lstatSync(`public/${name}`).isFile());
  assert.equal(crypto.createHash('sha256').update(fs.readFileSync(`public/${name}`)).digest('hex'), expected);
}
assert.equal(crypto.createHash('sha256').update(fs.readFileSync('history.json')).digest('hex'), m.historySHA256);
const version = JSON.parse(fs.readFileSync('public/version.json', 'utf8'));
assert.equal(version.sourceSHA, m.sourceSHA);
assert.equal(version.dataSHA256, m.dataSHA256);
const html=fs.readFileSync('public/index.html','utf8');
// Old v2 releases remain usable for rollback. Every v3-rendered page has this
// stable slot, including a v3 interface rendering legacy DATA.
const matches=[...html.matchAll(/<script\b[^>]*>\s*const\s+DATA\s*=\s*(.*?)\s*;\s*<\/script\s*>/gis)];
let embedded=null;
if(matches.length===1){try{embedded=JSON.parse(matches[0][1]);}catch{if(needsV3Scan(html,null,m))throw Error('invalid_embedded_data');}}
if(needsV3Scan(html,embedded,m)) {
  assert.equal(matches.length,1);
  scanOutput(html,embedded);
}
// The immutable source files above are checked before this build-only derivative.
// It lets the authenticated browser identify the exact currently served Git build.
if (!process.argv.includes('--check-only')) {
  assert.equal(process.env.VERCEL_ENV, 'production');
  assert.equal(process.env.VERCEL_GIT_COMMIT_REF, 'production');
  assert.match(process.env.VERCEL_GIT_COMMIT_SHA || '', /^[0-9a-f]{40}$/);
  fs.writeFileSync('public/version.json', JSON.stringify({...version, productionSHA: process.env.VERCEL_GIT_COMMIT_SHA}));
}
console.log(JSON.stringify({verified: true, sourceSHA: m.sourceSHA, runId: m.runId, priceDateRange: m.priceDateRange}));
}
if(require.main===module)verifyRelease();
module.exports={scanOutput,needsV3Scan,BANNED_WORDS,DISCLAIMER};
