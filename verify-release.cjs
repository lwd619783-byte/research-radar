// Vercel builds only the allowlisted static output, never repository evidence.
const fs = require('node:fs');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
// production_release.py embeds the tracked calendar in the shipped verifier.
const REVIEWED_MARKET_CALENDAR = {"exchanges":{"XETR":{"close":"17:30","confidenceByYear":{"2026":"official","2027":"official"},"earlyCloses":{},"holidays":["2026-01-01","2026-04-03","2026-04-06","2026-05-01","2026-12-24","2026-12-25","2026-12-31","2027-01-01","2027-03-26","2027-03-29","2027-12-24","2027-12-31"],"open":"09:00","sources":["https://www.cashmarket.deutsche-boerse.com/cash-en/trading/trading-calendar-and-trading-hours"],"timezone":"Europe/Berlin","validFrom":"2026-01-01","validThrough":"2027-12-31"},"XHKG":{"close":"16:10","confidenceByYear":{"2026":"official","2027":"official"},"earlyCloses":{"2026-02-16":"12:10","2026-12-24":"12:10","2026-12-31":"12:10","2027-02-05":"12:10","2027-12-24":"12:10","2027-12-31":"12:10"},"holidays":["2026-01-01","2026-02-17","2026-02-18","2026-02-19","2026-04-03","2026-04-06","2026-04-07","2026-05-01","2026-05-25","2026-06-19","2026-07-01","2026-10-01","2026-10-19","2026-12-25","2027-01-01","2027-02-08","2027-02-09","2027-03-26","2027-03-29","2027-04-05","2027-05-13","2027-06-09","2027-07-01","2027-09-16","2027-10-01","2027-10-08","2027-12-27"],"open":"09:30","sources":["https://www.hkex.com.hk/News/HKEX-Calendar?sc_lang=en","https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Securities-Market"],"timezone":"Asia/Hong_Kong","validFrom":"2026-01-01","validThrough":"2027-12-31"},"XKRX":{"close":"15:30","confidenceByYear":{"2026":"official","2027":"official"},"earlyCloses":{},"holidays":["2026-01-01","2026-02-16","2026-02-17","2026-02-18","2026-03-02","2026-05-01","2026-05-05","2026-05-25","2026-06-03","2026-07-17","2026-08-17","2026-09-24","2026-09-25","2026-10-05","2026-10-09","2026-12-25","2026-12-31","2027-01-01","2027-02-08","2027-02-09","2027-03-01","2027-05-03","2027-05-05","2027-05-13","2027-07-19","2027-08-16","2027-09-14","2027-09-15","2027-09-16","2027-10-04","2027-10-11","2027-12-27","2027-12-31"],"open":"09:00","sources":["https://global.krx.co.kr/contents/GLB/06/0602/0602020204/GLB0602020204T1.jsp","https://www.kasi.re.kr/kor/post/newsMaterial/32031","https://www.kasa.go.kr/prog/plcyBrf/brief/kor/sub01_01_04/view.do?plcyBrfNo=431"],"timezone":"Asia/Seoul","validFrom":"2026-01-01","validThrough":"2027-12-31"},"XNAS":{"close":"16:00","confidenceByYear":{"2026":"official","2027":"rule_based"},"earlyCloses":{"2026-11-27":"13:00","2026-12-24":"13:00","2027-11-26":"13:00"},"holidays":["2026-01-01","2026-01-19","2026-02-16","2026-04-03","2026-05-25","2026-06-19","2026-07-03","2026-09-07","2026-11-26","2026-12-25","2027-01-01","2027-01-18","2027-02-15","2027-03-26","2027-05-31","2027-06-18","2027-07-05","2027-09-06","2027-11-25","2027-12-24"],"model":"exchange_calendars==4.13.2","open":"09:30","sources":["https://www.nasdaqtrader.com/Trader.aspx?id=Calendar","https://github.com/gerrymanoim/exchange_calendars/tree/4.13.2/exchange_calendars"],"timezone":"America/New_York","validFrom":"2026-01-01","validThrough":"2027-12-31"},"XNYS":{"close":"16:00","confidenceByYear":{"2026":"official","2027":"official"},"earlyCloses":{"2026-11-27":"13:00","2026-12-24":"13:00","2027-11-26":"13:00"},"holidays":["2026-01-01","2026-01-19","2026-02-16","2026-04-03","2026-05-25","2026-06-19","2026-07-03","2026-09-07","2026-11-26","2026-12-25","2027-01-01","2027-01-18","2027-02-15","2027-03-26","2027-05-31","2027-06-18","2027-07-05","2027-09-06","2027-11-25","2027-12-24"],"open":"09:30","sources":["https://www.nyse.com/trade/hours-calendars"],"timezone":"America/New_York","validFrom":"2026-01-01","validThrough":"2027-12-31"},"XPAR":{"close":"17:30","confidenceByYear":{"2026":"official","2027":"rule_based"},"earlyCloses":{"2026-12-24":"14:05","2026-12-31":"14:05","2027-12-24":"14:05","2027-12-31":"14:05"},"holidays":["2026-01-01","2026-04-03","2026-04-06","2026-05-01","2026-12-25","2027-01-01","2027-03-26","2027-03-29"],"model":"exchange_calendars==4.13.2","open":"09:00","sources":["https://www.euronext.com/en/trading/trading-hours-holidays","https://github.com/gerrymanoim/exchange_calendars/tree/4.13.2/exchange_calendars"],"timezone":"Europe/Paris","validFrom":"2026-01-01","validThrough":"2027-12-31"},"XSHE":{"close":"15:00","confidenceByYear":{"2026":"official","2027":"provisional"},"earlyCloses":{},"holidays":["2026-01-01","2026-01-02","2026-02-16","2026-02-17","2026-02-18","2026-02-19","2026-02-20","2026-02-23","2026-04-06","2026-05-01","2026-05-04","2026-05-05","2026-06-19","2026-09-25","2026-10-01","2026-10-02","2026-10-05","2026-10-06","2026-10-07"],"open":"09:30","provisionalHolidays":["2027-01-01","2027-02-05","2027-02-08","2027-02-09","2027-02-10","2027-02-11","2027-02-12","2027-04-05","2027-05-03","2027-06-09","2027-09-15","2027-10-01","2027-10-04","2027-10-05","2027-10-06","2027-10-07"],"provisionalMethod":"2027\u519c\u5386\u65e5\u671f\u53ca2026\u4ea4\u6613\u6240\u5047\u671f\u60ef\u4f8b\uff1b\u975e\u6b63\u5f0f\u5e74\u5ea6\u5b89\u6392\uff0c\u4e0d\u4fdd\u8bc1\u8c03\u4f11\u957f\u5ea6\u3002","provisionalNote":"2027\u6625\u828202/05\u201302/12\u6309\u9664\u5915\u8d778\u5929\u60ef\u4f8b\u4f30\u8ba1\uff0c\u5176\u4f59\u5047\u65e5\u540c\u4e3a\u4f30\u8ba1\uff1b\u8bf7\u4e8e2026-12-20\u524d\u590d\u6838\u4ea4\u6613\u6240\u516c\u544a\u3002","reviewBy":"2026-12-20","sources":["https://investor.szse.cn/English/services/trading/calendar/index.html","https://www.hko.gov.hk/en/gts/time/calendar/pdf/files/2027e.pdf"],"timezone":"Asia/Shanghai","validFrom":"2026-01-01","validThrough":"2027-12-31"},"XSHG":{"close":"15:00","confidenceByYear":{"2026":"official","2027":"provisional"},"earlyCloses":{},"holidays":["2026-01-01","2026-01-02","2026-02-16","2026-02-17","2026-02-18","2026-02-19","2026-02-20","2026-02-23","2026-04-06","2026-05-01","2026-05-04","2026-05-05","2026-06-19","2026-09-25","2026-10-01","2026-10-02","2026-10-05","2026-10-06","2026-10-07"],"open":"09:30","provisionalHolidays":["2027-01-01","2027-02-05","2027-02-08","2027-02-09","2027-02-10","2027-02-11","2027-02-12","2027-04-05","2027-05-03","2027-06-09","2027-09-15","2027-10-01","2027-10-04","2027-10-05","2027-10-06","2027-10-07"],"provisionalMethod":"2027\u519c\u5386\u65e5\u671f\u53ca2026\u4ea4\u6613\u6240\u5047\u671f\u60ef\u4f8b\uff1b\u975e\u6b63\u5f0f\u5e74\u5ea6\u5b89\u6392\uff0c\u4e0d\u4fdd\u8bc1\u8c03\u4f11\u957f\u5ea6\u3002","provisionalNote":"2027\u6625\u828202/05\u201302/12\u6309\u9664\u5915\u8d778\u5929\u60ef\u4f8b\u4f30\u8ba1\uff0c\u5176\u4f59\u5047\u65e5\u540c\u4e3a\u4f30\u8ba1\uff1b\u8bf7\u4e8e2026-12-20\u524d\u590d\u6838\u4ea4\u6613\u6240\u516c\u544a\u3002","reviewBy":"2026-12-20","sources":["https://www.sse.com.cn/disclosure/dealinstruc/closed/","https://www.hko.gov.hk/en/gts/time/calendar/pdf/files/2027e.pdf"],"timezone":"Asia/Shanghai","validFrom":"2026-01-01","validThrough":"2027-12-31"},"XTAI":{"close":"13:30","confidenceByYear":{"2026":"official","2027":"provisional"},"earlyCloses":{},"holidays":["2026-01-01","2026-02-12","2026-02-13","2026-02-16","2026-02-17","2026-02-18","2026-02-19","2026-02-20","2026-02-27","2026-04-03","2026-04-06","2026-05-01","2026-06-19","2026-09-25","2026-09-28","2026-10-09","2026-10-23","2026-10-26","2026-12-25"],"open":"09:00","provisionalHolidays":["2027-01-01","2027-02-04","2027-02-05","2027-02-08","2027-02-09","2027-02-10","2027-03-01","2027-04-05","2027-04-30","2027-06-09","2027-09-15","2027-09-28","2027-10-11","2027-10-25","2027-12-31"],"provisionalMethod":"exchange_calendars==4.13.2 XTAI\u9759\u6001\u5bfc\u51fa\uff0c\u5e74\u5ea6\u7279\u6b8a\u4f11\u5e02\u53ef\u80fd\u672a\u6db5\u76d6\u3002","provisionalNote":"\u56fa\u5b9aexchange_calendars==4.13.2\u89c4\u5219\u4f30\u8ba1\uff0c\u6625\u8282\u989d\u5916\u7ed3\u7b97\u65e5\u5f85\u5b98\u65b9\u786e\u8ba4\uff1b\u8bf7\u4e8e2026-12-20\u524d\u590d\u6838TWSE\u516c\u544a\u3002","reviewBy":"2026-12-20","sources":["https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=html","https://www.twse.com.tw/zh/about/news/news/content.html?8a8216d6a0fa351b01a1638507a10203","https://www.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d6a0fa351b01a1638507940202.pdf","https://github.com/gerrymanoim/exchange_calendars/blob/4.13.2/exchange_calendars/exchange_calendar_xtai.py"],"timezone":"Asia/Taipei","validFrom":"2026-01-01","validThrough":"2027-12-31"},"XTKS":{"close":"15:30","confidenceByYear":{"2026":"official","2027":"official"},"earlyCloses":{},"holidays":["2026-01-01","2026-01-02","2026-01-12","2026-02-11","2026-02-23","2026-03-20","2026-04-29","2026-05-04","2026-05-05","2026-05-06","2026-07-20","2026-08-11","2026-09-21","2026-09-22","2026-09-23","2026-10-12","2026-11-03","2026-11-23","2026-12-31","2027-01-01","2027-01-11","2027-02-11","2027-02-23","2027-03-22","2027-04-29","2027-05-03","2027-05-04","2027-05-05","2027-07-19","2027-08-11","2027-09-20","2027-09-23","2027-10-11","2027-11-03","2027-11-23","2027-12-31"],"open":"09:00","sources":["https://www.jpx.co.jp/english/corporate/about-jpx/calendar/index.html","https://www.jpx.co.jp/equities/trading/domestic/01.html"],"timezone":"Asia/Tokyo","validFrom":"2026-01-01","validThrough":"2027-12-31"}},"modelExport":{"version":"4.13.2","wheelSHA256":"fc5a2ad0d61b5c3a6539a3061cd4cbb55c59f4a903455cec7926e4b798919996"},"reviewedAt":"2026-10-23","schemaVersion":1,"symbolExchanges":{"ANET":"XNYS","ASML":"XNAS","AVGO":"XNAS","COHR":"XNYS","ETN":"XNYS","GEV":"XNYS","LITE":"XNAS","MOD":"XNYS","MRVL":"XNAS","MU":"XNAS","NVDA":"XNAS","TSM":"XNYS","VRT":"XNYS","^GSPC":"XNYS","^HSI":"XHKG","^IXIC":"XNAS","^SOX":"XNAS"},"validThrough":"2027-12-31","warningDays":60};
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
checkIndependentCloseProofs(m,embedded);
checkProviderCloseConflicts(embedded);
checkYahooMetaClose(m, embedded);
const operationSlots=[...html.matchAll(/<script id="radar-operations">const OPERATIONS=(.*?);<\/script>/gs)];
if(operationSlots.length!==1)throw Error('release_status_slot_mismatch');
assert.deepEqual(JSON.parse(operationSlots[0][1]),version);
checkOperationalSchedule(m,embedded,version);
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
function checkIndependentCloseProofs(manifest,data) {
  // This is an additional, narrow certificate type. The provider-only path and
  // every original date/receipt/publication check above remain unchanged.
  const rows=Array.isArray(data?.companies)?data.companies:[];
  const selected=rows.filter(row=>row?.provenance?.daily&&Object.hasOwn(row.provenance.daily,'independentCloseProof'));
  const present=Object.hasOwn(manifest,'independentCloseProofs');
  if(!present&&!selected.length)return;
  const fail=()=>{throw Error('independent_close_proof_binding_mismatch');};
  const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)
    &&Object.keys(value).sort().join('|')===[...keys].sort().join('|');
  const canonical=value=>JSON.stringify(sort(value));
  function sort(value){if(Array.isArray(value))return value.map(sort);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(key=>[key,sort(value[key])]));return value;}
  const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
  const validDay=day=>typeof day==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(day)
    &&Number.isFinite(Date.parse(day+'T00:00:00Z'))&&new Date(day+'T00:00:00Z').toISOString().slice(0,10)===day;
  function micros(value) {
    const match=typeof value==='string'&&/^(\d{4}-\d\d-\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?(Z|[+-]\d\d:\d\d)$/.exec(value);
    if(!match||!validDay(match[1])||Number(match[2])>23||Number(match[3])>59||Number(match[4])>59)fail();
    const zone=match[6],hour=zone==='Z'?0:Number(zone.slice(1,3)),minute=zone==='Z'?0:Number(zone.slice(4,6));
    if(hour>23||minute>59)fail();
    const offset=(hour*60+minute)*(zone.startsWith('-')?-1:1);
    const base=Date.parse(match[1]+'T'+match[2]+':'+match[3]+':'+match[4]+'Z')-offset*60000;
    return BigInt(base)*1000n+BigInt((match[5]||'').padEnd(6,'0'));
  }
  const decimal=value=>typeof value==='string'&&/^(?:0|[1-9]\d*)(?:\.\d*[1-9])?$/.test(value)&&Number.isFinite(Number(value))&&Number(value)>0;
  const keys=['schemaVersion','method','symbol','exchange','currency','day','timezone','sourcePhase',
    'officialSourceUrl','yahooSourceUrl','officialResponseSHA256','yahooResponseSHA256','yahooRecordSHA256',
    'officialReceivedAt','yahooReceivedAt','parserReceivedAt','checkedAt','execution','officialResponseDate',
    'officialTitle','officialRow','close','adjclose','high','barTimestamp','sessionStart','sessionEnd','checksum'];
  const proofs=manifest.independentCloseProofs;
  if(!exact(proofs,['2383.TW'])||selected.length!==1||rows.filter(row=>row.sym==='2383.TW').length!==1)fail();
  const p=proofs['2383.TW'],row=selected[0],daily=row.provenance.daily;
  if(!exact(p,keys)||p.schemaVersion!==1||p.method!=='twse-independent-close'||p.symbol!=='2383.TW'
    ||p.exchange!=='XTAI'||p.currency!=='TWD'||p.timezone!=='Asia/Taipei'||p.sourcePhase!=='unknown'||!validDay(p.day))fail();
  if(!exact(p.execution,['GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT'])
    ||p.execution.GITHUB_SHA!==manifest.sourceSHA||p.execution.GITHUB_RUN_ID!==manifest.runId
    ||p.execution.GITHUB_RUN_ATTEMPT!=='1'||! /^[0-9a-f]{40}$/.test(p.execution.GITHUB_SHA)
    ||! /^[1-9][0-9]*$/.test(p.execution.GITHUB_RUN_ID))fail();
  const {checksum,...content}=p;
  if(!/^[0-9a-f]{64}$/.test(checksum)||sha(canonical(content))!==checksum
    ||['officialResponseSHA256','yahooResponseSHA256','yahooRecordSHA256'].some(key=>! /^[0-9a-f]{64}$/.test(p[key])))fail();
  const date=p.day.replaceAll('-',''),year=Number(p.day.slice(0,4))-1911,month=Number(p.day.slice(5,7));
  const title=typeof p.officialTitle==='string'&&p.officialTitle.length<=160
    &&/^(\d{2,3})年(\d{1,2})月2383台光電各日成交資訊$/.exec(p.officialTitle.replace(/\s/g,''));
  if(p.officialSourceUrl!=='https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date='+date+'&stockNo=2383&response=json'
    ||p.yahooSourceUrl!=='https://query1.finance.yahoo.com/v8/finance/chart/2383.TW?range=5y&interval=1d&includeAdjustedClose=true'
    ||p.officialResponseDate!==date||!title||Number(title[1])!==year||Number(title[2])!==month
    ||!exact(p.officialRow,['date','close','high','note'])||p.officialRow.date!==year+'/'+p.day.slice(5).replace('-','/')
    ||p.officialRow.note!==''||!decimal(p.close)||!decimal(p.adjclose)||!decimal(p.high)
    ||p.close!==p.adjclose||p.close!==p.officialRow.close||p.high!==p.officialRow.high||Number(p.high)<Number(p.close))fail();
  const now=micros(manifest.fixedClock),official=micros(p.officialReceivedAt),yahoo=micros(p.yahooReceivedAt),
    parser=micros(p.parserReceivedAt),checked=micros(p.checkedAt),close=micros(p.day+'T13:30:00+08:00');
  // This independent route certifies only today's normal Taiwan close. A
  // rewritten output calendar must not turn a fresh receipt into an old close.
  if(new Date(Number(now/1000n)+8*3600000).toISOString().slice(0,10)!==p.day)fail();
  const age=36n*3600n*1000000n;
  if(official<close||yahoo<close||official>checked||yahoo>parser||parser>checked||checked>now
    ||now-official>age||now-yahoo>age||now-parser>age)fail();
  const epochKeys=['barTimestamp','sessionStart','sessionEnd'];
  if(epochKeys.some(key=>!Number.isSafeInteger(p[key])||p[key]<=0)
    ||p.sessionEnd<=p.sessionStart||p.sessionEnd-p.sessionStart>12*3600||BigInt(p.sessionEnd)*1000000n<close
    ||p.barTimestamp<=p.sessionEnd||BigInt(p.barTimestamp)*1000000n>yahoo
    ||epochKeys.some(key=>new Date((p[key]+8*3600)*1000).toISOString().slice(0,10)!==p.day))fail();
  const weekday=new Date(p.day+'T00:00:00Z').getUTCDay(),calendar=row.marketCalendar||{};
  if(weekday===0||weekday===6||['2026-10-23','2026-10-26'].includes(p.day)
    ||calendar.exchange!=='XTAI'||calendar.confidence!=='official'||calendar.expectedCompletedDate!==p.day||calendar.quoteDate!==p.day)fail();
  try{assert.deepEqual(daily.independentCloseProof,p);}catch{fail();}
  const selection=daily.snapshotSelection||{};
  if(row.sym!=='2383.TW'||row.cur!=='TWD'||['ld','metricAsOf','priceAsOf'].some(key=>row[key]!==p.day)
    ||daily.asOf!==p.day||daily.src!=='yahoo'||daily.phase!=='closed'||daily.returnBasis!=='yahoo-adjclose'
    ||daily.timezone!=='Asia/Taipei'||daily.receivedAt!==p.parserReceivedAt
    ||selection.sourcePhase!=='unknown'||selection.sourceAsOf!==p.day||selection.selectedDate!==p.day
    ||row.pricePhase!=='closed'||row.priceSource!=='yahoo'||row.priceObservedAt!==null
    ||row.priceSelection?.useQuote!==false||typeof row.price!=='number'||String(row.price)!==p.close)fail();
}
function checkProviderCloseConflicts(data) {
  const method = 'latest-completed-per-market-provider-close-conflict';
  const validDay = day => typeof day === 'string' && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(day)
    && !day.startsWith('0000-') && Number.isFinite(Date.parse(day + 'T00:00:00Z'))
    && new Date(day + 'T00:00:00Z').toISOString().slice(0, 10) === day;
  function receiptSeconds(value) {
    const match = typeof value === 'string'
      && /^(([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2}))(?:\.([0-9]{1,6}))?(Z|[+-][0-9]{2}:[0-9]{2})$/.exec(value);
    if (!match || match[0] !== value || !validDay(match[2])
        || Number(match[3]) > 23 || Number(match[4]) > 59 || Number(match[5]) > 59) return NaN;
    const zone = match[7];
    if (zone !== 'Z' && (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4, 6)) > 59)) return NaN;
    return Date.parse(match[1] + zone) / 1000 + (match[6] ? Number('0.' + match[6]) : 0);
  }
  for (const row of Array.isArray(data?.companies) ? data.companies : []) {
    const daily = row?.provenance?.daily, selection = daily?.snapshotSelection;
    const marked = row != null && Object.hasOwn(row, 'providerCloseConflict');
    const fallback = selection?.method === method;
    if (!marked && !fallback) continue;
    const marker = row.providerCloseConflict, calendar = row.marketCalendar;
    if (!marked || !fallback || !marker || typeof marker !== 'object' || Array.isArray(marker)
        || Object.keys(marker).length !== 3 || !['date', 'sessionEnd', 'receivedAt'].every(key => Object.hasOwn(marker, key))) {
      throw Error('provider_close_conflict_binding_mismatch');
    }
    const selected = row.ld, conflict = marker.date;
    if (!validDay(selected) || !validDay(conflict) || conflict <= selected
        || selection.sourceAsOf !== conflict || selection.sourcePhase !== 'closed' || daily.phase !== 'closed'
        || [selection.selectedDate, row.metricAsOf, daily.asOf, calendar?.quoteDate,
            calendar?.expectedCompletedDate].some(value => value !== selected)
        || !['official', 'rule_based'].includes(calendar?.confidence) || daily.receivedAt !== marker.receivedAt
        || !Number.isFinite(marker.sessionEnd) || marker.sessionEnd <= 0 || marker.sessionEnd > Number.MAX_SAFE_INTEGER
        || !(marker.sessionEnd <= receiptSeconds(marker.receivedAt))) {
      throw Error('provider_close_conflict_binding_mismatch');
    }
  }
}
function closeProofMicros(value) {
  const match = typeof value === 'string'
    && /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match || match[0] !== value || !closeProofDay(match[1])
      || Number(match[2]) > 23 || Number(match[3]) > 59 || Number(match[4]) > 59) return null;
  const zone = match[6];
  if (zone !== 'Z' && (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4, 6)) > 59)) return null;
  const whole = Date.parse(`${match[1]}T${match[2]}:${match[3]}:${match[4]}${zone}`);
  return BigInt(whole) * 1000n + BigInt((match[5] || '').padEnd(6, '0'));
}

function closeProofDay(day) {
  if (typeof day !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(day) || day.startsWith('0000-')) return false;
  const instant = Date.parse(day + 'T00:00:00Z');
  return Number.isFinite(instant) && new Date(instant).toISOString().slice(0, 10) === day;
}

function calendarExchange(calendar, symbol) {
  if (typeof symbol !== 'string') return null;
  if (Object.hasOwn(calendar.symbolExchanges, symbol)) return calendar.symbolExchanges[symbol];
  const bySuffix = {SS: 'XSHG', SZ: 'XSHE', HK: 'XHKG', TW: 'XTAI', KS: 'XKRX', T: 'XTKS', DE: 'XETR', PA: 'XPAR'};
  const dot = symbol.lastIndexOf('.');
  const suffix = symbol.slice(dot + 1);
  return dot >= 0 && Object.hasOwn(bySuffix, suffix) ? bySuffix[suffix] : null;
}

function calendarSessionBounds(spec, day, clock) {
  const confidence = date => spec.confidenceByYear[date.slice(0, 4)];
  const trusted = date => spec.validFrom <= date && date <= spec.validThrough
    && ['official', 'rule_based'].includes(confidence(date));
  const midnight = date => Date.parse(date + 'T00:00:00Z');
  const shift = (date, days) => new Date(midnight(date) + days * 86400000).toISOString().slice(0, 10);
  const session = date => {
    const weekday = new Date(midnight(date)).getUTCDay();
    return weekday > 0 && weekday < 6 && !spec.holidays.includes(date);
  };
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: spec.timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  const local = seconds => {
    const parts = Object.fromEntries(formatter.formatToParts(seconds * 1000).map(({type, value}) => [type, value]));
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
  };
  const localDay = seconds => local(seconds).slice(0, 10);
  function sessionTime(date, time) {
    const wanted = `${date}T${time}:00`;
    const nominal = Date.parse(wanted + 'Z') / 1000;
    const offset = Date.parse(local(nominal) + 'Z') / 1000 - nominal;
    const instant = nominal - offset;
    return local(instant) === wanted ? instant : NaN;
  }
  const clockSeconds = Number(clock / 1000000n);
  const today = localDay(clockSeconds);
  if (!trusted(today) || !trusted(day) || !session(day)) return null;
  const closingTime = date => sessionTime(date, spec.earlyCloses[date] || spec.close);
  const sessionClose = closingTime(day);
  let expected = null;
  for (let offset = 0; offset < 32; offset++) {
    const candidate = shift(today, -offset);
    if (!trusted(candidate)) return null;
    if (session(candidate) && closingTime(candidate) <= clockSeconds) {
      expected = candidate;
      break;
    }
  }
  if (expected !== day) return null;
  for (let offset = 1; offset <= 32; offset++) {
    const next = shift(day, offset);
    if (!trusted(next)) return null;
    if (session(next)) return {sessionClose, nextSessionOpen: sessionTime(next, spec.open),
      confidence: confidence(today), localDay};
  }
  return null;
}

function roundedClosePrice(price) {
  const digits = price < 10 ? 3 : 2;
  const fixed = price.toFixed(digits);
  // An exact halfway binary float has an odd numerator after scaling by
  // 2^(digits+1). Since 5^digits is 1 mod 4, remainder 1 rounds down to even.
  const numerator = price * 2 ** (digits + 1);
  if (Number.isSafeInteger(numerator) && numerator % 4 === 1) {
    return Number(`${BigInt(fixed.replace('.', '')) - 1n}e-${digits}`);
  }
  return Number(fixed);
}

function checkYahooMetaClose(manifest, data, calendar = REVIEWED_MARKET_CALENDAR) {
  const source = 'yahoo-meta-close';
  const proofKeys = ['date', 'price', 'marketTime', 'sessionClose', 'nextSessionOpen', 'receivedAt'];
  const positive = value => Number.isFinite(value) && value > 0 && value <= Number.MAX_SAFE_INTEGER;
  const maxReceiptAge = 36n * 3600n * 1000000n;
  const fail = () => { throw Error('yahoo_meta_close_binding_mismatch'); };
  for (const row of Array.isArray(data?.companies) ? data.companies : []) {
    const daily = row?.provenance?.daily;
    const marked = daily != null && Object.hasOwn(daily, 'yahooMetaClose');
    if (!marked && daily?.src !== source && row?.priceSource !== source) continue;
    const proof = daily?.yahooMetaClose;
    if (daily?.src !== source || !proof || typeof proof !== 'object' || Array.isArray(proof)
        || Object.keys(proof).length !== proofKeys.length || !proofKeys.every(key => Object.hasOwn(proof, key))
        || !closeProofDay(proof.date) || !positive(proof.price)
        || ['marketTime', 'sessionClose', 'nextSessionOpen'].some(key => !Number.isSafeInteger(proof[key]) || proof[key] <= 0)
        || !calendar) fail();
    const received = closeProofMicros(proof.receivedAt), clock = closeProofMicros(manifest.fixedClock);
    if (received === null || clock === null || BigInt(proof.marketTime) * 1000000n > received
        || received > clock || clock - received > maxReceiptAge
        || proof.marketTime < proof.sessionClose || proof.marketTime >= proof.nextSessionOpen) fail();
    const exchange = calendarExchange(calendar, row.sym), spec = calendar.exchanges[exchange];
    if (!spec || exchange === 'XTAI') fail();
    const bounds = calendarSessionBounds(spec, proof.date, clock);
    if (!bounds || proof.sessionClose !== bounds.sessionClose || proof.nextSessionOpen !== bounds.nextSessionOpen) fail();
    const annotation = row.marketCalendar, selection = daily.snapshotSelection;
    if (annotation?.exchange !== exchange || annotation?.confidence !== bounds.confidence
        || daily.timezone !== spec.timezone || annotation.timezone !== spec.timezone
        || daily.phase !== 'closed' || daily.receivedAt !== proof.receivedAt || daily.returnBasis !== 'yahoo-adjclose'
        || Object.hasOwn(daily, 'independentCloseProof') || Object.hasOwn(row, 'providerCloseConflict')
        || selection?.method !== 'latest-completed-per-market' || selection.sourcePhase !== 'closed'
        || ['r1d', 'r5', 'r20', 'r60', 'ytd', 'dd52', 'hi52'].some(key => row[key] != null)
        || [row.ld, row.metricAsOf, daily.asOf, annotation.quoteDate, annotation.expectedCompletedDate,
            selection.selectedDate, selection.sourceAsOf].some(value => value !== proof.date)) fail();
    const priceSelection = row.priceSelection;
    if (row.priceSource === source) {
      if (row.priceAsOf !== proof.date || row.pricePhase !== 'closed' || row.priceObservedAt !== null
          || priceSelection?.useQuote !== false || !positive(row.price)
          || row.price !== roundedClosePrice(proof.price)) fail();
    } else {
      const boundary = BigInt(proof.nextSessionOpen) * 1000000n;
      const observed = closeProofMicros(row.priceObservedAt);
      if (typeof row.priceSource !== 'string' || !row.priceSource || !positive(row.price)
          || row.pricePhase !== 'intraday' || priceSelection?.useQuote !== true
          || priceSelection.boundaryKind !== 'later_session_start_upper_bound'
          || closeProofMicros(priceSelection.completedBoundaryUTC) !== boundary
          || observed === null || observed <= boundary || observed > clock
          || row.priceAsOf !== bounds.localDay(Number(observed / 1000000n))) fail();
    }
  }
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
  if(!schedule||!Array.isArray(schedule.cronUtc)||!schedule.cronUtc.length||!Number.isInteger(schedule.lateAfterMinutes)||(schedule.lateAfterMinutes<0||schedule.lateAfterMinutes>180))throw Error('release_schedule_missing');
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
  return Math.min(...candidates);
}
function checkOperationalSchedule(manifest,data,version) {
  const owns=Object.hasOwn(manifest,'scheduleAdmission');
  if(!owns) {
    if(Object.hasOwn(version,'schedule'))throw Error('publication_schedule_without_ownership');
    return; // Legacy releases retain the original DATA fixed-clock contract.
  }
  const record=manifest.scheduleAdmission, keys=['schemaVersion','kind','slot','plannedAt','createdAt','sourceSHA','runId'];
  const slots={'weekday-0845':[8,45,[1,2,3,4,5]],'weekday-1215':[12,15,[1,2,3,4,5]],
    'weekday-1815':[18,15,[1,2,3,4,5]],'monday-0650':[6,50,[1]]};
  const aware=value=>typeof value==='string'&&/(Z|[+-]\d\d:\d\d)$/.test(value)&&Number.isFinite(Date.parse(value));
  const beijing=instant=>new Date(instant+8*3600000).toISOString().slice(0,19)+'+08:00';
  if(!record||typeof record!=='object'||Array.isArray(record)||Object.keys(record).sort().join('|')!==keys.sort().join('|')
    ||record.schemaVersion!==1||!['schedule','external_schedule'].includes(record.kind)||typeof record.slot!=='string'||!Object.hasOwn(slots,record.slot)
    ||typeof record.sourceSHA!=='string'||! /^[0-9a-f]{40}$/.test(record.sourceSHA)
    ||typeof record.runId!=='string'||! /^[0-9]+$/.test(record.runId)
    ||record.sourceSHA!==manifest.sourceSHA||record.runId!==manifest.runId
    ||!aware(record.createdAt)||!aware(record.plannedAt)||!aware(manifest.fixedClock))throw Error('schedule_publication_invalid');
  const created=Date.parse(record.createdAt),fixed=Date.parse(manifest.fixedClock),local=new Date(created+8*3600000);
  if(created>fixed)throw Error('schedule_publication_after_collection');
  const [hour,minute,days]=slots[record.slot];
  let planned=Date.UTC(local.getUTCFullYear(),local.getUTCMonth(),local.getUTCDate(),hour,minute)-8*3600000;
  if(record.kind==='external_schedule') {
    if(!days.includes(local.getUTCDay())||created<planned||created-planned>180*60000)throw Error('external_schedule_outside_slot');
  } else {
    for(let i=0;i<8;i++) {
      if(planned<=created&&days.includes(new Date(planned+8*3600000).getUTCDay()))break;
      planned-=86400000;
    }
  }
  if(record.plannedAt!==beijing(planned))throw Error('schedule_publication_slot_mismatch');
  const schedule=data?.meta?.schedule;
  if(schedule==null&&manifest.schemaVersion<3) {
    if(Object.hasOwn(version,'schedule'))throw Error('publication_schedule_without_data_schedule');
    return;
  }
  if(!schedule||Object.keys(schedule).sort().join('|')!==['cronUtc','lateAfterMinutes','nextRunAt'].sort().join('|'))throw Error('publication_schedule_missing');
  checkSchedule(schedule,manifest.fixedClock);
  const next=checkSchedule(version.schedule,record.plannedAt);
  assert.deepEqual(version.schedule,{cronUtc:schedule.cronUtc,nextRunAt:beijing(next),lateAfterMinutes:schedule.lateAfterMinutes},
    'publication_schedule_mismatch');
}
if(require.main===module)verifyRelease();
module.exports={scanOutput,needsV3Scan,BANNED_WORDS,DISCLAIMER,checkIndependentCloseProofs,checkYahooMetaClose};
