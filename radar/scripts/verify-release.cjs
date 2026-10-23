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
assert([2,3].includes(m.schemaVersion));
const checkOnly=process.argv.includes('--check-only');
const diagnostic=m.publicationAuthorized===false;
if(diagnostic&&(!checkOnly||!['live-notion-dry-run','offline-rehearsal'].includes(m.purpose)))throw Error('diagnostic_publication_forbidden');
if(['live-notion-dry-run','offline-rehearsal'].includes(m.purpose)&&!diagnostic)throw Error('diagnostic_authorization_invalid');
checkSensitive(m);
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
checkSensitive(version);
assert.equal(version.sourceSHA, m.sourceSHA);
assert.equal(version.dataSHA256, m.dataSHA256);
const html=fs.readFileSync('public/index.html','utf8');
// Old v2 releases remain usable for rollback. Every v3-rendered page has this
// stable slot, including a v3 interface rendering legacy DATA.
const matches=[...html.matchAll(/<script\b[^>]*>\s*const\s+DATA\s*=\s*(.*?)\s*;\s*<\/script\s*>/gis)];
let embedded=null;
if(matches.length===1){try{embedded=JSON.parse(matches[0][1]);}catch{if(needsV3Scan(html,null,m))throw Error('invalid_embedded_data');}}
if(embedded)checkSensitive(embedded);
const operationSlots=[...html.matchAll(/<script id="radar-operations">const OPERATIONS=(.*?);<\/script>/gs)];
if(operationSlots.length!==1)throw Error('release_status_slot_mismatch');
assert.deepEqual(JSON.parse(operationSlots[0][1]),version);
if(needsV3Scan(html,embedded,m)) {
  assert.equal(matches.length,1);
  scanOutput(html,embedded);
}
if(m.schemaVersion===3) {
  if(!embedded?.meta?.notion||!embedded.meta.schedule)throw Error('v3_metadata_missing');
  const snapshotPath='research-snapshot.json';
  if(!fs.lstatSync(snapshotPath).isFile())throw Error('research_snapshot_file_type');
  const bytes=fs.readFileSync(snapshotPath), hash=crypto.createHash('sha256').update(bytes).digest('hex');
  if(hash!==m.researchSnapshotSHA256||hash!==embedded.meta.notion.snapshotSHA256)throw Error('research_snapshot_hash_mismatch');
  const snapshot=JSON.parse(bytes);checkSensitive(snapshot);checkSnapshot(snapshot,m.fixedClock);
  const n=embedded.meta.notion;
  assert.deepEqual(m.notion,{source:n.source,requests:n.requests,counts:n.counts,fallbackTables:n.fallbackTables,
    warningCount:n.warnings.length,quarantinedCount:n.quarantined.length});
  checkSchedule(embedded.meta.schedule,m.fixedClock);
} else if(embedded?.meta&&Object.hasOwn(embedded.meta,'notion'))throw Error('notion_release_requires_v3');
if(embedded?.meta&&['fixture','offline','reviewPreview'].some(key=>embedded.meta[key])&&!(diagnostic&&m.purpose==='offline-rehearsal'))throw Error('release_data_invalid');
const history=JSON.parse(fs.readFileSync('history.json','utf8'));checkSensitive(history);
if(history.schemaVersion!==1||!Array.isArray(history.days)||history.days.length>8)throw Error('history_invalid');
// The immutable source files above are checked before this build-only derivative.
// It lets the authenticated browser identify the exact currently served Git build.
if (!checkOnly) {
  assert.equal(process.env.VERCEL_ENV, 'production');
  assert.equal(process.env.VERCEL_GIT_COMMIT_REF, 'production');
  assert.match(process.env.VERCEL_GIT_COMMIT_SHA || '', /^[0-9a-f]{40}$/);
  fs.writeFileSync('public/version.json', JSON.stringify({...version, productionSHA: process.env.VERCEL_GIT_COMMIT_SHA}));
}
console.log(JSON.stringify({verified: true, sourceSHA: m.sourceSHA, runId: m.runId, priceDateRange: m.priceDateRange}));
}
function checkSensitive(value) {
  const keys=new Set(['cookie','cookies','cookiejar','setcookie','headers','requestheaders','responseheaders',
    'authorization','password','passwd','credential','credentials','token','accesstoken','refreshtoken','idtoken',
    'apikey','secret','clientsecret','crumb','raw','rawbody','rawpayload','payload','httpbody','responsebody',
    'requestbody','documents','chart','quoteresponse','body','rawresponse','httpresponse','authentication','apitoken',
    'createdby','lasteditedby','requestid','notiontoken']);
  function walk(item) {
    if(typeof item==='string'&&(SECRET_VALUE.test(item)||/(?:AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{12,}|https?:\/\/[^\s/<>]+:[^\s/<>]+@|[?&](?:token|access_token|api_key|apikey|crumb|signature|x-amz-signature)=)/i.test(item)))throw Error('sensitive_release_value');
    if(item&&typeof item==='object')for(const [key,child] of Object.entries(item)) {
      if(keys.has(key.toLowerCase().replace(/[^a-z0-9]/g,'')))throw Error('sensitive_release_field');
      walk(child);
    }
  }
  walk(value);
}
function checkSnapshot(snapshot,clock) {
  const tables=['industries','chokepoints','companies','financials','daily','weekly'];
  const exact=(object,keys)=>object&&typeof object==='object'&&!Array.isArray(object)&&Object.keys(object).sort().join('|')===[...keys].sort().join('|');
  const aware=value=>typeof value==='string'&&/(Z|[+-]\d\d:\d\d)$/.test(value)&&Number.isFinite(Date.parse(value));
  if(!exact(snapshot,['schemaVersion','contractVersion','notionVersion','builtAt','tables'])||snapshot.schemaVersion!==1||snapshot.contractVersion!=='3.0'||snapshot.notionVersion!=='2026-03-11'||snapshot.builtAt!==clock||!aware(clock)||!exact(snapshot.tables,tables))throw Error('research_snapshot_schema');
  for(const table of Object.values(snapshot.tables)) {
    if(!exact(table,['source','fetchedAt','schemaHash','rows'])||!['notion','last_good'].includes(table.source)||!aware(table.fetchedAt)||!/^sha256:[0-9a-f]{64}$/.test(table.schemaHash)||!Array.isArray(table.rows))throw Error('research_snapshot_table');
    let previous=null;
    for(const row of table.rows) {
      if(!exact(row,['id','created_time','last_edited_time','props'])||typeof row.id!=='string'||(previous!==null&&row.id<=previous)||typeof row.created_time!=='string'||typeof row.last_edited_time!=='string'||!row.props||typeof row.props!=='object'||Array.isArray(row.props))throw Error('research_snapshot_row');
      previous=row.id;
    }
  }
}
function checkSchedule(schedule,clock) {
  if(!schedule||!Array.isArray(schedule.cronUtc)||!schedule.cronUtc.length||!Number.isInteger(schedule.lateAfterMinutes)||schedule.lateAfterMinutes<0)throw Error('release_schedule_missing');
  const now=Date.parse(clock), midnight=new Date(now);midnight.setUTCHours(0,0,0,0);
  const candidates=[];
  for(const expression of schedule.cronUtc) {
    const match=typeof expression==='string'&&/^(\d{1,2}) (\d{1,2}) \* \* ([0-6])(?:-([0-6]))?$/.exec(expression);
    if(!match)throw Error('invalid_schedule_cron');
    const minute=Number(match[1]),hour=Number(match[2]),first=Number(match[3]),last=Number(match[4]??match[3]);
    if(minute>59||hour>23||first>last)throw Error('invalid_schedule_cron');
    for(let offset=0;offset<8;offset++) {
      const instant=new Date(midnight.getTime()+offset*86400000);instant.setUTCHours(hour,minute);
      if(instant.getUTCDay()>=first&&instant.getUTCDay()<=last&&instant.getTime()>now)candidates.push(instant.getTime());
    }
  }
  if(Date.parse(schedule.nextRunAt)!==Math.min(...candidates))throw Error('release_schedule_mismatch');
}
if(require.main===module)verifyRelease();
module.exports={scanOutput,needsV3Scan,BANNED_WORDS,DISCLAIMER};
