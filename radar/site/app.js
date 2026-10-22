(()=>{'use strict';
const D=DATA,html=document.documentElement;html.classList.remove('no-js');
const OP=typeof OPERATIONS==='undefined'?null:OPERATIONS;
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>Array.from(r.querySelectorAll(s));
const store={get(k,d){try{const v=localStorage.getItem(k);return v==null?d:v}catch(e){return d}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
const S={theme:store.get('ar-theme','dark'),conv:store.get('ar-conv','cn'),metric:'r20',view:'map',indF:'all',mktF:'all',level:'all',sel:null,cpInd:null,sort:{k:'r20',d:-1},range:'6m',drawer:null,drawerType:null};
html.dataset.theme=S.theme;html.dataset.conv=S.conv;

/* ---------- constants ---------- */
const DIMS=[{k:0,n:'景气度',c:'var(--d1)'},{k:1,n:'业绩兑现',c:'var(--d2)'},{k:2,n:'卡点强度',c:'var(--d3)'},{k:3,n:'估值位置',c:'var(--d4)'}];
const IND_C={'AI网络与光互连':'#8b7bff','AI核心半导体':'#45c4ff','PCB与覆铜板':'#ffb020','电力与数据中心':'#2dd4bf'},IND_PAL=['#8b7bff','#45c4ff','#ffb020','#2dd4bf','#f472b6','#a3e635'];
const IC=n=>IND_C[n]||'#8e95a5';
const TIGHT={'🔴极紧':{k:'t1',l:'极紧',r:0},'🟠偏紧':{k:'t2',l:'偏紧',r:1},'🟢缓解中':{k:'t3',l:'缓解中',r:2}};
const TC={t1:'var(--tight)',t2:'var(--warm)',t3:'var(--ease)'};
const METRICS=[{k:'r5',l:'近5日',dom:.12},{k:'r20',l:'近20日',dom:.3},{k:'r60',l:'近60日',dom:.45},{k:'ytd',l:'年初至今',dom:1.2},{k:'dd52',l:'距52周高点',dom:.6,neg:true},{k:'revg',l:'营收同比',dom:1},{k:'earng',l:'净利同比',dom:2}];
const CUR={CNY:'¥',HKD:'HK$',USD:'$',TWD:'NT$',KRW:'₩',JPY:'JP¥',EUR:'€'};
const WD='日一二三四五六',MINUS='−',TODAY=D.meta.today,ASOF=D.meta.asOf,WK=D.meta.weekly||{},REPO=D.meta.repoUrl||'',STALE=D.meta.stale||[];

/* ---------- icons ---------- */
const I=(p,s)=>`<svg width="${s||14}" height="${s||14}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
const ICON={
  search:I('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',15),
  sun:I('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',16),
  moon:I('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',16),
  ext:I('<path d="M7 17 17 7M8 7h9v9"/>',13),
  x:I('<path d="M18 6 6 18M6 6l12 12"/>',16),
  hot:I('<path d="M12 22c4.4 0 7.5-2.9 7.5-7.2 0-3.1-2-5.6-3.6-7.2-.3 2-1.5 3.1-2.6 3.1.5-3.1-1-6.2-4.1-8.2 0 3.1-1.5 5.1-3.1 6.7C4.6 10.8 4.5 12.6 4.5 14.8 4.5 19.1 7.6 22 12 22z"/>',12),
  watch:I('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',12),
  low:I('<path d="M5 12h14"/>',12),
  bolt:I('<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',14),
  alert:I('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',14),
  target:I('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',14),
  cal:I('<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',14),
  arrow:I('<path d="M5 12h14M13 6l6 6-6 6"/>',14),
  left:I('<path d="M15 18l-6-6 6-6"/>',16),right:I('<path d="M9 18l6-6-6-6"/>',16),
  book:I('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',14),
  radar:I('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/>',14),
  up:I('<path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/>',15),
  down:I('<path d="M3 7l6 6 4-4 8 8"/><path d="M14 17h7v-7"/>',15),
  thermo:I('<path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z"/>',14),
  grid:I('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',14)
};

/* ---------- helpers ---------- */
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fin=v=>typeof v==='number'&&Number.isFinite(v);
function pct(v,dp){if(!fin(v))return'—';const a=Math.abs(v*100);const d=dp!=null?dp:2;return(v>0?'+':v<0?MINUS:'')+a.toFixed(d)+'%'}
const ud=v=>!fin(v)?'':v>0?'up':v<0?'down':'';
const mean=a=>{a=a.filter(fin);return a.length?a.reduce((s,v)=>s+v,0)/a.length:null};
const median=a=>{a=a.filter(fin).sort((x,y)=>x-y);if(!a.length)return null;const m=a.length>>1;return a.length%2?a[m]:(a[m-1]+a[m])/2};
const dObj=iso=>new Date(iso+'T00:00:00Z');
const md=iso=>{const d=dObj(iso);return(d.getUTCMonth()+1)+'/'+d.getUTCDate()};
const ASOFL=D.meta.asOfLabel||(ASOF?md(ASOF)+' 收盘':'行情待更新');
const wd=iso=>'周'+WD[dObj(iso).getUTCDay()];
const daysTo=iso=>Math.round((dObj(iso)-dObj(TODAY))/864e5);
const addDays=(iso,n)=>new Date(dObj(iso).getTime()+n*864e5).toISOString().slice(0,10);
const levelOf=t=>t>=17?{k:'hot',l:'重点追踪'}:t>=14?{k:'watch',l:'持续观察'}:{k:'low',l:'低频跟踪'};
const lvBadge=t=>{const L=levelOf(t);return`<span class="lv ${L.k}">${ICON[L.k]}${L.l}</span>`};
const tbBadge=t=>{const T=TIGHT[t]||{k:'t2',l:t};return`<span class="tb ${T.k}"><i></i>${T.l}</span>`};
const vlen=s=>Array.from(s).reduce((a,ch)=>a+(/[\u3000-\u9fff\uff00-\uffef]/.test(ch)?1:.62),0);
function fmtNum(v){if(!fin(v))return'—';const a=Math.abs(v);return v.toLocaleString('en-US',{minimumFractionDigits:a>=1000?0:2,maximumFractionDigits:a>=1000?0:2})}
const fmtPrice=c=>fin(c.price)?(CUR[c.cur]||'')+fmtNum(c.price):'—';
const mcapStr=v=>!fin(v)?'—':v>=10000?(v/10000).toFixed(2)+' 万亿美元':Math.round(v).toLocaleString('en-US')+' 亿美元';
const hlDates=s=>s.replace(/(\d{1,2}\/\d{1,2})/g,'<span class="dt">$1</span>');

/* ---------- display coverage ---------- */
const coverageCount=(items,value)=>items.filter(c=>fin(value(c))).length;
const coverageText=(items,value)=>`${coverageCount(items,value)}/${items.length}`;
function sparkHistoryLabel(c){const n=Math.min(60,c.sc.length);return`实际 ${n} 个交易日${n<60?' · 短历史':''}`}
function indexAvailability(indices,issues){
  const known=Array.isArray(issues),missing=known?[...new Set(issues.filter(x=>x.kind==='index').map(x=>x.symbol).filter(Boolean))]:[];
  return{missing,label:known?`指数有效 ${indices.length}/${indices.length+missing.length}`:`指数已提供 ${indices.length} 项 · 覆盖未提供`}}
function availableDays(c){return Number.isInteger(c.history?.count)?c.history.count:(c.sc||[]).length}
function historyGap(c){return`${c.sym==='688825.SS'?'上市时间不足':'历史数据不足'} · 可用 ${availableDays(c)} 个交易日`}
function peStatusText(c){
  if(fin(c.pe))return'';
  const v=c.provenance?.valuation||{};
  if(v.peStatus==='not_meaningful')return fin(v.epsTrailingTwelveMonths)&&v.epsTrailingTwelveMonths<=0?(v.epsTrailingTwelveMonths<0?'亏损 · 不适用':'每股收益非正 · 不适用'):'不适用';
  return v.peStatus==='invalid'?'来源数值无效':v.peStatus==='nonpositive'?'PE非正 · 不参排':'暂未取得'}
function metricGap(c,k){
  if(fin(rankValue(c,k)))return'';
  if(k==='pe')return peStatusText(c);
  if(c.financialPartial&&['revg','earng','gm'].includes(k))return'部分披露 · 不参排';
  const h=c.history||{},n=availableDays(c),required={r5:5,r20:20,r60:60}[k];
  if(n>0&&((required&&n<=required)||(k==='ytd'&&h.firstDate?.slice(0,4)===(c.ld||'').slice(0,4))||(['dd52','hi52'].includes(k)&&fin(h.days)&&h.days<364)))return historyGap(c);
  return'暂未取得'}
function compareRows(a,b,col,dir){
  const x=col.v(a),y=col.v(b),missing=v=>col.s?v==null||String(v).trim()==='':!fin(v),xm=missing(x),ym=missing(y);
  if(xm||ym)return xm===ym?0:xm?1:-1;
  return(col.s?String(x).localeCompare(String(y),'zh'):x-y)*dir}
function filterCompanies(items,industry,market){return items.filter(c=>(industry==='all'||c.ind===industry)&&(market==='all'||(market==='其他'?!['A股','港股','美股'].includes(c.mkt):c.mkt===market)))}
function dataStateCounts(rows){const counts={complete:0,partial:0,not_applicable:0,missing:0,access_blocked:0};for(const r of rows||[])if(r.status in counts)counts[r.status]++;return counts}
function dataStateLabel(rows){if(!rows?.length)return'数据覆盖未提供';const c=dataStateCounts(rows);return`数据：${c.complete}/${rows.length} 项完整 · ${c.partial} 项部分覆盖 · ${c.not_applicable} 项不适用 · ${c.missing} 项暂缺${c.access_blocked?' · '+c.access_blocked+' 项访问受阻':''}`}
function nativeCapText(c){return fin(c.mcapLocal)?(c.mcapLocal/1e8).toLocaleString('en-US',{maximumFractionDigits:2})+' 亿 '+c.cur:'原币市值暂未取得'}

/* ---------- research and calendar validity ---------- */
const deepDrawdown=c=>fin(c.dd52)&&c.dd52<=-.4;
function isoWeek(day){const d=new Date(day+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+4-(d.getUTCDay()||7));const y=d.getUTCFullYear();return y+'-W'+String(Math.ceil((((d-Date.UTC(y,0,1))/864e5)+1)/7)).padStart(2,'0')}
const REASONS={missing_reason:'缺研判理由',missing_source:'缺来源链接',missing_dates:'缺研判日期或有效期',future_judgment_date:'研判日期在未来',expired:'研判已过期',validity_too_long:'有效期超过 14 天',banned_words:'内容含不适合展示的用语',row_quarantined:'本行有误，沿用上次版本',not_current_week:'本周尚未更新',no_weekly_row:'本周尚无主线研判',legacy_data:'旧版数据，无研判信息'};
function judgmentOf(row){return row?.judgment||{label:'stale',reasons:['legacy_data'],date:null,validUntil:null,reason:'',sources:[]}}
function reasonText(code,j={}){if(code==='expired'&&j.validUntil)return`有效至 ${md(j.validUntil)}，已过期`;return REASONS[code]||code}
function statusTag(kind,label,tip,small=false){return`<span class="st ${kind}${small?' sm':''}" tabindex="0" data-tip="${esc(tip||label)}" aria-label="${esc((tip?label+'：':'')+(tip||label))}">${esc(label)}</span>`}
function judgmentTag(j,small=false){return statusTag(j.label==='ai'?'ai':j.label==='auto'?'auto':'stale',j.label==='ai'?'AI 研判':j.label==='auto'?'自动生成':'待更新',(j.reasons||[]).map(x=>reasonText(x,j)).join('；')||'由 AI 撰写；已附理由、来源、研判日期与有效期。',small)}
function reasonButton(kind,name){return`<button type="button" class="reason-link" data-reason-kind="${kind}" data-reason-name="${esc(name||'')}" aria-haspopup="dialog">查看理由</button>`}
function provenanceLine(j,kind,name,mode=''){
  if(mode==='none')return'';
  if(mode==='auto')return`${statusTag('auto','自动生成','由程序按有效行业评分生成')}<span>本周还没有主线研判 · 按行业评分自动选出</span>`;
  const reasons=j.reasons||[],first=reasons.includes('expired')?'expired':reasons.includes('not_current_week')?'not_current_week':reasons[0];
  const detail=j.label==='ai'?`${j.date?md(j.date)+' 研判':''}${j.validUntil?' · 有效至 '+md(j.validUntil):''}`:
    `${j.date?md(j.date)+' 研判 · ':''}${reasonText(first||'legacy_data',j)}${mode==='stale'?' · 显示上次结论':''}`;
  return`${judgmentTag(j)}<span class="opt">${esc(detail)}</span>${j.label==='ai'?`<span class="opt">· 依据 <b class="num">${(j.sources||[]).length}</b> 条</span>`:''}<span class="sep">·</span>${reasonButton(kind,name)}`;
}
function researchText(review={},week='',today=TODAY){return(review.reasons||['legacy_data']).map(x=>reasonText(x,review)).join(' · ')}
function hasConfirmedEvent(c){return!!(c.next&&c.earnings?.status==='confirmed'&&safeSourceUrl(c.earnings?.source_url))}
function eventState(c,today=TODAY){if(!c.next)return'undated';if(c.next<today)return'overdue';return hasConfirmedEvent(c)?'confirmed':'unverified'}
const EVENT_LABEL={confirmed:'官方确认',estimated:'预估',unverified:'预估',overdue:'待更新',undated:'日期待定'};
const eventLabel=(c,today=TODAY)=>EVENT_LABEL[eventState(c,today)];
function eventCounts(rows){const n={confirmed:0,estimated:0,unverified:0,overdue:0,undated:0};rows.forEach(c=>{if(!c.next)n.undated++;else if(hasConfirmedEvent(c))n.confirmed++;else n.unverified++});return n}
function eventSummary(rows){const n=eventCounts(rows);return`官方确认 ${n.confirmed} · 预估 ${n.unverified}${n.undated?' · 待定 '+n.undated:''}`}
function eventCountdown(day,today=TODAY){const n=Math.round((Date.parse(day+'T00:00:00Z')-Date.parse(today+'T00:00:00Z'))/864e5);return n<0?`已过 ${-n} 天 · 待更新`:n===0?'今天':`${n} 天后`}
function earningsText(text,companies=byId,today=TODAY){return String(text||'').replace(/\{\{earnings:([^}]+)\}\}/g,(_,id)=>{const c=companies[id];return c?`${c.next?md(c.next)+' · ':''}${eventLabel(c,today)}`:'日期待定'})}
const TIMEZONES={'Asia/Shanghai':'北京时间','America/New_York':'美东时间','Asia/Hong_Kong':'香港时间','Asia/Taipei':'台北时间','Asia/Seoul':'韩国时间','Asia/Tokyo':'日本时间','Europe/Paris':'欧洲中部时间'};
const MARKET_TZ={'A股':'Asia/Shanghai','美股':'America/New_York','港股':'Asia/Hong_Kong','台股':'Asia/Taipei','韩股':'Asia/Seoul','日股':'Asia/Tokyo','欧股':'Europe/Paris'};
function eventTip(c){const tz=c.earnings?.timezone||MARKET_TZ[c.mkt];return`${c.name} · ${c.next?hasConfirmedEvent(c)?'官方确认':'预估':'日期待定'} · ${TIMEZONES[tz]||tz||'时区未注明'}${c.earnings?.time_note?' '+c.earnings.time_note:''}${c.next&&c.next<TODAY?' · '+eventCountdown(c.next):''}`}
function eventPill(c,withDate=false){const cls=!c.next?' tbd':hasConfirmedEvent(c)?'':' est';return`<button type="button" class="pill${cls}" data-co="${esc(c.id)}" style="--ic:${IC(c.ind)}" data-tip="${esc(eventTip(c))}" aria-label="${esc(eventTip(c))}"><i></i><span>${esc(withDate?(c.next?md(c.next)+' · '+(hasConfirmedEvent(c)?'官方确认':'预估'):'日期待定'):c.short||c.name)}</span></button>`}
function earningsHTML(text){return String(text||'').split(/(\{\{earnings:[^}]+\}\})/g).map(part=>{const m=part.match(/^\{\{earnings:([^}]+)\}\}$/);return m?(byId[m[1]]?eventPill(byId[m[1]],true):'<span class="pill tbd"><i></i><span>日期待定</span></span>'):esc(part)}).join('')}
function calendarLegend(){return'<span class="cf-legend"><span><i></i>官方确认</span><span class="est"><i></i>预估</span><span class="tbd"><i></i>待定</span></span>'}

/* ---------- release and evidence helpers ---------- */
function safeSourceUrl(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:''}catch(e){return''}}
function safeResearchUrl(value){try{const u=new URL(value);return['https:','http:'].includes(u.protocol)&&!u.username&&!u.password?u.href:''}catch(e){return''}}
function researchAnchor(url,label){const href=safeResearchUrl(url);return href?`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label||new URL(href).hostname)} ↗</a>`:'<span class="muted">缺来源</span>'}
function sourceAnchor(url,label){const href=safeSourceUrl(url);return href?`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`:'<span class="muted">缺来源</span>'}
function providerUrl(symbol,source,history=false){
  if(source==='yahoo'&&symbol)return`https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}/${history?'history/':''}`;
  if(source==='tencent'&&symbol){const s=symbol.toUpperCase();let code=s.endsWith('.SS')?'sh'+s.slice(0,-3):s.endsWith('.SZ')?'sz'+s.slice(0,-3):s.endsWith('.HK')?'hk'+(s.slice(0,-3).match(/^\d+$/)?s.slice(0,-3).padStart(5,'0'):s.slice(0,-3)):s==='^HSI'?'hkHSI':null;return code?`https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${encodeURIComponent(code)},day,,,10,`:''}return'';
}
function nextScheduledRun(crons,now=Date.now()){
  if(!Array.isArray(crons))return null;
  const start=new Date(now),day=Date.UTC(start.getUTCFullYear(),start.getUTCMonth(),start.getUTCDate());
  for(let offset=0;offset<9;offset++){const base=day+offset*864e5,dow=new Date(base).getUTCDay(),times=[];
    for(const cron of crons){const m=String(cron).match(/^(\d{1,2}) (\d{1,2}) \* \* ([0-6](?:-[0-6])?)$/);if(!m)continue;const [a,b]=m[3].split('-').map(Number);if(dow<a||dow>(b??a))continue;const at=base+(+m[2]*60+(+m[1]))*60e3;if(at>now)times.push(at)}
    if(times.length)return Math.min(...times);
  }return null;
}
function scheduledDue(generated,now=Date.now(),schedule=D.meta.schedule){return!!(schedule?.nextRunAt&&Number.isFinite(Date.parse(schedule.nextRunAt))&&now>Date.parse(schedule.nextRunAt)+(schedule.lateAfterMinutes||90)*60000)}
function validVersion(v){return v&&v.schemaVersion===1&&['current','failed'].includes(v.state)&&/^[a-f0-9]{64}$/.test(v.dataSHA256||'')&&/^[a-f0-9]{40}$/.test(v.sourceSHA||'')&&/^\d+$/.test(v.runId||'')}
/* ---------- data ---------- */
const CO=D.companies,byId={},byInd={},byCp={};
function perfSig(c){if(c.financialPartial)return{k:'na',l:'不适用',r:0};if(!c.financialSignalEligible)return{k:'na',l:'不适用',r:0};const g=fin(c.earng)?c.earng:c.revg;if(!fin(g))return{k:'na',l:'—',r:0};if(g>=.5)return{k:'p1',l:'高增',r:4};if(g>=.1)return{k:'p2',l:'增长',r:3};if(g>-.1)return{k:'p3',l:'平稳',r:2};return{k:'p4',l:'下滑',r:1}}
function pxSig(c){const r=c.r20,d=c.dd52;if(!fin(r))return{k:'na',l:'—',r:0};if(r>=.05)return{k:'x1',l:'走强',r:4};if(fin(d)&&d<=-.4)return{k:'x4',l:'深度回调',r:1};if(r<=-.1)return{k:'x3',l:'回调',r:2};return{k:'x2',l:'震荡',r:3}}
CO.forEach(c=>{c.sd=c.sd||[];c.sc=c.sc||[];let t=Date.parse((c.s0||TODAY)+'T00:00:00Z');c.t=c.sd.map(d=>(t+=d*864e5));c.short=/[\u4e00-\u9fff]/.test(c.name)?c.name.split(' ')[0]:c.name;c.perf=perfSig(c);c.px=pxSig(c);byId[c.id]=c;(byInd[c.ind]=byInd[c.ind]||[]).push(c);(byCp[c.cp]=byCp[c.cp]||[]).push(c)});
const IND=D.industries.slice().sort((a,b)=>b.total-a.total);
const CP=D.chokepoints;
const cpsOf=n=>CP.filter(c=>c.ind===n).map((c,i)=>({c,i})).sort((a,b)=>(TIGHT[a.c.tight]?TIGHT[a.c.tight].r:9)-(TIGHT[b.c.tight]?TIGHT[b.c.tight].r:9)||a.i-b.i).map(x=>x.c);
const KEY_IND=IND.filter(i=>CP.some(c=>c.ind===i.name)).map(i=>i.name);
KEY_IND.forEach(n=>{if(!IND_C[n]){const u=Object.values(IND_C);IND_C[n]=IND_PAL.find(x=>!u.includes(x))||'#8e95a5'}});
const TOP=IND.find(i=>i.name===WK.focus)||IND[0];S.sel=TOP.name;S.cpInd=TOP.name;
const sgBadges=c=>`<span class="sg ${c.perf.k}" data-tip="业绩${esc(c.perf.l)}：${c.perf.k==='na'?esc(financialReason(c)):(fin(c.earng)?'净利':'营收')+'同比 '+pct(fin(c.earng)?c.earng:c.revg,1)}">${c.perf.l}</span><span class="sg ${c.px.k}" data-tip="股价${esc(c.px.l)}：近20日 ${pct(c.r20)} · 距高点 ${pct(c.dd52)}">${c.px.l}</span>${deepDrawdown(c)&&c.px.k!=='x4'?`<span class="sg x4" data-tip="距52周高点 ${pct(c.dd52)}；近期走强与深度回撤可同时成立">深度回调</span>`:''}`;

/* ---------- sparkline ---------- */
function spark(c,n,w,h){const v=c.sc.slice(-n);if(v.length<2)return'';const mn=Math.min.apply(null,v),mx=Math.max.apply(null,v),r=mx-mn||1,st=w/(v.length-1);
  const p=v.map((y,i)=>[i*st,h-2-(y-mn)/r*(h-4)]);const d='M'+p.map(q=>q[0].toFixed(1)+','+q[1].toFixed(1)).join('L');const k=v[v.length-1]>=v[0]?'up':'down';const L=p[p.length-1];
  return`<svg class="spark ${k}" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d}L${w},${h}L0,${h}Z" fill="url(#g-${k})"/><path class="line" d="${d}"/><circle cx="${L[0].toFixed(1)}" cy="${L[1].toFixed(1)}" r="2.2"/></svg>`}
const rankValue=(c,k)=>['revg','earng','gm'].includes(k)&&(c.financialPartial||c.provenance?.financial?.evidence==='missing'||k==='earng'&&['turnaround','one_off','not_disclosed'].includes(c.provenance?.financial?.profit_comparison))?null:c[k];
const finLine=c=>`营收 ${financialCell(c,'revg',true)} · 净利 ${financialCell(c,'earng')}`;
const leadRow=c=>`<div class="lr" data-co="${c.id}"><div class="lr-n"><b>${esc(c.short)}</b></div>${spark(c,60,58,20)}<div class="lr-f">${finLine(c)}</div><div class="lr-v num ${ud(c.r20)}">${pct(c.r20)}<small>近20日</small></div></div>`;

/* ---------- segmented control ---------- */
function moveThumb(el){const b=$('button.on',el),t=$('.thumb',el);if(!b||!t||!b.offsetWidth)return;t.style.left=b.offsetLeft+'px';t.style.width=b.offsetWidth+'px'}
function seg(el,opts,cur,fn){el.innerHTML='<span class="thumb"></span>'+opts.map(o=>`<button type="button" data-v="${esc(o.v)}" class="${o.v===cur?'on':''}">${o.l}</button>`).join('');el.dataset.cur=cur;
  el.onclick=e=>{const b=e.target.closest('button');if(!b||b.dataset.v===el.dataset.cur)return;setSeg(el,b.dataset.v);fn(b.dataset.v)};requestAnimationFrame(()=>moveThumb(el))}
function setSeg(el,v){el.dataset.cur=v;$$('button',el).forEach(x=>x.classList.toggle('on',x.dataset.v===v));moveThumb(el)}

/* ---------- count up ---------- */
const RM=()=>!!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches),SB=()=>RM()?'auto':'smooth';
function countUp(el){const to=parseFloat(el.dataset.count),dp=+(el.dataset.dp||0),pre=el.dataset.pre||'',suf=el.dataset.suf||'',t0=performance.now(),dur=1200;if(RM()){el.textContent=pre+to.toFixed(dp)+suf;return}
  const f=now=>{const p=Math.min(1,(now-t0)/dur),e=1-Math.pow(1-p,3);el.textContent=pre+(to*e).toFixed(dp)+suf;if(p<1)requestAnimationFrame(f)};requestAnimationFrame(f)}

const phaseText=p=>p==='closed'?'收盘':p==='intraday'?'盘中':'状态未知';
const quoteLabel=c=>`${c.priceAsOf||c.ld||'日期未知'} ${phaseText(c.pricePhase||c.provenance?.daily?.phase)} · ${c.priceSource||c.provenance?.daily?.src||'来源未知'}`;
const timeDetail=c=>{const v=c.provenance?.valuation||{},f=v.fx;return `行情 ${quoteLabel(c)} · 报价时点 ${c.priceObservedAt||'未提供精确时刻'} · ${c.marketTimezone||'时区未注明'}；日线指标截至 ${c.metricAsOf||c.ld||'缺失'} 收盘；估值 ${v.asOf||'缺失'} ${phaseText(v.phase)} · ${v.source||'来源未知'}；本币市值 ${fin(c.mcapLocal)?c.mcapLocal.toLocaleString('en-US')+' '+c.cur:'—'}；美元折算${f?.estimated?'为估算':''}：${f?`${f.src} ${f.asOf} · 1 USD=${f.value} ${c.cur}`:'汇率缺失'}`};

/* ---------- ticker ---------- */
function renderTicker(){const status=indexAvailability(D.indices,D.meta.issues),notice=status.missing.length?`<div class="tk idx-gap">指数缺项：${esc(status.missing.join('、'))}</div>`:'';const idx=D.indices.map(x=>`<div class="tk idx"><b data-tip="${esc((x.asOf||'日期未知')+' · '+phaseText(x.phase)+' · '+(x.source||'未知来源')+' · '+(x.providerLocalTime||''))}">${esc(x.name)} <small>${esc(x.asOf||'未知')} ${phaseText(x.phase)}</small></b><span class="px num">${fmtNum(x.price)}</span><span class="num ${ud(x.chg)}">${pct(x.chg,2)}</span></div>`).join('');
  const cos=CO.map(c=>`<div class="tk" data-co="${c.id}" data-tip="${esc(timeDetail(c))}"><b>${esc(c.short)} <small>${esc(c.priceAsOf||c.ld||'未知')} ${phaseText(c.pricePhase||c.provenance?.daily?.phase)}</small></b><span class="px num">${fmtPrice(c)}</span><span class="num ${ud(c.r1d)}">日线 ${pct(c.r1d,2)}</span></div>`).join('');
  const one=notice+idx+'<span class="tk-sep"></span>'+cos+'<span class="tk-sep"></span>';$('#tickerTrack').innerHTML=one+one;$('#tickerLabel').textContent=ASOFL+' · '+status.label;$('#tickerLabel').dataset.tip=status.missing.length?'指数缺项：'+status.missing.join('、'):status.label}

/* ---------- hero ---------- */
function renderHero(){
  const week=isoWeek(TODAY),start=WK.weekStart||addDays(TODAY,-((dObj(TODAY).getUTCDay()+6)%7)),endWeek=WK.weekEnd||addDays(start,6),mode=WK.mode||'stale';
  $('#heroDate').textContent=`${week} · ${md(start)}–${md(endWeek)}`;
  $('#heroTitle').innerHTML=mode==='none'?'本周主线待更新':`本周主线：<span class="grad">${esc(WK.focus||TOP.name)}</span>`;
  $('#heroProv').innerHTML=provenanceLine(judgmentOf(WK),'weekly',WK.focus||TOP.name,mode);$('#heroProv').hidden=mode==='none';
  $('#heroLead').textContent=mode==='none'?'行业研判均待更新，下方数据照常显示。':WK.lead||TOP.logic||'';
  const end=addDays(TODAY,14),focus=IND.filter(i=>i.total>=17),stale=focus.filter(i=>judgmentOf(i).label!=='ai').length,soon=CO.filter(c=>c.next&&c.next>=TODAY&&c.next<=end);
  const kp=[
    {v:focus.length,l:'重点追踪行业',s:'总分 ≥ 17'+(stale?` · ${stale} 个待更新`:''),c:'var(--gold)',ic:ICON.hot},
    {v:CP.filter(c=>TIGHT[c.tight]&&TIGHT[c.tight].k==='t1').length,l:'极紧卡点',s:`共 ${CP.length} 个`,c:'var(--tight)',ic:ICON.alert},
    {v:CO.filter(c=>c.perf.k==='p1').length,l:'业绩高增龙头',s:`同比 ≥ 50% · 共 ${CO.length} 家`,c:'var(--up)',ic:ICON.up},
    {v:CO.filter(deepDrawdown).length,l:'深度回调龙头',s:'距52周高点 ≤ −40%',c:'var(--down)',ic:ICON.down},
    {v:soon.length,l:'两周内财报',s:eventSummary(soon),c:'var(--accent-2)',ic:ICON.cal}];
  $('#kpis').innerHTML=kp.map(k=>`<div class="kpi" style="--c:${k.c}"><span class="ic">${k.ic}</span><span class="v num" data-count="${k.v}">${k.v}</span><span class="l">${k.l}<small>${k.s}</small></span></div>`).join('');
  renderToday();
}
function renderToday(){
  const daily=D.meta.daily||{},markets=['A股','美股'],allAI=markets.every(m=>daily[m]?.source==='ai');
  $('#today').innerHTML=`<div class="today-h"><span class="today-t">今日要点</span>${allAI?statusTag('ai','AI 摘要','AI 根据当日收盘复盘写的一句话，只陈述已发生的事实，不做预测。'):''}<span class="hint">每个交易日收盘后更新</span></div><div class="today-rows">${markets.map(m=>{const row=daily[m]||{},auto=row.source==='auto',date=row.date;return`<div class="today-row${auto?' is-auto':''}"><div class="today-meta"><span class="today-mk">${m}</span><span class="num">${date?`${md(date)} ${wd(date)} · 收盘`:'日期未提供'}</span>${auto?statusTag('auto','自动生成','复盘未更新，按已完成交易日的指数生成'):''}${!auto&&safeResearchUrl(row.reviewUrl)?`<a class="today-go" href="${esc(safeResearchUrl(row.reviewUrl))}" target="_blank" rel="noopener noreferrer">看复盘 ↗</a>`:''}${auto?'<span class="today-go muted">复盘未更新</span>':''}</div><p class="today-line${row.line?'':' muted'}">${esc(row.line||'今日要点待更新')}</p><div class="today-ix num">${(row.chips||[]).map(c=>`<span>${esc(c.label)}<b class="${ud(c.chg)}">${pct(c.chg,2)}</b></span>`).join('')}</div></div>`}).join('')}</div>`;
}

function nextEvents(cos,n){const m={};cos.filter(c=>c.next&&c.next>=TODAY).forEach(c=>{(m[c.next]=m[c.next]||[]).push(c)});return Object.keys(m).sort().slice(0,n).map(d=>({d,cs:m[d]}))}
function renderTop(){
  const d=TOP,cps=cpsOf(d.name),cos=byInd[d.name]||[];
  const r20=mean(cos.map(c=>c.r20)),dd=mean(cos.map(c=>c.dd52)),rev=median(cos.filter(c=>c.financialRevenueComparable).map(c=>c.revg));const C=2*Math.PI*48;
  const cpCol=(cp,i)=>{const T=TIGHT[cp.tight]||{k:'t2'};return`<div class="cp-col ${T.k}" style="--tc:${TC[T.k]}"><div class="cp-col-h"><span class="cp-idx">卡点 0${i+1}</span>${tbBadge(cp.tight)}</div><div class="cp-name">${esc(cp.name)}</div><div class="cp-seg" title="${esc(cp.seg)}">${esc(cp.seg)}</div>${(byCp[cp.name]||[]).map(leadRow).join('')}</div>`};
  $('#topCard').innerHTML=`<div class="card-h"><div class="card-t">${ICON.target}主线拆解 · <span data-src="notion">${esc(d.name)}</span></div>${WK.mode==='none'?judgmentTag(judgmentOf(d)):lvBadge(d.total)}</div>

  <div class="top-strip">
    <div class="ring"><svg width="112" height="112" viewBox="0 0 112 112"><circle class="trk" cx="56" cy="56" r="48" stroke-width="9" fill="none"/><circle class="bar" cx="56" cy="56" r="48" stroke-width="9" fill="none" stroke-dasharray="${C.toFixed(2)}" stroke-dashoffset="${C.toFixed(2)}" data-to="${(C*(1-d.total/20)).toFixed(2)}"/></svg><div class="ctr"><div><div class="big num" data-count="${d.total}">${d.total}</div><div class="of">/ 20 综合分</div></div></div></div>
    <div class="dims">${DIMS.map(x=>`<div class="dim"><span>${x.n}</span><span class="pips" style="--c:${x.c}">${[1,2,3,4,5].map(i=>`<i class="pip ${i<=d.s[x.k]?'on':''}" style="transition-delay:${250+i*90}ms"></i>`).join('')}</span><b class="num">${d.s[x.k]}</b></div>`).join('')}</div>
    <div class="tstats"><div class="tstat"><span class="l">龙头近20日 · 均值 · 有效 ${coverageText(cos,c=>c.r20)}</span><span class="v num ${ud(r20)}">${pct(r20)}</span></div><div class="tstat"><span class="l">距52周高点 · 均值 · 有效 ${coverageText(cos,c=>c.dd52)}</span><span class="v num ${ud(dd)}">${pct(dd)}</span></div><div class="tstat"><span class="l">单季营收同比 · 中位数 · 有效 ${coverageText(cos,c=>c.financialRevenueComparable?c.revg:null)}</span><span class="v num ${ud(rev)}">${pct(rev,1)}</span></div></div>
  </div>
  <div class="mini-h"><span>关键卡点 → 细分龙头</span><span class="hint">按紧缺度排序 · 点击公司看走势与财务</span></div>
  <div class="cp-cols">${cps.slice(0,3).map(cpCol).join('')}</div>
  <div class="top-foot"><span class="lbl">${ICON.cal}下一个验证窗口</span>${nextEvents(cos,3).map(e=>`<span class="ev"><b>${md(e.d)}</b>${e.cs.map(c=>eventPill(c)).join('')}</span>`).join('')}${cps.length>3?`<span class="more">另有：${cps.slice(3).map(c=>esc(c.name)+'（'+(TIGHT[c.tight]?TIGHT[c.tight].l:'')+'）').join('、')}</span>`:''}</div>`}

function renderRank(){
  const ai=IND.filter(d=>judgmentOf(d).label==='ai'),majority=ai.length>=IND.length/2?'ai':'stale',dates={};ai.forEach(d=>{const date=judgmentOf(d).date;if(date)dates[date]=(dates[date]||0)+1});const date=Object.keys(dates).sort((a,b)=>dates[b]-dates[a]||b.localeCompare(a))[0];
  $('#rankCard').innerHTML=`<div class="card-h"><div class="card-t">${ICON.radar}行业评分</div><span class="meta">${ai.length?statusTag(majority,majority==='ai'?'AI 研判':'待更新',majority==='ai'?'多数行业的研判信息齐全且有效':'多数行业研判待更新'):statusTag('stale','待更新','旧版数据或行业研判均待更新')}<span class="hint">${date?md(date)+' · ':''}每周一更新</span></span></div>
  <div class="rk-list">${IND.map((d,i)=>{const j=judgmentOf(d),conflicts=j.conflicts||[],exception=j.label==='stale'&&majority!=='stale';return`<div class="rk ${i<3?'top':''}${j.label!=='ai'?' is-stale':''}" data-ind="${esc(d.name)}" data-tip="${esc(d.name)}｜${DIMS.map(x=>x.n+' '+d.s[x.k]).join(' · ')}" tabindex="0"><span class="n">${String(i+1).padStart(2,'0')}</span><span class="nm" data-src="notion">${esc(d.name)}${exception?judgmentTag(j,true):''}${conflicts.length?statusTag('conflict','数据冲突',conflicts.map(c=>conflictText(c,j)).join('；'),true):''}</span><span class="bar"><span class="fill" style="width:${d.total/20*100}%">${d.s.map((v,k)=>`<i style="flex:${v};background:${DIMS[k].c}"></i>`).join('')}</span></span><b class="sc num">${d.total}</b></div>`}).join('')}</div>
  <div class="legend-dims">${DIMS.map(x=>`<span><i style="background:${x.c}"></i>${x.n}</span>`).join('')}</div>`;
}
function conflictText(c,j){const a=j.anchors?.[c.field];return`${c.field}：AI ${c.ai} · 数据档 ${c.anchor}${a?.medianRevenueYoYPct!=null?'（营收同比中位数 '+pct(a.medianRevenueYoYPct/100,1)+'，'+a.n+' 家）':a?.maxTightness?'（最紧卡点为「'+a.maxTightness+'」）':''}`}

function renderThermo(){
  if(!D.ratio){$('#thermoCard').innerHTML=`<div class="card-h"><div class="card-t">${ICON.thermo}成长/红利温度计</div></div><div class="muted" style="padding:28px 0">当前快照无可用比值数据</div>`;return}
  const R=D.ratio,lo=.3,hi=.7,f=Math.max(0,Math.min(1,(R.cur-lo)/(hi-lo))),cx=130,cy=128,r=100;
  const pt=(v,rr)=>{const a=Math.PI*(1-(v-lo)/(hi-lo));return[cx+rr*Math.cos(a),cy-rr*Math.sin(a)]};
  let ticks='';[.3,.4,.5,.6,.7].forEach(v=>{const a=pt(v,r-14),b=pt(v,r-6),t=pt(v,r+13);const end=v===lo||v===hi,tx=end?(v===lo?cx-r-11:cx+r+11):t[0],ty=end?cy+3.5:t[1]+3;ticks+=`<line x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}" stroke="currentColor" opacity=".35"/><text x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${end?(v===lo?'end':'start'):'middle'}">${v.toFixed(1)}</text>`});
  const zone=R.p60<.2?'红利相对强 · 极端':R.p60>.8?'成长相对强 · 极端':'中性区';
  // ratio line
  const ser=R.series,W=300,H=70,vals=ser.map(s=>s[1]),mn=Math.min(.28,Math.min.apply(null,vals)),mx=Math.max(.78,Math.max.apply(null,vals));
  const X=i=>4+(W-34)*i/(ser.length-1),Y=v=>6+(H-18)*(1-(v-mn)/(mx-mn));
  const path='M'+ser.map((s,i)=>X(i).toFixed(1)+','+Y(s[1]).toFixed(1)).join('L');const lx=X(ser.length-1),ly=Y(R.cur);
  const line=`<svg class="th-line" viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none" aria-label="创业板/中证红利比值月线"><line class="ref" x1="4" x2="${W-30}" y1="${Y(.7)}" y2="${Y(.7)}"/><line class="ref" x1="4" x2="${W-30}" y1="${Y(.3)}" y2="${Y(.3)}"/><text x="${W-26}" y="${Y(.7)+3}">0.7</text><text x="${W-26}" y="${Y(.3)+3}">0.3</text><path class="ln" d="${path}"/><circle class="halo" cx="${lx}" cy="${ly}" r="5"/><circle class="dot" cx="${lx}" cy="${ly}" r="3"/><text x="4" y="${H-1}">${ser[0][0].slice(0,4)}</text><text x="${W-30}" y="${H-1}" text-anchor="end">${ser[ser.length-1][0].slice(0,4)}</text></svg>`;
  const L10=ser.slice(-121,-1),lv=L10.map(s=>s[1]),so=lv.slice().sort((a,b)=>a-b),vmin=so[0],vmax=so[so.length-1],med=(so[59]+so[60])/2,smin=L10[lv.indexOf(vmin)][0],smax=L10[lv.indexOf(vmax)][0],RP=v=>(Math.max(0,Math.min(1,(v-vmin)/(vmax-vmin)))*100).toFixed(1);
  const rng=`<div class="th-rng"><div class="rl"><span>近10年区间（月末）</span><span class="num">中位 ${med.toFixed(3)} · 当前 ${R.cur.toFixed(3)}</span></div><div class="rt"><i class="rf" style="width:${RP(R.cur)}%"></i><i class="rm" style="left:${RP(med)}%"></i><i class="rc" style="left:${RP(R.cur)}%"></i></div><div class="re num"><span>低 ${vmin.toFixed(3)} · ${smin}</span><span>高 ${vmax.toFixed(3)} · ${smax}</span></div></div>`;
  $('#thermoCard').innerHTML=`<div class="card-h"><div class="card-t">${ICON.thermo}成长/红利温度计</div><span class="hint">创业板指 ÷ 中证红利</span></div>
  <div class="thermo-b">
    <div class="gauge"><svg viewBox="0 0 260 150" width="100%"><path class="arc-bg" d="M${cx-r},${cy} A${r},${r} 0 0 1 ${cx+r},${cy}" stroke-width="14" fill="none" stroke-linecap="round"/><path d="M${cx-r},${cy} A${r},${r} 0 0 1 ${cx+r},${cy}" stroke="url(#g-gauge)" stroke-width="14" fill="none" stroke-linecap="round" opacity=".9"/><g style="color:var(--text-2)">${ticks}</g><text class="gl" x="${cx-r}" y="${cy+18}" text-anchor="middle">红利强</text><text class="gl" x="${cx+r}" y="${cy+18}" text-anchor="middle">成长强</text><g class="needle" data-deg="${(f*180).toFixed(1)}"><line x1="${cx}" y1="${cy}" x2="${cx-r+22}" y2="${cy}"/></g><circle class="hub" cx="${cx}" cy="${cy}" r="6"/></svg>
      <div class="g-read"><div class="v num" data-count="${R.cur}" data-dp="3">${R.cur.toFixed(3)}</div><div class="s">当前比值</div></div></div>
    <div class="th-txt"><span class="zone">● ${zone}</span>
      <p>创业板指 ${fmtNum(R.cyb)} ÷ 中证红利 ${fmtNum(R.hl)}；比值日期 ${esc(R.asOf||'未知')}，同步时刻未确认；分位只按共同完整月末计算。</p>
      <div class="pc"><div><b class="num" data-count="${Math.round(R.p60*100)}" data-suf="%">${Math.round(R.p60*100)}%</b><span>近5年分位</span><em class="num">${R.n60}/60 个月</em></div><div><b class="num" data-count="${Math.round(R.p120*100)}" data-suf="%">${Math.round(R.p120*100)}%</b><span>近10年分位</span><em class="num">${R.n120}/120 个月</em></div></div>
      ${line}
      <div class="th-act">${statusTag('auto','自动生成','按比值与历史分位生成的位置说明')}只描述位置，不含操作建议</div></div>
  </div>${rng}`}

function renderSoon(){
  const end=addDays(TODAY,14),list=CO.filter(c=>c.next&&c.next>=TODAY&&c.next<=end).sort((a,b)=>a.next.localeCompare(b.next)),dates=Array.from(new Set(list.map(c=>c.next)));
  $('#soonCard').innerHTML=`<div class="card-h"><div class="card-t">${ICON.cal}两周内财报</div><span class="hint">${md(TODAY)} – ${md(end)} · ${list.length} 家</span></div>
  <div class="soon-legend">${calendarLegend()}<span class="hint">日期按公司所在地时区</span></div>
  <div class="soon-list">${dates.map(d=>{const cs=list.filter(c=>c.next===d);return`<div class="sr"><div class="sd"><b class="num">${md(d)}</b><span>${wd(d)}</span></div><div class="scd">${eventCountdown(d)}</div><div class="sp">${cs.map(c=>eventPill(c)).join('')}</div></div>`}).join('')}</div>
  <div class="legend-dims" style="padding-top:0">${KEY_IND.map(n=>`<span><i style="background:${IC(n)};border-radius:50%"></i>${esc(n)}</span>`).join('')}</div>`}

/* ---------- radar section ---------- */
function renderIndList(){
  const L=IND.filter(d=>S.level==='all'||levelOf(d.total).k===S.level);
  $('#indList').innerHTML=L.map(d=>{const i=IND.indexOf(d),lv=levelOf(d.total);return`<div class="ir lvl-${lv.k} ${d.name===S.sel?'sel':''}" data-pick="${esc(d.name)}" tabindex="0"><span class="ir-n">${String(i+1).padStart(2,'0')}</span><div style="min-width:0"><div class="ir-t"><b>${esc(d.name)}</b>${lvBadge(d.total)}${judgmentOf(d).label==='ai'?'':judgmentTag(judgmentOf(d),true)}</div><div class="ir-r">${esc(d.reps)}</div></div><div class="ir-mid" data-tip="${DIMS.map(x=>x.n+' '+d.s[x.k]).join(' · ')}"><div class="ir-bar on"><div class="fill" style="width:${d.total/20*100}%">${d.s.map((v,k)=>`<i style="flex:${v};background:${DIMS[k].c}"></i>`).join('')}</div></div><div class="ir-sub">${d.s.map((v,k)=>`<span>${DIMS[k].n.slice(0,2)}${v}</span>`).join('')}</div></div><b class="ir-s num">${d.total}</b></div>`}).join('')||'<div class="pempty">暂无</div>'}

let RC=[0,0,0,0],raf=0;
const RG={cx:150,cy:108,R:70},ANG=[-90,0,90,180].map(a=>a*Math.PI/180);
function radarSVG(){const{cx,cy,R}=RG;let rings='';for(let k=1;k<=5;k++){rings+=`<polygon class="ring-l" opacity="${k===5?1:.5}" points="${ANG.map(a=>(cx+R*k/5*Math.cos(a)).toFixed(1)+','+(cy+R*k/5*Math.sin(a)).toFixed(1)).join(' ')}"/>`}
  const axes=ANG.map(a=>`<line class="axis" x1="${cx}" y1="${cy}" x2="${(cx+R*Math.cos(a)).toFixed(1)}" y2="${(cy+R*Math.sin(a)).toFixed(1)}"/>`).join('');
  const lab=[[cx,cy-R-12,'middle'],[cx+R+10,cy+4,'start'],[cx,cy+R+22,'middle'],[cx-R-10,cy+4,'end']];
  return`<svg class="radar-svg" viewBox="0 0 300 220" width="100%" style="max-width:300px">${rings}${axes}<polygon class="poly" id="rpoly" points="${cx},${cy}"/>${DIMS.map((d,i)=>`<circle class="pt" id="rp${i}" cx="${cx}" cy="${cy}" r="4" style="stroke:${d.c}"/>`).join('')}${DIMS.map((d,i)=>`<text x="${lab[i][0]}" y="${lab[i][1]}" text-anchor="${lab[i][2]}">${d.n} <tspan class="v" id="rv${i}">0</tspan></text>`).join('')}</svg>`}
function drawRadar(v){const{cx,cy,R}=RG,poly=$('#rpoly');if(!poly)return;const p=v.map((s,i)=>[cx+R*s/5*Math.cos(ANG[i]),cy+R*s/5*Math.sin(ANG[i])]);poly.setAttribute('points',p.map(q=>q[0].toFixed(1)+','+q[1].toFixed(1)).join(' '));p.forEach((q,i)=>{const c=$('#rp'+i);c.setAttribute('cx',q[0].toFixed(1));c.setAttribute('cy',q[1].toFixed(1));$('#rv'+i).textContent=Math.round(v[i])})}
function animateRadar(tg){RC=tg.slice();drawRadar(RC)}
function findCo(token){token=token.trim();return CO.find(c=>c.short===token||c.name===token||c.name.indexOf(token)===0||c.name.indexOf(' '+token)>0)}
function renderIndDetail(){
  const d=IND.find(x=>x.name===S.sel),cos=byInd[d.name]||[],cps=cpsOf(d.name),i=IND.indexOf(d),lv=levelOf(d.total);
  const reps=d.reps.split(/[、,，]/).map(s=>s.trim()).filter(Boolean);
  const rs=cos.length?[['龙头近20日 · 均值',mean(cos.map(c=>c.r20)),coverageText(cos,c=>c.r20)],['距52周高点 · 均值',mean(cos.map(c=>c.dd52)),coverageText(cos,c=>c.dd52)],['单季营收同比 · 中位数',median(cos.filter(c=>c.financialRevenueComparable).map(c=>c.revg)),coverageText(cos,c=>c.financialRevenueComparable?c.revg:null)]]:null;
  const el=$('#indDetail');
  el.innerHTML=`<div class="fade-swap"><div class="dt-h"><div><div class="eyebrow">#${String(i+1).padStart(2,'0')} · ${lv.l}</div><h3 data-src="notion">${esc(d.name)}</h3></div><div class="dt-score"><b class="num">${d.total}</b><span> / 20</span></div></div>
  <div class="prov" data-src="notion">${provenanceLine(judgmentOf(d),'industry',d.name)}</div>
  <div class="dt-body"><div>${radarSVG()}<div class="anchor-list">${DIMS.map(x=>{const j=judgmentOf(d),a=j.anchors?.[x.n],c=(j.conflicts||[]).find(c=>c.field===x.n);return`<div><span>${x.n}</span><b class="num">${d.s[x.k]}</b>${a?`<small>数据档 <span class="num">${a.anchor}</span></small>`:''}${c?statusTag('conflict','数据冲突',conflictText(c,j),true):''}</div>`}).join('')}</div></div><div class="rstats">${rs?rs.map(r=>`<div class="rstat"><div class="l">${r[0]} · 有效 ${r[2]}</div><div class="v num ${ud(r[1])}">${pct(r[1],r[0].startsWith('单季')?1:2)}</div></div>`).join('')+`<div class="hint">分母为本行业 ${cos.length} 家 · 各项仅计有效样本</div>`:`<div class="rstat"><div class="l">龙头数据</div><div class="v" style="font-size:13px;font-weight:500;color:var(--text-2)">仅研究观察，尚未接公司数据</div></div>`}</div></div>
  <div class="blk"><div class="bl">${ICON.target}一句话逻辑</div><p data-src="notion">${esc(d.logic)}</p></div>
  <div class="blk"><div class="bl">${ICON.bolt}最新信号</div><ul class="research-signals" data-src="notion">${String(d.signal||'').split('；').filter(Boolean).slice(0,4).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>
  <div class="blk risk"><div class="bl">${ICON.alert}主要风险</div><p data-src="notion">${esc(d.risk)}</p></div>
  <div class="blk"><div class="bl">${ICON.grid}代表公司</div><div class="chips">${reps.map(r=>{const c=findCo(r);return c?`<button class="chip link" data-co="${c.id}">${esc(r)}</button>`:`<span class="chip">${esc(r)}</span>`}).join('')}</div></div>
  <div class="dt-actions">${cps.length?`<button class="btn primary" data-gocp="${esc(d.name)}">查看卡点地图 ${ICON.arrow}</button>`:''}${researchAnchor(d.kb||d.url,'知识库笔记')}</div></div>`;
  animateRadar(d.s)}
function selectInd(name,scroll){S.sel=name;$$('#indList .ir').forEach(r=>r.classList.toggle('sel',r.dataset.pick===name));renderIndDetail();
  if(KEY_IND.indexOf(name)>=0&&S.cpInd!==name){S.cpInd=name;setSeg($('#cpSeg'),name);renderFlow()}
  if(scroll)document.getElementById('radar').scrollIntoView({behavior:SB()})}

/* ---------- chokepoints ---------- */
function renderFlow(){const cps=cpsOf(S.cpInd);
  $('#flow').innerHTML=cps.map((cp,i)=>{const T=TIGHT[cp.tight]||{k:'t2'};const segs=cp.seg.split(/[、，,]/).map(s=>s.trim()).filter(Boolean),tr=cp.track.split(/[、；;]/).map(s=>s.trim()).filter(Boolean);
    return`<article class="card cp-card ${T.k} fade-swap" style="--tc:${TC[T.k]};animation-delay:${i*70}ms" data-cpname="${esc(cp.name)}"><div class="accent"></div>
    <div class="cp-top"><span class="cp-no mono">卡点 0${i+1}</span>${tbBadge(cp.tight)}</div>
    <h3 class="cp-title" data-src="notion">${esc(cp.name)}</h3><div class="chips">${segs.map(s=>`<span class="chip">${esc(s)}</span>`).join('')}</div>
    <div class="prov" data-src="notion">${judgmentOf(cp).label==='ai'?reasonButton('chokepoint',cp.name):provenanceLine(judgmentOf(cp),'chokepoint',cp.name)}</div>
    <div class="sec-l">为什么卡</div><p class="why" data-src="notion">${esc(cp.why)}</p>
    <div class="sec-l">跟踪指标</div><ul class="track" data-src="notion">${tr.map(t=>`<li>${earningsHTML(t)}</li>`).join('')}</ul>
    <div class="cp-leads"><div class="sec-l">细分龙头</div>${(byCp[cp.name]||[]).map(c=>leadRow(c)+`<div style="margin:-2px 0 6px 2px">${sgBadges(c)}</div>`).join('')}</div></article>`}).join('')}

/* ---------- treemap ---------- */
function squarify(items,x,y,w,h){const out=[];if(w<=0||h<=0||!items.length)return out;const tot=items.reduce((s,d)=>s+d.value,0);if(tot<=0)return out;
  const ns=items.map(d=>({d,a:d.value/tot*w*h})).sort((p,q)=>q.a-p.a);let rx=x,ry=y,rw=w,rh=h,row=[],i=0;
  const worst=(r,side)=>{let s=0,mx=-1e18,mn=1e18;r.forEach(n=>{s+=n.a;if(n.a>mx)mx=n.a;if(n.a<mn)mn=n.a});const s2=s*s,q=side*side;return Math.max(q*mx/s2,s2/(q*mn))};
  const lay=r=>{const s=r.reduce((t,n)=>t+n.a,0);if(rw>=rh){const cw=s/rh;let cy=ry;r.forEach(n=>{const hh=n.a/cw;out.push({d:n.d,x:rx,y:cy,w:cw,h:hh});cy+=hh});rx+=cw;rw-=cw}else{const ch=s/rw;let cx=rx;r.forEach(n=>{const ww=n.a/ch;out.push({d:n.d,x:cx,y:ry,w:ww,h:ch});cx+=ww});ry+=ch;rh-=ch}};
  while(i<ns.length){const side=Math.min(rw,rh),n=ns[i];if(!row.length||worst(row.concat([n]),side)<=worst(row,side)){row.push(n);i++}else{lay(row);row=[]}}if(row.length)lay(row);return out}
const hex=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16));
const mix=(a,b,t)=>{const A=hex(a),B=hex(b);return'rgb('+A.map((v,i)=>Math.round(v+(B[i]-v)*t)).join(',')+')'};
function pal(){const L=S.theme==='light',red=L?'#e0303e':'#e2323f',green=L?'#0f9a56':'#11a35b';return{neu:L?'#dfe3ea':'#2a2e39',up:S.conv==='cn'?red:green,down:S.conv==='cn'?green:red,L}}
function tileColor(v,M){const P=pal();if(!fin(v))return{bg:P.neu,a:0,P};let t=Math.max(-1,Math.min(1,v/M.dom));const a=Math.pow(Math.abs(t),.72);return{bg:mix(P.neu,t>=0?P.up:P.down,a),a,P}}
const tiles={};
const filtered=()=>filterCompanies(CO,S.indF,S.mktF);
function tileInner(c,w,h,M){const vs=pct(rankValue(c,M.k)),nm=esc(c.short),nl=vlen(c.short)+.6,fs=Math.max(10,Math.min(22,(w-8)/nl,h/3.3));
  if(w>=74&&h>=50)return`<div class="tn" style="font-size:${fs.toFixed(1)}px">${nm}</div><div class="tv num" style="font-size:${Math.max(10,fs*.7).toFixed(1)}px">${vs}</div>${h>=96&&w>=96?`<div class="tc">${esc(c.code)}</div>`:''}`;
  if(w>=42&&h>=30)return`<div class="tn" style="font-size:${Math.min(fs,12).toFixed(1)}px">${nm}</div><div class="tv num" style="font-size:10px">${vs}</div>`;
  if(w<42&&w>=14&&h>=46)return`<div class="tn vt" style="font-size:${Math.max(10,Math.min(12,w-6)).toFixed(1)}px">${nm}</div>`;
  if(w>=42&&h>=16)return`<div class="tn" style="font-size:10px">${nm}</div>`;
  if(w>=30&&h>=20)return`<div class="tv num" style="font-size:10px">${vs}</div>`;
  return''}
function renderMap(){const box=$('#treemap');if(!box||!box.offsetWidth)return;const W=box.clientWidth,H=box.clientHeight,M=METRICS.find(m=>m.k===S.metric),list=filtered(),PW=.4;
  const raw=c=>Math.pow(Math.max(c.mcapUSD||5,5),PW),av=list.map(raw).sort((a,b)=>a-b),medV=av.length?av[Math.floor(av.length/2)]:1;
  const groups=KEY_IND.map(ind=>{const kids=cpsOf(ind).map(cp=>{const ks=list.filter(c=>c.cp===cp.name).map(c=>({c,value:raw(c)})),gm=Math.max.apply(null,ks.map(k=>k.value).concat([0]));ks.forEach(k=>{k.value=Math.max(k.value,gm*.3,medV*.4)});return{name:cp.name,kids:ks,value:ks.reduce((s,k)=>s+k.value,0)}}).filter(g=>g.kids.length);return{name:ind,kids,value:kids.reduce((s,k)=>s+k.value,0)}}).filter(g=>g.kids.length);
  const seen={};let labels='';const tilesBox=$('#mapTiles');
  squarify(groups,0,0,W,H).forEach(r=>{const g=r.d,gh=24,n=g.kids.reduce((s,k)=>s+k.kids.length,0);
    labels+=`<div class="glabel" style="left:${(r.x+4).toFixed(1)}px;top:${(r.y+2).toFixed(1)}px;width:${Math.max(0,r.w-8).toFixed(1)}px;height:${gh-4}px"><i style="background:${IC(g.name)}"></i>${esc(g.name)}<span>${n} 家</span></div>`;
    squarify(g.kids,r.x+3,r.y+gh,r.w-6,r.h-gh-3).forEach(r2=>{const s=r2.d,sh=(r2.h>64&&r2.w>84)?16:0;
      if(sh)labels+=`<div class="slabel" style="left:${(r2.x+1).toFixed(1)}px;top:${(r2.y+1).toFixed(1)}px;width:${(r2.w-2).toFixed(1)}px">${esc(s.name)}</div>`;
      squarify(s.kids,r2.x+1,r2.y+sh+1,r2.w-2,r2.h-sh-2).forEach(r3=>{const c=r3.d.c;seen[c.id]=1;let el=tiles[c.id];
        if(!el){el=document.createElement('div');el.className='tile';el.dataset.co=c.id;el.dataset.tco=c.id;tilesBox.appendChild(el);tiles[c.id]=el;el.style.left=(r3.x+r3.w/2)+'px';el.style.top=(r3.y+r3.h/2)+'px';el.style.width='0px';el.style.height='0px';void el.offsetWidth}
        const x=r3.x+1,y=r3.y+1,w=Math.max(0,r3.w-2),h=Math.max(0,r3.h-2),col=tileColor(rankValue(c,M.k),M);
        el.classList.remove('gone');el.style.left=x.toFixed(1)+'px';el.style.top=y.toFixed(1)+'px';el.style.width=w.toFixed(1)+'px';el.style.height=h.toFixed(1)+'px';el.style.backgroundColor=col.bg;el.classList.toggle('dark-t',col.P.L&&col.a<.45);el.innerHTML=tileInner(c,w,h,M)})})});
  Object.keys(tiles).forEach(id=>{if(!seen[id])tiles[id].classList.add('gone')});
  $('#mapLabels').innerHTML=labels||'<div class="muted" style="padding:24px">当前筛选无匹配公司，请调整行业或市场。</div>';
  const P=pal(),ramp=M.neg?`linear-gradient(90deg,${P.down},${P.neu})`:`linear-gradient(90deg,${P.down},${P.neu},${P.up})`;
  $('#mapLegend').innerHTML=`<span>${M.l}</span>${M.neg?`<span class="num">${pct(-M.dom,0)}</span><span class="ramp" style="background:${ramp}"></span><span class="num">0%</span>`:`<span class="num">${pct(-M.dom,0)}</span><span class="ramp" style="background:${ramp}"></span><span class="num">${pct(M.dom,0)}</span>`}<span>· 灰色 = 暂无数据/不参排</span><span class="sp"></span><span>${list.length} 家 · 面积 ≈ 市值(美元)^0.4，小市值设最小面积；市值缺失用占位面积</span>`}
function tileTip(c){const M=METRICS.find(m=>m.k===S.metric);return`<div class="tt">${esc(c.name)}</div><div class="muted" style="font-size:11px">${esc(c.code)} · ${esc(c.mkt)} · ${esc(c.cp)}</div>
  <div style="margin:6px 0 4px">${sgBadges(c)}</div>
  <div class="tr"><span>${M.l}</span><b class="num ${ud(rankValue(c,M.k))}">${['revg','earng'].includes(M.k)?financialNumber(c,M.k):pct(rankValue(c,M.k))}</b></div>${metricGap(c,M.k)?`<div class="muted">${esc(metricGap(c,M.k))}</div>`:''}
  ${M.k!=='r20'?`<div class="tr"><span>近20日</span><b class="num ${ud(c.r20)}">${pct(c.r20)}</b></div>`:''}
  <div class="tr"><span>${c.financialPartial?esc(c.period)+' · ':''}营收 / 净利同比</span><b class="num">${financialCell(c,'revg')} / ${financialCell(c,'earng')}</b></div>
  <div class="tr"><span>市值${c.mcapEstimated&&fin(c.mcapUSD)?'（估算）':''}</span><b>${c.mcapEstimated&&fin(c.mcapUSD)?'≈ ':''}${mcapStr(c.mcapUSD)}</b></div><div class="muted">FX ${esc(c.provenance?.valuation?.fx?.asOf||'暂未取得')} · ${esc(nativeCapText(c))}</div>${spark(c,120,240,36)}<div class="muted" style="font-size:10.5px">${c.sc.length>=120?'近120个交易日':`短历史 · 实际 ${c.sc.length} 个交易日`} · 点击查看详情</div>`}

/* ---------- table ---------- */
const PL={r5:'近5日',r20:'近20日',r60:'近60日',ytd:'年初至今',dd52:'距高点',revg:'营收同比',earng:'净利同比'};
const COLS=[
  {k:'name',l:'公司',c:'l',v:c=>c.short,s:1,f:c=>`<div class="tc-n"><i style="background:${IC(c.ind)}"></i><div><b>${esc(c.short)}</b><span>${esc(c.code)} · ${esc(c.mkt)}</span></div></div>`},
  {k:'cp',l:'卡点',c:'l',v:c=>c.cp,s:1,f:c=>`<div class="cpc" title="${esc(c.cp)}">${esc(c.cp)}</div>`},
  {k:'sig',l:'信号',c:'l',v:c=>c.perf.r*10+c.px.r,f:sgBadges},
  {k:'spark',l:'走势（最多60日）',c:'l',ns:1,f:c=>spark(c,60,92,26)+`<div class="muted" style="font-size:10px">${sparkHistoryLabel(c)} · ${esc(c.metricAsOf||c.ld||'日期未知')} 收盘</div>`},
  {k:'price',l:'最新价',ns:1,coverage:1,v:c=>c.price,f:c=>`<span class="num" data-tip="${esc(timeDetail(c))}">${fmtPrice(c)}</span><div class="muted" style="font-size:10px">${esc(quoteLabel(c))}</div>`}]
  .concat(Object.keys(PL).map(k=>({k,l:PL[k],coverage:1,v:c=>rankValue(c,k),f:c=>['revg','earng'].includes(k)?financialCell(c,k,k==='revg'):`<span class="num ${ud(rankValue(c,k))}">${pct(rankValue(c,k))}</span>${metricGap(c,k)?`<div class="muted" style="font-size:10px;white-space:normal">${esc(metricGap(c,k))}</div>`:''}`})))
  .concat([{k:'gm',l:'毛利率',coverage:1,v:c=>rankValue(c,'gm'),f:c=>financialCell(c,'gm')},
  {k:'pe',l:'PE(TTM)',coverage:1,v:c=>c.pe,f:c=>`<span class="num">${fin(c.pe)?c.pe.toFixed(1):'—'}</span><div class="muted" style="font-size:10px">${esc(peStatusText(c))}${peStatusText(c)?' · ':''}${esc(c.provenance?.valuation?.asOf||'日期未知')}</div>`},
  {k:'mcapUSD',l:'市值(亿$)',coverage:1,v:c=>c.mcapUSD,f:c=>`<span class="num">${c.mcapEstimated&&fin(c.mcapUSD)?'≈ ':''}${fin(c.mcapUSD)?Math.round(c.mcapUSD).toLocaleString('en-US'):'—'}</span><div class="muted" style="font-size:10px" data-tip="${esc(timeDetail(c))}">${c.mcapEstimated&&fin(c.mcapUSD)?'估算 · ':''}${esc(c.provenance?.valuation?.asOf||'日期未知')}<br>FX ${esc(c.provenance?.valuation?.fx?.asOf||'暂未取得')}<br>${esc(nativeCapText(c))}</div>`},
  {k:'next',l:'财报日期',v:c=>c.next,s:1,f:c=>eventPill(c,true)}]);
function renderTable(){const col=COLS.find(x=>x.k===S.sort.k)||COLS[6],dir=S.sort.d;
  const rows=filtered().slice().sort((a,b)=>compareRows(a,b,col,dir));
  $('#tbl').innerHTML=`<thead><tr>${COLS.map(c=>`<th class="${c.c||''} ${c.k===S.sort.k?'sorted':''}" data-sort="${c.ns?'':c.k}">${c.l}${c.k===S.sort.k?`<span class="ar">${dir<0?'↓':'↑'}</span>`:''}${c.coverage?`<div class="muted" style="font-size:10px">有效 ${coverageText(rows,c.v)}</div>`:''}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.map(r=>`<tr data-co="${r.id}">${COLS.map(c=>`<td class="${c.c||''}">${c.f(r)}</td>`).join('')}</tr>`).join(''):`<tr class="empty-state"><td colspan="${COLS.length}">当前筛选无匹配公司，请调整行业或市场。</td></tr>`}</tbody>`}
function renderLeaders(){if(S.view==='map'){$('#mapCard').hidden=false;$('#tableCard').hidden=true;renderMap()}else{$('#mapCard').hidden=true;$('#tableCard').hidden=false;renderTable()}
  const list=filtered(),metric=METRICS.find(x=>x.k===S.metric),coverage=` · 当前 ${list.length} 家 · ${metric.l}有效 ${coverageText(list,c=>rankValue(c,S.metric))} · 市值有效 ${coverageText(list,c=>c.mcapUSD)} · PE有效 ${coverageText(list,c=>c.pe)} · 有效样本不含缺值及不参排项 · 收盘折线；价格详情列时点/FX`;
  $('#leadSub').textContent=(S.view==='map'?'按行业 → 卡点分组 · 已知市值决定面积；缺失用占位面积 · 颜色=所选指标':'点击表头排序 · 点击行查看走势与财务 · 颜色：'+(S.conv==='cn'?'红涨绿跌':'绿涨红跌'))+coverage}

/* ---------- calendar ---------- */
function renderCal(){const list=CO.filter(c=>c.next).sort((a,b)=>a.next.localeCompare(b.next)||(b.mcapUSD||0)-(a.mcapUSD||0)),dates=Array.from(new Set(list.map(c=>c.next)));
  $('#calSub').textContent=`今天 ${md(TODAY)} ${wd(TODAY)} · ${eventSummary(CO)} · 日期按公司所在地时区`;
  let h=`<div class="cal-col is-today"><div class="cal-top"><div class="cal-d num">${md(TODAY)}</div><div class="cal-cd">今天</div></div><div class="cal-w">${wd(TODAY)}</div><div class="hint">行情截至 ${ASOFL}${WK.calHint?'<br>'+esc(WK.calHint):''}</div></div>`,prev=TODAY;
  dates.forEach(d=>{const gap=daysTo(d)-daysTo(prev);if(gap>4)h+=`<div class="cal-gap mono">··· ${gap} 天 ···</div>`;const cs=list.filter(c=>c.next===d);
    h+=`<div class="cal-col ${cs.length>=4?'busy':''}"><div class="cal-top"><div class="cal-d num">${md(d)}</div><div class="cal-cd">${eventCountdown(d)}</div></div><div class="cal-w">${wd(d)} · ${cs.length} 家</div>${cs.map(c=>eventPill(c)).join('')}</div>`;prev=d});
  $('#cal').innerHTML=h;$('#calLegend').innerHTML=KEY_IND.map(n=>`<span><i style="background:${IC(n)}"></i>${esc(n)}</span>`).join('')+calendarLegend()}

/* ---------- drawer ---------- */
const FIN_BASIS={single_quarter:'单季',half_year:'半年累计',cumulative:'累计',annual:'全年'};
const REPORT_STATUS={final:'正式报告',formal:'正式报告',express:'业绩快报',forecast:'业绩预告',preliminary:'初步结果',revenue_only:'仅营收'};
function financialKind(c){const f=c.provenance?.financial;return f?.evidence||(f?.status==='verified'?'source':f?.status==='verified_partial'?'partial':'missing')}
function financialReason(c){const f=c.provenance?.financial||{},k=financialKind(c);if(k==='partial')return`${c.period||'期间缺失'} · ${REPORT_STATUS[f.report_status]||f.report_status||'报告状态缺失'} · 只展示，不参与信号`;if(k==='missing')return'没有来源链接，不参与任何统计';if(f.period_end&&daysTo(f.period_end)<-200)return'期末日超过 200 天，不参与业绩信号';if(!['final','formal'].includes(f.report_status))return'不是正式报告，不参与业绩信号';if(f.profit_comparison==='turnaround')return'上年同期为亏损，同比不适用';if(f.profit_comparison==='one_off')return'含一次性项目，利润不可比，不参与信号';if(f.profit_comparison==='not_disclosed')return'利润可比性未披露，不参与信号';return c.financialSignalEligible?'正式报告 · 单季 · 利润可比':'数据不满足可比条件，不参与业绩信号'}
function financialTag(c){const k=financialKind(c);return statusTag(k==='source'?'src':k==='partial'?'src part':'src none',k==='source'?'有原文':k==='partial'?'部分':'缺来源',k==='source'?'已附原始披露来源':financialReason(c),true)}
function financialNumber(c,key){const f=c.provenance?.financial||{};if(key==='earng'&&f.profit_comparison==='turnaround')return'扭亏';if(key==='earng'&&f.profit_comparison==='one_off')return'一次性';if(key==='gm')return fin(c.gm)?(c.gm*100).toFixed(1)+'%':'—';return pct(c[key],1)}
function financialCell(c,key,tag=false){const grey=financialKind(c)!=='source'||key==='earng'&&c.provenance?.financial?.profit_comparison==='not_disclosed';return`<span class="num ${grey?'muted':key==='gm'?'':ud(c[key])}" data-tip="${esc(finDetail(c))}">${financialNumber(c,key)}</span>${tag&&financialKind(c)!=='source'?' '+financialTag(c)+(financialKind(c)==='partial'?`<small class="financial-period muted"> · ${esc(c.period)}</small>`:''):''}`}
function finLabel(c){const f=c.provenance?.financial||{};return[c.period,FIN_BASIS[f.basis],REPORT_STATUS[f.report_status]||f.report_status,f.currency,(f.accounting_basis||'').split(';')[0]].filter(Boolean).join(' · ')}
function finDetail(c){const f=c.provenance?.financial||{};return[finLabel(c),financialReason(c),f.accounting_basis,f.profit_metric,f.revenue_scope,f.profit_scope,f.margin_scope,f.source_name,`发布 ${f.published_at||'未知'} · 录入 ${f.entered_at||f.verified_at||'未知'}`,...(f.source_urls||[]),...(f.conditions||[])].filter(Boolean).join('；')}
function peLabel(c){return 'PE(TTM)'+(peStatusText(c)?' · '+peStatusText(c):'')}
function financialEvidence(c){if(!c.provenance?.financial)return'<div class="evidence-card">暂无财报记录</div>';const f=c.provenance?.financial||{},urls=[...new Set([...(f.source_urls||[]),f.source_url].filter(Boolean))].filter(safeResearchUrl);
 const fields=[['发布日 / 录入日',`${f.published_at||'缺失'} / ${f.entered_at||f.verified_at||'缺失'}`],['原始来源',f.source_name],['会计口径',f.accounting_basis],['收入 / 利润口径',[f.revenue_scope,f.profit_scope,f.profit_metric].filter(Boolean).join('；')],['毛利率口径',f.margin_scope],['计算说明',f.calculation_note],['录入说明',f.review_note]];
 return`<details class="evidence-card financial-evidence" data-src="notion"><summary>财务来源 · ${esc(c.period||'期间缺失')} · ${esc(REPORT_STATUS[f.report_status]||f.report_status||'报告状态缺失')} ${financialTag(c)}</summary><dl>${fields.filter(x=>x[1]).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl><div class="evidence-links">${urls.length?urls.map(u=>researchAnchor(u)).join(''):'原文链接缺失'}</div>${f.conditions?.length?`<ul>${f.conditions.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}</details>`;
}
function marketEvidence(c){const p=c.provenance||{},d=p.daily||{},v=p.valuation||{},f=v.fx||{};const fxSymbol=c.cur==='EUR'?'EURUSD=X':c.cur+'=X';
  return`<details class="evidence-card market-evidence"><summary>行情与估值来源 · ${esc(c.priceAsOf||'日期缺失')}</summary><dl><dt>展示报价</dt><dd>${esc(timeDetail(c))} · ${sourceAnchor(providerUrl(c.sym,c.priceSource),'报价来源')}</dd><dt>完成日线 / 收益口径</dt><dd>${esc(d.asOf||'日期缺失')} · ${esc(d.returnBasis||'口径未提供')} · ${sourceAnchor(providerUrl(c.sym,d.src,true),'日线来源')}</dd><dt>估值</dt><dd>${esc(v.asOf||'日期缺失')} · ${esc(peLabel(c))} · ${sourceAnchor(providerUrl(c.sym,v.source),'估值来源')}</dd><dt>美元折算</dt><dd>${c.cur==='USD'?'原币为 USD，无需折算':`${esc(f.asOf||'日期缺失')} · ${!f.asOf?'汇率缺失':c.mcapEstimated?'跨日汇率估算':'同日汇率'} · ${sourceAnchor(providerUrl(fxSymbol,f.src,true),'汇率来源')}`}</dd></dl><p>行情链接打开供应商当前页面或接口，并非冻结历史快照。计算仍以本页标注日期为准；链接可打开不等于缺项已补齐。</p></details>`;
}
function rangeComplete(c,r){if(c.t.length<2)return false;const last=c.t[c.t.length-1],cut=r==='ytd'?Date.UTC(new Date(last).getUTCFullYear(),0,1):last-({'1m':31,'3m':92,'6m':183,'1y':366,'2y':731}[r]||0)*864e5;return c.t[0]<=cut}
const ORDER=CO.map(c=>c.id);
let drawerReturn=null;
function flashHTML(c){if(!c.flash)return'';const stale=Object.hasOwn(c,'flashDate')&&(c.flashFresh===false||!!c.flashDate&&daysTo(c.flashDate)<-30);return`<div class="flash-box${stale?' is-stale':''}" data-src="notion">${ICON.bolt}<div><div class="t">业绩快讯${c.flashDate?' · '+esc(md(c.flashDate))+(stale?' · 已过期':''):''}</div><p>${earningsHTML(c.flash)}</p>${c.flashSource?researchAnchor(c.flashSource,'快讯来源'):''}</div></div>`}
function activateDrawer(){const dr=$('#drawer');hideTip();dr.classList.add('on');dr.setAttribute('aria-hidden','false');$('#mask').classList.add('on');document.body.style.overflow='hidden';requestAnimationFrame(()=>$('#dwClose')?.focus())}
function openReason(kind,name,trigger){const row=kind==='weekly'?WK:kind==='industry'?IND.find(x=>x.name===name):CP.find(x=>x.name===name);if(!row)return;drawerReturn=trigger||document.activeElement;S.drawer='__reason__';S.drawerType='research';const j=kind==='weekly'?judgmentOf(WK):judgmentOf(row),title=kind==='weekly'?'本周主线':name,urls=(j.sources||[]).filter(safeResearchUrl),reasons=j.reasons||[];
 $('#drawer').innerHTML=`<div class="dw research-reason" data-src="notion"><div class="dw-h"><h3>${esc(title)} · 研判理由</h3><button type="button" class="icon-btn sq" id="dwClose" aria-label="关闭理由（Esc）">${ICON.x}</button></div><div class="prov">${judgmentTag(j)}</div>${reasons.length?`<ul class="reason-list">${reasons.map(x=>`<li>${esc(reasonText(x,j))}</li>`).join('')}</ul>`:''}<dl class="reason-dates"><dt>研判日期</dt><dd class="num">${esc(j.date||'未填写')}</dd><dt>有效至</dt><dd class="num">${esc(j.validUntil||'未填写')}</dd></dl><p class="reason-body" id="reasonBody"></p><div class="bl">依据来源</div><div class="evidence-links">${urls.length?urls.map(u=>researchAnchor(u)).join(''):'<span class="muted">缺来源链接</span>'}</div>${kind==='industry'?`<div class="anchor-list">${DIMS.map(x=>{const a=j.anchors?.[x.n],c=(j.conflicts||[]).find(c=>c.field===x.n);return`<div><span>${x.n}</span><b class="num">${row.s[x.k]}</b>${a?`<small>数据档 <span class="num">${a.anchor}</span></small>`:''}${c?statusTag('conflict','数据冲突',conflictText(c,j),true):''}</div>${c?`<p class="hint">${esc(conflictText(c,j))}</p>`:''}`}).join('')}</div>`:''}</div>`;
 $('#reasonBody').textContent=j.reason||'研判理由未填写';activateDrawer();
}
function openDrawer(id,trigger){const c=byId[id];if(!c)return;if(!S.drawer)drawerReturn=trigger||document.activeElement;S.drawer=id;S.drawerType='company';const cp=CP.find(x=>x.name===c.cp),k=ORDER.indexOf(id);hideTip();
  const dr=$('#drawer');
  dr.innerHTML=`<div class="dw"><div class="dw-h"><div class="crumb"><i style="background:${IC(c.ind)}"></i>${esc(c.ind)}<span class="sep">›</span>${esc(c.cp)}${cp?tbBadge(cp.tight):''}</div><div class="dw-nav"><button class="icon-btn sq" data-step="-1" title="上一家（←）">${ICON.left}</button><button class="icon-btn sq" data-step="1" title="下一家（→）">${ICON.right}</button><button class="icon-btn sq" id="dwClose" title="关闭（Esc）">${ICON.x}</button></div></div>
  <div class="dw-title"><h3>${esc(c.name)}</h3><div class="dw-tags"><span class="tag mono">${esc(c.code)}</span><span class="tag">${esc(c.mkt)}</span>${c.role?`<span class="tag">${esc(c.role)}</span>`:''}${sgBadges(c)}</div></div>
  <div class="dw-price"><span class="big num">${fmtPrice(c)}</span><span class="chg num ${ud(c.r1d)}">日线 ${pct(c.r1d,2)}</span><span class="meta">${esc(timeDetail(c))}${c.stale?' · 日线暂未更新':''} · 市值 ${c.mcapEstimated&&fin(c.mcapUSD)?'≈ ':''}${mcapStr(c.mcapUSD)} · 第 ${k+1}/${ORDER.length} 家</span></div>
  <div class="dw-range"><div class="seg" id="rangeSeg"></div></div>
  <div class="dw-chart" id="dwChart"></div>
  <div class="mgrid">${[['近5日','r5'],['近20日','r20'],['近60日','r60'],['年初至今','ytd'],['距52周高点','dd52']].map(([label,key])=>`<div class="mt"><div class="l">${label}</div><div class="v num ${ud(c[key])}">${pct(c[key])}</div>${metricGap(c,key)?`<div class="muted" style="font-size:10px">${esc(metricGap(c,key))}</div>`:''}</div>`).join('')}</div>
  <div class="dw-sec" data-tip="${esc(finDetail(c))}">近期财务<span>${esc(finLabel(c))}</span></div>
  <div class="mgrid four">${[['营收同比',financialCell(c,'revg'),''],['净利同比',financialCell(c,'earng'),''],['毛利率',financialCell(c,'gm'),''],[peLabel(c),fin(c.pe)?c.pe.toFixed(1):'—','']].map(m=>`<div class="mt"><div class="l">${m[0]}</div><div class="v num ${m[2]}">${m[1]}</div></div>`).join('')}</div>
  ${financialEvidence(c)}${marketEvidence(c)}
  ${flashHTML(c)}
  ${c.view?`<div class="view-box" data-src="notion"><div class="t">一句话看点</div><p>${esc(c.view)}</p></div>`:''}
  <div class="dw-next">${ICON.cal}财报日期 ${eventPill(c,true)}${c.next?`<span class="cd">${eventCountdown(c.next)}</span>`:''}</div>
  <div class="earnings-evidence">${esc(eventTip(c))}${hasConfirmedEvent(c)?` · ${sourceAnchor(c.earnings.source_url,'日期来源')}`:''}</div>
  <div class="dw-actions">${c.url?researchAnchor(c.url,'知识库笔记'):'<span class="hint">研究笔记来源未接通</span>'}<button class="btn${c.url?'':' primary'}" data-gocp="${esc(c.ind)}" data-cpname="${esc(c.cp)}">查看所在卡点 ${ICON.arrow}</button></div></div>`;
  seg($('#rangeSeg'),[{v:'1m',l:'1月'},{v:'3m',l:'3月'},{v:'6m',l:'6月'},{v:'ytd',l:'年初至今'},{v:'1y',l:'1年'},{v:'2y',l:'2年'}].map(o=>({...o,l:rangeComplete(c,o.v)?o.l:o.l+'·不足'})),S.range,v=>{S.range=v;drawChart(c)});
  activateDrawer();
  requestAnimationFrame(()=>{drawChart(c);moveThumb($('#rangeSeg'))})}
function closeDrawer(){const dr=$('#drawer');dr.classList.remove('on');dr.setAttribute('aria-hidden','true');$('#mask').classList.remove('on');document.body.style.overflow='';S.drawer=null;S.drawerType=null;if(drawerReturn?.isConnected)drawerReturn.focus();drawerReturn=null;hideTip()}
function stepDrawer(n){if(S.drawerType!=='company')return;const k=(ORDER.indexOf(S.drawer)+n+ORDER.length)%ORDER.length;openDrawer(ORDER[k]);$('#drawer').scrollTop=0}
const fmtAx=v=>v>=1000?Math.round(v).toLocaleString('en-US'):v>=100?v.toFixed(1):v.toFixed(2);
const fmtDay=(t,long)=>{const d=new Date(t);return long?`${String(d.getUTCFullYear()).slice(2)}年${d.getUTCMonth()+1}月`:`${d.getUTCMonth()+1}/${d.getUTCDate()}`};
function drawChart(c){const box=$('#dwChart');if(!box)return;const W=Math.max(280,box.clientWidth),H=240,pl=6,pr=60,pt=14,pb=26,n=c.t.length,last=c.t[n-1],range=S.range;let i0=0;
  if(range==='ytd'){const y0=Date.UTC(new Date(last).getUTCFullYear(),0,1);i0=c.t.findIndex(t=>t>=y0)}else{const days={'1m':31,'3m':92,'6m':183,'1y':366,'2y':731}[range];i0=c.t.findIndex(t=>t>=last-days*864e5)}
  if(i0<0)i0=0;const T=c.t.slice(i0),V=c.sc.slice(i0);if(V.length<2){box.innerHTML='<div class="muted" style="padding:40px 0;text-align:center">暂无行情</div>';return}
  let mn=Math.min.apply(null,V),mx=Math.max.apply(null,V);const showHi=fin(c.hi52)&&c.hi52<=mx*1.3&&c.hi52>=mn;if(showHi)mx=Math.max(mx,c.hi52);const pv=(mx-mn)*.08||1;mn-=pv;mx+=pv;
  const X=i=>pl+(W-pl-pr)*i/(V.length-1),Y=v=>pt+(H-pt-pb)*(1-(v-mn)/(mx-mn)),d='M'+V.map((v,i)=>X(i).toFixed(1)+','+Y(v).toFixed(1)).join('L'),k=V[V.length-1]>=V[0]?'up':'down',chg=V[V.length-1]/V[0]-1,long=['1y','2y'].indexOf(range)>=0;
  let g='';for(let j=0;j<4;j++){const v=mn+(mx-mn)*(j+.5)/4,y=Y(v);g+=`<line class="gl" x1="${pl}" x2="${W-pr}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/><text class="ax" x="${W-pr+8}" y="${(y+3.5).toFixed(1)}">${fmtAx(v)}</text>`}
  const xi=[0,Math.round((V.length-1)/2),V.length-1],xl=xi.map((i,j)=>`<text class="ax" x="${X(i).toFixed(1)}" y="${H-7}" text-anchor="${j===0?'start':j===2?'end':'middle'}">${fmtDay(T[i],long)}</text>`).join('');
  const hi=showHi?`<line class="hi" x1="${pl}" x2="${W-pr}" y1="${Y(c.hi52).toFixed(1)}" y2="${Y(c.hi52).toFixed(1)}"/><text class="ax hi-t" x="${pl+4}" y="${(Y(c.hi52)-5).toFixed(1)}">52周高点 ${fmtAx(c.hi52)}</text>`:'';
  box.innerHTML=`<div class="ch-h"><span class="muted">${rangeComplete(c,range)?'收盘折线 · 区间涨跌':`收盘折线 · ${esc(historyGap(c))}`}</span><b class="num ${ud(chg)}">${pct(chg)}</b><span class="muted">· ${new Date(T[0]).toISOString().slice(0,10)} – ${new Date(T[T.length-1]).toISOString().slice(0,10)}</span></div><svg class="chart ${k}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${g}${hi}<path d="${d}L${X(V.length-1).toFixed(1)},${H-pb}L${X(0)},${H-pb}Z" fill="url(#g-${k})"/><path class="line" d="${d}"/>${xl}<circle class="lastdot" cx="${X(V.length-1).toFixed(1)}" cy="${Y(V[V.length-1]).toFixed(1)}" r="3" style="fill:var(--${k})"/><g class="cross" style="opacity:0"><line class="cx" y1="${pt}" y2="${H-pb}"/><circle class="cd" r="4.5"/></g><rect class="hit" x="${pl}" y="0" width="${W-pl-pr}" height="${H}" fill="transparent"/></svg><div class="ch-tip"></div>`;
  const svg=$('svg',box),cr=$('.cross',svg),cx=$('.cx',svg),cd=$('.cd',svg),tp=$('.ch-tip',box),hit=$('.hit',svg);
  const mv=e=>{const r=svg.getBoundingClientRect(),x=(e.clientX-r.left)*(W/r.width);let i=Math.round((x-pl)/(W-pl-pr)*(V.length-1));i=Math.max(0,Math.min(V.length-1,i));const px=X(i),py=Y(V[i]);cx.setAttribute('x1',px);cx.setAttribute('x2',px);cd.setAttribute('cx',px);cd.setAttribute('cy',py);cr.style.opacity=1;const ch=V[i]/V[0]-1;tp.innerHTML=`<b>${new Date(T[i]).toISOString().slice(0,10)}</b>&nbsp; ${fmtAx(V[i])} &nbsp;<span class="${ud(ch)}">${pct(ch)}</span>`;tp.style.left=Math.max(70,Math.min(W-90,px*(r.width/W)))+'px';tp.classList.add('on')};
  hit.addEventListener('pointermove',mv);hit.addEventListener('pointerdown',mv);hit.addEventListener('pointerleave',()=>{cr.style.opacity=0;tp.classList.remove('on')})}

/* ---------- palette ---------- */
const PAL=[].concat(IND.map(d=>({t:'行业',ic:'业',n:d.name,k:d.reps,m:`${d.total} 分 · ${levelOf(d.total).l}`,go:()=>{selectInd(d.name,true)}})),
  CP.map(cp=>({t:'卡点',ic:'卡',n:cp.name,k:cp.seg,m:`${cp.ind} · ${TIGHT[cp.tight]?TIGHT[cp.tight].l:''}`,go:()=>gotoCp(cp.ind,cp.name)})),
  CO.map(c=>({t:'公司',ic:c.mkt.slice(0,1),n:c.name,k:c.code+' '+c.sym,m:`${c.code} · 近20日 ${pct(c.r20)}`,go:()=>openDrawer(c.id)})));
let pSel=0,pRes=[];
function hl(s,q){if(!q)return esc(s);const i=s.toLowerCase().indexOf(q);return i<0?esc(s):esc(s.slice(0,i))+'<mark>'+esc(s.slice(i,i+q.length))+'</mark>'+esc(s.slice(i+q.length))}
function palSearch(q){const OR=['行业','卡点','公司'],sc=p=>{const n=p.n.toLowerCase(),i=n.indexOf(q);return i===0?0:i>0?1:2};
  const m=PAL.filter(p=>p.n.toLowerCase().indexOf(q)>=0||(p.k||'').toLowerCase().indexOf(q)>=0).map(p=>({p,s:sc(p)}));
  const gs=OR.map(t=>{const it=m.filter(x=>x.p.t===t).sort((a,b)=>a.s-b.s);return{t,it,b:it.length?it[0].s:9}}).filter(g=>g.it.length).sort((a,b)=>a.b-b.b||OR.indexOf(a.t)-OR.indexOf(b.t));
  return[].concat.apply([],gs.map(g=>g.it.map(x=>x.p))).slice(0,24)}
function renderPal(){const q=$('#pq').value.trim().toLowerCase();
  pRes=q?palSearch(q):[].concat(PAL.filter(p=>p.t==='行业').slice(0,4),PAL.filter(p=>p.t==='卡点'&&p.m.indexOf('极紧')>=0),PAL.filter(p=>p.t==='公司').slice(0,6));
  if(pSel>=pRes.length)pSel=0;let h='',last='';
  pRes.forEach((p,i)=>{if(p.t!==last){h+=`<div class="pg">${p.t}</div>`;last=p.t}h+=`<div class="pi ${i===pSel?'on':''}" data-pi="${i}"><span class="ic">${esc(p.ic)}</span><span>${hl(p.n,q)}</span><span class="m">${esc(p.m)}</span></div>`});
  $('#plist').innerHTML=h||'<div class="pempty">没有找到匹配项，试试公司名、代码或行业</div>';const on=$('.pi.on',$('#plist'));if(on)on.scrollIntoView({block:'nearest'})}
function openPal(){const p=$('#palette');p.hidden=false;$('#pq').value='';pSel=0;renderPal();setTimeout(()=>$('#pq').focus(),10)}
function closePal(){$('#palette').hidden=true}
function runPal(i){const p=pRes[i];if(!p)return;closePal();p.go()}
function gotoCp(ind,name){closeDrawer();if(S.cpInd!==ind){S.cpInd=ind;setSeg($('#cpSeg'),ind);renderFlow()}document.getElementById('choke').scrollIntoView({behavior:SB()});
  if(name)setTimeout(()=>{const el=$$('#flow .cp-card').find(e=>e.dataset.cpname===name);if(el){el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash')}},450)}

/* ---------- tooltip ---------- */
const tip=$('#tip');let tipOn=null;
function placeTip(x,y){const w=tip.offsetWidth,h=tip.offsetHeight;let L=x+14,T=y+16;if(L+w>innerWidth-8)L=x-w-14;if(T+h>innerHeight-8)T=y-h-12;tip.style.transform=`translate(${Math.max(6,L)}px,${Math.max(6,T)}px)`}
function showTip(h,x,y){tip.innerHTML=h;tip.classList.add('on');placeTip(x,y)}
function hideTip(){tip.classList.remove('on');tipOn=null}
document.addEventListener('pointerover',e=>{if(e.pointerType==='touch')return;const t=e.target.closest('[data-tco],[data-tip]');if(!t||t===tipOn)return;tipOn=t;if(t.dataset.tco)showTip(tileTip(byId[t.dataset.tco]),e.clientX,e.clientY);else showTip(esc(t.dataset.tip),e.clientX,e.clientY)});
document.addEventListener('pointermove',e=>{if(tipOn){if(!tipOn.isConnected||!tipOn.contains(e.target)){hideTip();return}placeTip(e.clientX,e.clientY)}
  const card=e.target.closest&&e.target.closest('.card');if(card){const r=card.getBoundingClientRect();card.style.setProperty('--mx',(e.clientX-r.left)+'px');card.style.setProperty('--my',(e.clientY-r.top)+'px')}},{passive:true});
document.addEventListener('scroll',()=>{if(!tipOn)return;if(document.activeElement===tipOn){const r=tipOn.getBoundingClientRect();placeTip(r.left,r.bottom)}else hideTip()},{passive:true});
document.addEventListener('focusin',e=>{const t=e.target.closest('[data-tip]');if(t){tipOn=t;const r=t.getBoundingClientRect();showTip(esc(t.dataset.tip),r.left,r.bottom)}});
document.addEventListener('focusout',e=>{if(e.target.closest('[data-tip]'))hideTip()});

/* ---------- events ---------- */
document.addEventListener('click',e=>{const t=e.target;let el;
  if(t.closest('#dwClose')||t.closest('#mask')){closeDrawer();return}
  if((el=t.closest('[data-step]'))){stepDrawer(+el.dataset.step);return}
  if((el=t.closest('[data-gocp]'))){gotoCp(el.dataset.gocp,el.dataset.cpname);return}
  if((el=t.closest('[data-pi]'))){runPal(+el.dataset.pi);return}
  if(t.closest('.palette')&&!t.closest('.pbox')){closePal();return}
  if((el=t.closest('th[data-sort]'))&&el.dataset.sort){const k=el.dataset.sort,col=COLS.find(c=>c.k===k);S.sort=S.sort.k===k?{k,d:-S.sort.d}:{k,d:col&&col.s?1:-1};renderTable();return}
  if((el=t.closest('[data-reason-kind]'))){openReason(el.dataset.reasonKind,el.dataset.reasonName,el);return}
  if((el=t.closest('[data-co]'))){openDrawer(el.dataset.co,el);return}
  if((el=t.closest('[data-ind]'))){selectInd(el.dataset.ind,true);return}
  if((el=t.closest('[data-pick]'))){selectInd(el.dataset.pick,false);if(innerWidth<1180)$('#indDetail').scrollIntoView({behavior:SB(),block:'start'});return}
});
const typing=e=>{const t=e.target;return t&&(t.tagName==='INPUT'||t.tagName==='TEXTAREA'||t.isContentEditable)};
document.addEventListener('keydown',e=>{const pal=!$('#palette').hidden;
  if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();pal?closePal():openPal();return}
  if(pal){if(e.key==='Escape'){closePal()}else if(e.key==='ArrowDown'){e.preventDefault();pSel=Math.min(pRes.length-1,pSel+1);renderPal()}else if(e.key==='ArrowUp'){e.preventDefault();pSel=Math.max(0,pSel-1);renderPal()}else if(e.key==='Enter'){e.preventDefault();runPal(pSel)}return}
  if(e.key==='/'&&!typing(e)){e.preventDefault();openPal();return}
  if(S.drawer&&e.key==='Tab'){const f=$$('button:not([disabled]),a[href],input,[tabindex="0"]',$('#drawer')).filter(x=>x.offsetParent!==null),first=f[0],last=f[f.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}return}
  if(!S.drawer&&(e.key==='Enter'||e.key===' ')&&e.target.matches('[data-ind],[data-pick]')){e.preventDefault();e.target.click();return}
  if(e.key==='Escape'&&S.drawer){closeDrawer();return}
  if(S.drawerType==='company'&&!typing(e)&&(e.key==='ArrowRight'||e.key==='ArrowLeft')){e.preventDefault();stepDrawer(e.key==='ArrowRight'?1:-1)}});
$('#pq').addEventListener('input',()=>{pSel=0;renderPal()});
$('#plist').addEventListener('pointermove',e=>{const el=e.target.closest('[data-pi]');if(el&&+el.dataset.pi!==pSel){pSel=+el.dataset.pi;$$('.pi',$('#plist')).forEach(x=>x.classList.toggle('on',+x.dataset.pi===pSel))}});
$('#openPalette').addEventListener('click',openPal);
const isMac=/Mac|iPhone|iPad/.test(navigator.platform||navigator.userAgent);$('#kbdHint').textContent=isMac?'⌘K':'Ctrl K';
function applyTheme(){html.dataset.theme=S.theme;$('#themeBtn').innerHTML=S.theme==='dark'?ICON.sun:ICON.moon;$('#themeBtn').title=S.theme==='dark'?'切换到浅色':'切换到深色'}
function applyConv(){html.dataset.conv=S.conv;$('#convLabel').textContent=S.conv==='cn'?'红涨绿跌':'绿涨红跌'}
$('#themeBtn').addEventListener('click',()=>{S.theme=S.theme==='dark'?'light':'dark';store.set('ar-theme',S.theme);applyTheme();if(S.view==='map')renderMap()});
$('#convBtn').addEventListener('click',()=>{S.conv=S.conv==='cn'?'intl':'cn';store.set('ar-conv',S.conv);applyConv();renderLeaders()});
$('#icSearch').innerHTML=ICON.search;$('#icSearch2').innerHTML=ICON.search;

/* ---------- footer ---------- */
/* ---------- publication status and factual changes ---------- */
let remoteVersion=null,versionError=false,versionBusy=false;
function shortTime(value){if(!value)return'时间缺失';const date=new Date(value);if(!Number.isFinite(+date))return'时间缺失';const local=new Date(+date+8*3600e3),year=local.getUTCFullYear(),prefix=year===+TODAY.slice(0,4)?'':year+'/';return`${prefix}${local.getUTCMonth()+1}/${local.getUTCDate()} ${String(local.getUTCHours()).padStart(2,'0')}:${String(local.getUTCMinutes()).padStart(2,'0')}`}
function quoteMissingCount(){const marked=new Set([...(D.meta.stale||[]),...(Array.isArray(D.meta.missing)?D.meta.missing:[])]);return CO.filter(c=>!fin(c.price)||marked.has(c.id)||marked.has(c.sym)||marked.has(c.name)).length}
function pulseProblems(){const n=D.meta.notion||{},f=n.fallbackTables||[],q=n.quarantined||[],problems=[];if(f.length===6){const dates=f.map(x=>x.lastGoodFetchedAt).filter(Boolean).sort();problems.push(`研究数据未更新，沿用 ${shortTime(dates[0])} 的版本`)}else if(f.length)problems.push(`${f.length} 张研究表沿用上次版本`);if(q.length)problems.push(`${q.length} 行研究数据有误，已沿用上次版本或暂不显示`);const missing=quoteMissingCount();if(missing)problems.push(`${missing} 家行情暂缺，显示上次值`);return problems.slice(0,2)}
function todayChangeText(){const summary=OP?.changes||D.changes||{},c=summary.today||OP?.changesToday||summary.changesToday||D.meta.changesToday;if(!c||summary.mode==='unavailable'||c.firstRun||c.firstUpdate||c.mode==='first_update')return'今日变化：首次更新';const count=x=>Array.isArray(x)?x.length:Number.isFinite(x)?x:0;return`今日变化：财报 ${count(c.reports??c.financials)} · 财报日确认 ${count(c.confirmed??c.calendar??c.earningsConfirmed)} · 评分 ${count(c.scores)}`}
function renderReleaseStatus(){const box=$('#pulse');if(!box)return;const now=Date.now(),schedule=D.meta.schedule,late=scheduledDue(D.meta.generatedAt,now,schedule),failed=OP?.state==='failed'||!!(OP&&remoteVersion?.state==='failed'&&remoteVersion.dataSHA256===OP.dataSHA256),bad=late||failed,problems=pulseProblems(),state=bad?'bad':problems.length?'warn':'ok',generated=shortTime(OP?.generatedAt||D.meta.generatedAt),changed=!!(OP&&remoteVersion&&(remoteVersion.dataSHA256!==OP.dataSHA256||remoteVersion.sourceSHA!==OP.sourceSHA)),next=bad?nextScheduledRun(schedule?.cronUtc,now):schedule?.nextRunAt;
 const parts=[bad?`本次更新未完成，显示 ${generated} 的数据`:`行情更新于 ${generated}`];if(!bad&&problems.length)parts.push(...problems);else{if(next)parts.push('下次 '+shortTime(next));if(!bad)parts.push(todayChangeText())}box.className='pulse '+state;
 box.innerHTML=`<i class="dot ${state==='ok'?'':state}" aria-hidden="true"></i>${parts.map((x,i)=>`${i?'<span class="sep">·</span>':''}<span class="${bad?'msg-bad':i&&state==='warn'?'msg-warn':''}">${esc(x)}</span>`).join('')}<span class="sep">·</span><a href="#dataNotes">数据说明</a>${changed?'<span class="sep">·</span><span>有新数据</span><button class="reason-link" id="refreshSnapshot">刷新</button>':''}`;
 $('#refreshSnapshot')?.addEventListener('click',()=>location.reload());
}
async function checkVersion(){if(!OP||versionBusy||document.hidden||!/^https?:$/.test(location.protocol))return;versionBusy=true;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
  try{const response=await fetch('/version.json',{cache:'no-store',credentials:'same-origin',redirect:'error',signal:controller.signal});if(!response.ok||!(response.headers.get('content-type')||'').includes('json'))throw Error('version unavailable');const v=await response.json();if(!validVersion(v))throw Error('version invalid');remoteVersion=v;versionError=false}catch(e){versionError=true}finally{clearTimeout(timer);versionBusy=false;renderReleaseStatus()}
}
function sharedSources(){const fx=D.meta.fxProvenance||{};return`<details class="evidence-card" id="marketSources"><summary>指数、汇率与比值来源</summary><ul>${D.indices.map(x=>`<li>${esc(x.name)} · ${esc(x.asOf||'日期缺失')} · ${phaseText(x.phase)} · ${sourceAnchor(providerUrl(x.symbol,x.source,true),x.source||'来源未提供')}</li>`).join('')}${Object.entries(fx).map(([cur,x])=>`<li>${esc(cur)} 汇率 · ${esc(x.asOf||'日期缺失')} · ${sourceAnchor(providerUrl(cur==='EUR'?'EURUSD=X':cur+'=X',x.src,true),x.src||'来源未提供')}</li>`).join('')}<li>创业板 / 红利比值 · ${sourceAnchor(providerUrl('399006.SZ',D.ratio?.provenance?.cyb?.src,true),'创业板来源')} · ${sourceAnchor(providerUrl('000922.SS',D.ratio?.provenance?.hl?.src,true),'红利来源')} · 同步时刻未确认</li></ul><p>供应商页面与接口返回当前数据；本页日期和阶段标记决定使用口径，来源入口不构成历史快照证明。</p></details>`}
const TABLE_NAMES={industries:'行业',chokepoints:'卡点',companies:'公司',financials:'财报记录',daily:'每日要点',weekly:'每周主线'};
const CODE_TEXT={"notion_token_missing": "未设置 NOTION_TOKEN", "notion_unauthorized": "NOTION_TOKEN 无效或无权限（401）", "notion_forbidden": "NOTION_TOKEN 权限不足（403）", "notion_not_found": "{表}库 404：未共享给 connection 或已移动", "notion_rate_limited": "Notion 限流（429），重试 3 次仍失败", "notion_server_error": "Notion 服务器错误（{状态码}），重试 3 次仍失败", "notion_timeout": "读取超时或连接失败", "notion_bad_json": "Notion 返回的内容无法解析", "notion_cursor_loop": "分页游标重复，已停止读取", "notion_too_many_pages": "超过 50 页，已停止读取", "notion_body_too_large": "单次响应超过 8 MB，已停止读取", "notion_http_error": "Notion 请求失败（{状态码}）", "no_last_good": "读不到研究数据，也没有上次成功的版本", "notion_schema_changed": "Notion 列名被改：{列名}（missing）／Notion 列类型被改：{列名}（{原类型} → {新类型}）", "table_quality_low": "有误的行太多（{坏行}/{总行}）", "missing_required": "缺必填项：{列名}", "number_out_of_range": "{列名}超出 {最小}–{最大}", "number_not_integer": "{列名}应为整数", "invalid_enum": "{列名}的选项「{值}」不在约定范围内", "regex_mismatch": "{列名}格式不对：{值}", "relation_missing": "{列名}没有关联，或关联的行已停用", "relation_multiple": "{列名}只能关联 1 行", "duplicate_key": "与另一行重复：{key}（保留较早创建的一行）", "period_after_publish": "期末日晚于发布日", "publish_in_future": "发布日晚于今天", "text_long": "文字偏长：{n} 字（建议 ≤ {上限}）", "text_truncated": "文字超长，已截到 {上限} 字", "list_truncated": "条目过多，只保留前 {上限} 条", "relation_truncated": "关联过多，只保留前 {上限} 个", "banned_words": "含禁用词，相关文字不显示", "prediction_words": "含预测性用词「{词}」，改用自动生成句", "token_unknown_company": "财报日标记里的代号 {代号} 不存在或已停用，显示为「日期待定」", "cp_industry_mismatch": "所属卡点不属于该公司的行业，不挂卡点", "earnings_confirmed_without_source": "标了官方确认但没有 https 来源，按预估显示", "earnings_date_past": "下次财报日已过，待更新", "timezone_invalid": "时区无效：{值}，改用市场默认时区", "url_invalid": "链接不是 https，已忽略", "pct_out_of_range": "{列名}超出合理范围，已置空", "pct_suspicious": "{列名}数值异常大，照常显示", "pct_maybe_fraction": "{列名}可能写成了小数（{值}），照原值显示", "flash_date_future": "快讯日期晚于今天，按今天处理", "financial_duplicate": "同一期有多条财报记录，保留录入日较晚的一条", "daily_duplicate": "同一市场同一天有多条，用最近编辑的一条", "daily_future_date": "日期晚于该市场最近交易日，已忽略", "company_cap_exceeded": "公司超过 80 家，多出的不显示", "missing_reason": "缺研判理由", "missing_source": "缺来源链接", "missing_dates": "缺研判日期或有效至", "future_judgment_date": "研判日期晚于今天", "expired": "研判已过期（有效至 {日期}）", "validity_too_long": "有效期超过 14 天", "row_quarantined": "本行数据有误，显示上次成功读取的版本", "not_current_week": "不是本周的研判，显示上次结论", "no_weekly_row": "本周还没有主线研判", "legacy_data": "旧版数据，无研判信息", "banned_words_in_output": "页面里出现禁用词「{词}」（{位置}）", "quotes_coverage_low": "有行情的公司只有 {n}/{总数}（低于 70%）", "contract_invalid": "契约文件不合法：{原因}"};
function diagnosticText(x){const d=x.detail||{},values={'表':TABLE_NAMES[x.table]||x.table||'','时间':shortTime(x.lastGoodFetchedAt),'列名':x.field||d.property||d.field||'相关字段','状态码':d.status||d.statusCode||'未知','坏行':d.bad,'总行':d.total,'key':x.key,'值':d.value??'所填值','n':d.length??d.count,'上限':d.max??d.limit??d.recommended,'最小':d.min,'最大':d.max,'原类型':d.expected,'新类型':d.actual,'词':(d.words||[]).join('、'),'代号':(d.companies||[]).join('、'),'日期':d.validUntil};return(CODE_TEXT[x.code]||x.code||'数据状态未提供').replace(/\{([^}]+)\}/g,(_,k)=>values[k]??'未提供')}
function researchNotes(){const n=D.meta.notion,f=n?.fallbackTables||[],q=n?.quarantined||[],w=(n?.warnings||[]).slice(0,50),requests=typeof n?.requests==='object'?n.requests.total:n?.requests;return`<details id="dataNotes" class="evidence-card"><summary>数据说明</summary><p>${n?`研究数据：来自 Notion · 读取于 ${esc(shortTime(n.fetchedAt))} · <span class="num">${requests||0}</span> 次请求`:'研究数据：仓库文件'}</p>${f.length?`<ul>${f.map(x=>`<li>${esc(TABLE_NAMES[x.table]||x.table)}：${esc(diagnosticText(x))}；沿用 ${esc(shortTime(x.lastGoodFetchedAt))} 的版本</li>`).join('')}</ul>`:''}${q.length?`<div class="bl">隔离的行</div><ul>${q.map(x=>`<li>${esc(TABLE_NAMES[x.table]||x.table)} · ${esc(x.key||x.pageId)} · ${esc(diagnosticText(x))} · ${x.usedLastGood?'显示上次成功读取的版本':'暂不显示'}</li>`).join('')}</ul>`:''}${w.length?`<div class="bl">提醒${(n.warnings||[]).length>50?'（仅列前 50 条）':''}</div><ul>${w.map(x=>`<li>${esc(TABLE_NAMES[x.table]||x.table)} · ${esc(x.key||x.pageId||'')} · ${esc(x.field||'')} · ${esc(diagnosticText(x))}</li>`).join('')}</ul>`:''}<p>${sourceAnchor(OP?.runUrl,'发布记录')} · ${sourceAnchor(OP?.workflowUrl||REPO&&REPO+'/actions','更新历史')}</p></details><p class="disclaimer" id="disclaimer">研究内容由 AI 依据公开资料撰写，程序自动检查格式、日期与来源，未经人工审核；行情由定时任务更新。仅供研究参考，不构成投资建议。</p>`}
function renderFoot(){
 const gaps=CO.flatMap(c=>['pe','r60','ytd','dd52'].filter(k=>metricGap(c,k)).map(k=>`${c.name} ${k==='pe'?'PE':PL[k]}：${metricGap(c,k)}`)),partial=CO.filter(c=>c.financialPartial).map(c=>c.name+' '+c.period+'：部分披露，不参排');
 const estimated=CO.filter(c=>c.mcapEstimated&&fin(c.mcapUSD)),fxDates=[...new Set(estimated.map(c=>c.provenance?.valuation?.fx?.asOf||'日期未知'))],detail=[...gaps,...partial,estimated.length?`${estimated.length} 家美元市值使用跨日 FX 估算（FX 日期 ${fxDates.join('、')}），≈ 数值的原币市值见列表与详情`:''].filter(Boolean).map(x=>`<li>${esc(x)}</li>`).join('');
 $('#foot').innerHTML=`<div class="foot-grid"><div><div class="bl">${ICON.grid}数据口径</div><p>行情：Yahoo Finance（备用：腾讯财经），各市场最新完成日线；比值：腾讯财经指数月线。财务：按公司所列期别、币种与会计口径；单季中位数只计「有原文」的单季正式报告，半年累计、快报与扭亏不作普通增长信号。市值保留本币，美元折算用同日或最近汇率并标注“≈”。缺值留空，不填 0。</p></div><div><div class="bl">${ICON.target}信号规则</div><p>业绩（单季 · 有原文 · 利润可比）：高增 ≥ 50% · 增长 ≥ 10% · 平稳 &gt; −10% · 其余为下滑。<br>股价：走强 = 近20日 ≥ +5%；深度回调 = 距52周高点 ≤ −40%；回调 = 近20日 ≤ −10%；其余为震荡。缺值不参与均值与中位数。</p></div><div><div class="bl">${ICON.alert}说明</div><p>${statusTag('ai','AI 研判','AI 撰写，附理由、来源与有效期',true)} 主线、评分、卡点与快讯由 AI 撰写，附理由、来源与有效期；过期或缺项自动改标「待更新」。<br>${statusTag('auto','自动生成','按固定模板生成',true)} 由程序按固定模板，用行情、财报与评分数据生成。<br>${statusTag('conflict','数据冲突','AI 评分与数据档相差 ≥ 2 分',true)} AI 评分与数据档相差 ≥ 2 分时提示，不改分。<br>行情每个交易日 08:45 / 12:15 / 18:15（北京时间）自动更新；周一 06:50 切换周次。</p></div></div>
 ${sharedSources()}<details id="dataDetails"><summary>数据状态与缺项 · ${esc(dataStateLabel(D.meta.coverage))}</summary><p>缺值表示本次快照没有有效值；每项保留原始观察时间和来源。</p><ul>${detail}</ul></details>${researchNotes()}<div class="foot-b">投研雷达 · ALPHA RADAR · 行情更新于 ${esc(shortTime(D.meta.generatedAt))} · 快捷键：${isMac?'⌘K':'Ctrl K'} 搜索 · ←/→ 切换公司 · Esc 关闭</div>`;
 $('#sigLegend').innerHTML=`<span>业绩：<span class="sg p1">高增</span> ≥50% <span class="sg p2">增长</span> ≥10% <span class="sg p3">平稳</span> <span class="sg p4">下滑</span></span><span>股价：<span class="sg x1">走强</span> 近20日≥+5% <span class="sg x3">回调</span> ≤−10% <span class="sg x4">深度回调</span> 距高点≤−40% <span class="sg x2">震荡</span></span>`
}

/* ---------- reveal / scrollspy ---------- */
function onReveal(el){$$('#kpis [data-count]',el).forEach(countUp);$$('.ring .bar',el).forEach(b=>{b.style.strokeDashoffset=b.dataset.to});$$('.needle',el).forEach(n=>{n.style.transform=`rotate(${n.dataset.deg}deg)`})}
function initObservers(){
  if(!('IntersectionObserver' in window)){$$('.reveal').forEach(el=>{el.classList.add('in');onReveal(el)});return}
  const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');onReveal(e.target);io.unobserve(e.target)}}),{threshold:.06,rootMargin:'0px 0px -4% 0px'});
  $$('.reveal').forEach((el,i)=>{el.style.transitionDelay=(el.closest('.bento')?(Array.from(el.parentNode.children).indexOf(el)*90):0)+'ms';io.observe(el)});
  const spy=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)setNav(e.target.id)}),{rootMargin:'-35% 0px -60% 0px'});
  ['overview','radar','choke','leaders','calendar'].forEach(id=>spy.observe(document.getElementById(id)))}
function setNav(id){$$('#nav a').forEach(a=>a.classList.toggle('active',a.dataset.sec===id));const a=$(`#nav a[data-sec="${id}"]`),ind=$('#navInd');if(a&&ind&&a.offsetWidth){ind.style.left=a.offsetLeft+'px';ind.style.width=a.offsetWidth+'px'}}

/* ---------- init ---------- */
applyTheme();applyConv();renderTicker();renderHero();renderTop();renderRank();renderThermo();renderSoon();
seg($('#levelSeg'),[{v:'all',l:'全部 15'},{v:'hot',l:'重点追踪'},{v:'watch',l:'持续观察'},{v:'low',l:'低频跟踪'}].map(o=>o.v==='all'?{v:'all',l:`全部 ${IND.length}`}:{v:o.v,l:`${o.l} ${IND.filter(d=>levelOf(d.total).k===o.v).length}`}),'all',v=>{S.level=v;renderIndList()});
renderIndList();renderIndDetail();
seg($('#cpSeg'),KEY_IND.map(n=>({v:n,l:n})),S.cpInd,v=>{S.cpInd=v;renderFlow()});renderFlow();
seg($('#viewSeg'),[{v:'map',l:'热力图'},{v:'table',l:'列表'}],'map',v=>{S.view=v;renderLeaders()});
seg($('#metricSeg'),METRICS.map(m=>({v:m.k,l:m.k==='dd52'?'距高点':m.l})),S.metric,v=>{S.metric=v;if(COLS.some(c=>c.k===v))S.sort={k:v,d:v==='dd52'?1:-1};renderLeaders()});
seg($('#indSeg'),[{v:'all',l:'全部行业'}].concat(KEY_IND.map(n=>({v:n,l:n}))),'all',v=>{S.indF=v;renderLeaders()});
seg($('#mktSeg'),['all','A股','港股','美股','其他'].map(v=>({v,l:v==='all'?'全部市场':v})),'all',v=>{S.mktF=v;renderLeaders()});
renderLeaders();renderCal();renderFoot();renderReleaseStatus();checkVersion();initObservers();setNav('overview');
setInterval(()=>{renderReleaseStatus();checkVersion()},120000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkVersion()});
let rt=0;addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(()=>{$$('.seg').forEach(moveThumb);if(S.view==='map')renderMap();if(S.drawerType==='company')drawChart(byId[S.drawer]);const a=$('#nav a.active');if(a)setNav(a.dataset.sec)},120)});
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(()=>{$$('.seg').forEach(moveThumb);const a=$('#nav a.active');if(a)setNav(a.dataset.sec)});
})();
