/* Local Ego Lite module. Only content links and the comment panel are opened. */
const HOSTS = {
  em: ['guba.eastmoney.com'], xq: ['xueqiu.com', 'www.xueqiu.com'],
  ths: ['t.10jqka.com.cn', 'tgb.10jqka.com.cn', 'bbs.10jqka.com.cn', 'stock.10jqka.com.cn'],
  dy: ['www.douyin.com', 'douyin.com'],
  xhs: ['www.xiaohongshu.com', 'xiaohongshu.com'],
};
const PLATFORMS = Object.keys(HOSTS);
const LIMIT_PER_TRACK = 2;
const MAX_COMMENTS = 20;

function safeUrl(platform, address) {
  try {
    const url = new URL(address);
    return url.protocol === 'https:' && !url.username && !url.password && !url.port &&
      HOSTS[platform].includes(url.hostname) ? url : null;
  } catch {
    return null;
  }
}

// This complete function is evaluated inside the visible web page. The same
// export can be run on saved HTML without Ego, credentials or network access.
export function extractComments({platform, date, now = Date.now(), track = 'community'}) {
  const profiles = {
    em: ['.reply_item,.reply-item,.replyListItem', '.reply_text,.reply-content,.reply_content,.shortntxt,.reply_title_span',
      'time,.reply_time,.reply-time,.publish_time,.pubtime', '.reply_like,.like_count,.likemodule'],
    xq: ['.comment__item,.comment-item', '.comment__item__text,.comment__text,.comment-content',
      'time,.comment__item__time,.comment__time,.comment__item__info .time', '.comment__item__like,.like-count'],
    ths: ['.comment-item,.comment_item,.reply-item,.cmt-item', '.comment-content,.reply-content,.cmt-text,.comment_text',
      'time,.comment-time,.cmt-time,.reply-time', '.like-count,.praise-count'],
    dy: ['[data-e2e="comment-level-1"],[data-e2e="comment-level-2"],[data-e2e="comment-item"]',
      '[data-e2e="comment-content"],.comment-content,[class*="commentText"]',
      'time,[data-e2e="comment-time"],.comment-time,[class*="commentTime"]',
      '[data-e2e="comment-like-count"],[data-e2e="comment-like"]'],
    xhs: ['.comment-item,.sub-comment-item', '.content .note-text,.content .content-text,.comment-content',
      'time,.info .date,.date,.comment-time', '.like-wrapper .count,.like-count'],
  };
  const visible = e => !!(e && e.getClientRects().length && !e.closest('[hidden],[aria-hidden="true"]') &&
    getComputedStyle(e).visibility !== 'hidden');
  const challenge = Array.from(document.querySelectorAll(
    '[role="dialog"],.login-container,.login-mask,[class*="captcha"],[id*="captcha"],iframe[title],h1,title'
  )).filter(e => e.tagName === 'TITLE' || visible(e)).map(e =>
    (e.innerText || e.textContent || '') + ' ' + (e.getAttribute('title') || '')).join('\n');
  const gate = /验证码|安全验证|人机验证|滑块验证|完成验证后|请验证身份/.test(challenge) ? 'captcha_required' :
    /扫码登录|登录后查看|登录后继续|手机号登录|登录后可查看|请先登录/.test(challenge) ? 'login_required' : null;
  if (gate) return {status:gate, comments:[]};
  if (!profiles[platform]) return {status:'unavailable', comments:[]};
  const [rowSelector, bodySelector, timeSelector, likesSelector] = profiles[platform];
  const observed = typeof now === 'number' ? now : Date.parse(now);
  const inChina = ms => new Date(ms + 8 * 3600000).toISOString().slice(0, 16);
  const dateToday = inChina(observed).slice(0,10);
  const start = Date.parse(date + (['dy','xhs'].includes(platform) ? 'T18:00:00+08:00' : 'T15:00:00+08:00'));
  const end = Math.min(observed, Date.parse(date + 'T20:15:59.999+08:00'));
  // Relative labels have rounding uncertainty. Accept only intervals entirely
  // within the requested research window, even near midnight or the cutoff.
  function moment(input) {
    const s = String(input || '').trim().replace(/^(?:发布时间|发布于|发表于|评论于|回复于)[\s:：]*/u,'');
    let lo, hi;
    if (/^\d{10}(?:\d{3})?$/.test(s)) {
      lo = hi = Number(s) * (s.length === 10 ? 1000 : 1);
    } else if (/^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:?\d\d)$/i.test(s)) {
      lo = hi = Date.parse(s);
    } else {
      let match = s.match(/^(?:(\d{4})[-/.年])?(\d{1,2})[-/.月](\d{1,2})日?[T\s]+(\d{1,2}):(\d\d)(?::(\d\d))?/);
      if (match) {
        const [, year, month, day, h, m, sec = '00'] = match;
        const y = year || dateToday.slice(0,4);
        const literal = [y,month.padStart(2,'0'),day.padStart(2,'0')].join('-');
        lo = hi = Date.parse(literal + 'T' + h.padStart(2,'0') + ':' + m + ':' + sec + '+08:00');
        if (!Number.isFinite(lo) || inChina(lo).slice(0,10) !== literal) return null;
      } else if ((match = s.match(/^(今天|今日|昨天)\s*(\d{1,2}):(\d\d)/))) {
        const d = inChina(observed - (match[1] === '昨天' ? 86400000 : 0)).slice(0,10);
        lo = hi = Date.parse(d+'T'+match[2].padStart(2,'0')+':'+match[3]+':00+08:00');
      } else if ((match = s.match(/^(\d+)\s*(秒|分钟|小时)前/))) {
        const unit = {秒:1000, 分钟:60000, 小时:3600000}[match[2]];
        hi = observed - Number(match[1])*unit;
        lo = hi-unit+1;
      } else if (/^刚刚(?:\s|$)/.test(s)) {
        hi = observed; lo = hi - 60000 + 1;
      }
    }
    return Number.isFinite(lo) && Number.isFinite(hi) ? {lo,hi} : null;
  }
  const comments = [], seen = new Set();
  const counts = {rows:0, dated:0, inWindow:0};
  for (const row of document.querySelectorAll(rowSelector)) {
    if (!visible(row)) continue;
    counts.rows++;
    const own = selector => Array.from(row.querySelectorAll(selector)).find(
      el => visible(el) && el.closest(rowSelector) === row);
    const content = own(bodySelector);
    const clock = own(timeSelector);
    if (!content || !clock) continue;
    const rawTime = [clock.getAttribute('datetime'), clock.getAttribute('data-time'),
      clock.getAttribute('title'), clock.innerText].filter(Boolean);
    const time = rawTime.map(moment).find(Boolean);
    if (!time) continue;
    counts.dated++;
    if (!(time.lo >= start && time.hi <= end)) continue;
    counts.inWindow++;
    const stamp = inChina(time.hi);
    // Isolate the comment body. A nested author, handle or profile element
    // is never part of the returned observation.
    const clone = content.cloneNode(true);
    clone.querySelectorAll('script,style,time,.author,.username,.nickname,.item_reuser,[data-e2e="comment-user-name"]')
      .forEach(node => node.remove());
    const text = (clone.textContent || '').trim().replace(/[@＠][^\s，。！？、；）)]+/gu, '匿名用户');
    if (!text || text.length > 600) continue;
    const key = stamp + '\n' + text;
    if (seen.has(key)) continue;
    seen.add(key);
    const item = {text, date:stamp.slice(0,10), time:stamp.slice(11,16), track};
    const like = own(likesSelector)?.innerText.trim().replaceAll(',','').match(/^(\d+(?:\.\d+)?)\s*(万)?(?:\s*赞)?$/);
    if (like) item.likes = Math.round(Number(like[1]) * (like[2] ? 10000 : 1));
    comments.push(item);
    if (comments.length >= 20) break;
  }
  return {status:comments.length ? 'ok' : 'empty', comments, counts, truncated:comments.length >= 20};
}

// A new comment on an old video is not evidence about tonight's review.
// Read the visible work's own publication date, outside all comment nodes.
export function datedReview({platform,date,now,readyOnly=false}) {
  const clock = typeof now === 'number' ? now : Date.parse(now);
  const chinaDate = ms => new Date(ms+8*3600000).toISOString().slice(0,10);
  const title = platform === 'dy' ? '[data-e2e="video-desc"],[data-e2e="detail-video-desc"],.video-info-detail h1' :
    '#noteContainer #detail-title,#noteContainer .note-content .desc,.note-detail-mask .note-content';
  const dates = platform === 'dy' ? '[data-e2e="video-publish-time"],[data-e2e="video-create-time"],.video-info-detail .time,.video-info-detail time' :
    '#noteContainer .note-content .date,.note-detail-mask .note-content .date,.note-content time';
  const shown = s => Array.from(document.querySelectorAll(s)).filter(e => e.getClientRects().length &&
    !e.closest('.comment-item,[data-e2e="comment-level-1"],[aria-hidden="true"],[hidden]'));
  const subject = shown(title).map(e=>e.innerText).join(' ');
  const clocks = shown(dates);
  if (readyOnly) return Boolean(subject.trim() && clocks.length);
  if (!/复盘|收盘|收评|盘后|大盘|A股|涨停|连板|龙虎榜/iu.test(subject)) return false;
  for (const el of clocks) {
    for (const value of [el.getAttribute('datetime'),el.getAttribute('title'),el.innerText]) {
      if (!value) continue;
      const s = value.trim().replace(/^(?:编辑于|发布于|发布时间[：:]?)\s*/, '');
      let key;
      if (/^今天|^今日|^刚刚/.test(s)) key=chinaDate(clock);
      else if (/^昨天/.test(s)) key=chinaDate(clock-86400000);
      else {
        const relative=s.match(/^(\d+)\s*(分钟|小时)前/);
        const absolute=s.match(/^(?:(\d{4})[-/.年])?(\d{1,2})[-/.月](\d{1,2})(?:日|T|\s|$)/);
        if(relative) {
          const unit=relative[2]==='小时'?3600000:60000;
          const hi=clock-Number(relative[1])*unit;
          if(chinaDate(hi)===chinaDate(hi-unit+1))key=chinaDate(hi);
        } else if(absolute) {
          const [,y,m,d]=absolute;
          key=[y||chinaDate(clock).slice(0,4),m.padStart(2,'0'),d.padStart(2,'0')].join('-');
        }
      }
      if(key===date)return true;
    }
  }
  return false;
}

export function approvedHotAuthor({platform,authors}) {
  const selector = {
    dy: '[data-e2e="video-author-name"] a,a[data-e2e="video-author-name"],.video-info-detail .author a,.video-info-detail [class*="author"] a',
    xhs: '#noteContainer .author-container a,.note-detail-mask .author-wrapper a,#noteContainer .author-wrapper a',
  }[platform];
  if (!selector || !authors.length) return false;
  const site = host => host.replace(/^www\./,'');
  const path = url => url.pathname.replace(/\/$/,'');
  const allowed = new Set(authors.map(address => path(new URL(address))));
  return [...document.querySelectorAll(selector)].some(link => {
    if (!link.getClientRects().length || link.closest('[hidden],[aria-hidden="true"],.comment-item')) return false;
    const author = new URL(link.href,location.href);
    return author.protocol==='https:' && !author.username && !author.password && !author.port &&
      site(author.hostname)===site(location.hostname) && allowed.has(path(author));
  });
}

// Return only public work paths. For signed links the browser itself follows
// the displayed anchor. Query strings, authors, device and session state
// never leave the page.
export function discoverWorks({platform, track}) {
  const pattern = {
    em:/^\/news,[\w-]+,\d+\.html$/i, xq:/^\/\d+\/\d+\/?$/,
    ths:/^\/(?:pid[_/]\d+|[^/]+\/post\/\d+|(?:discussion|article)\/\d+)(?:\.s?html?)?\/?$/,
    dy:/^\/video\/\d+\/?$/, xhs:/^\/(?:explore|discovery\/item|search_result)\/[a-z\d]{16,32}\/?$/i,
  }[platform];
  const containers = {
    dy:track === 'kol' ? '[data-e2e="user-post-list"],[data-e2e="user-post-list-item"]' :
      '[data-e2e="search-result"],[data-e2e*="search-card"],[class*="search-result"]',
    xhs:track === 'kol' ? '#userPostedFeeds,.user-page .feeds-container,.feeds-tab-container .note-item' :
      '.search-page,.search-layout,.search-result-container,.feeds-container .note-item',
  };
  const financial = /A\s*股|复盘|收评|收盘|大盘|指数|龙虎榜|涨停|股市|板块|题材|连板|盘后|情绪周期/iu;
  const found = new Map();
  for (const anchor of document.querySelectorAll('a[href]')) {
    if (!anchor.getClientRects().length || anchor.closest('[hidden],.advertisement,[data-ad]')) continue;
    const url = new URL(anchor.href, location.href);
    const sameXueqiu = platform === 'xq' && ['xueqiu.com','www.xueqiu.com'].includes(location.hostname)
      && ['xueqiu.com','www.xueqiu.com'].includes(url.hostname);
    if (url.protocol !== 'https:' || url.username || url.password || url.port ||
        (!sameXueqiu && url.origin !== location.origin) || !pattern.test(url.pathname)) continue;
    let likes = null;
    if (containers[platform]) {
      if (!anchor.closest(containers[platform])) continue;
      const card = anchor.closest('.note-item,li,article,[data-e2e*="card"],[data-e2e="user-post-list-item"]')
        || anchor.parentElement;
      const title = [card?.innerText, anchor.title, anchor.querySelector('img')?.alt].join(' ');
      if (!financial.test(title)) continue;
      const text = card?.querySelector('.like-wrapper .count,[data-e2e*="like-count"],.like-count')?.textContent;
      const count = text?.trim().replaceAll(',','').match(/^(\d+(?:\.\d+)?)\s*(万)?$/);
      if (count) likes = Number(count[1]) * (count[2] ? 10000 : 1);
    }
    found.set(url.pathname, {path:url.pathname, likes});
    if (found.size >= 40) break;
  }
  const works = Array.from(found.values());
  // Ordered result links are retained for the platform's popularity search.
  // Where displayed likes exist, prefer the most discussed visible works.
  if (track === 'hot') works.sort((a,b) => (b.likes ?? -1)-(a.likes ?? -1));
  // The first result can be a pinned older work. Inspect a bounded shortlist
  // until the collector has found two dated reviews, or the time budget ends.
  return works.slice(0,6).map(work=>work.path);
}

function sources(platform, spec) {
  if (platform === 'dy' || platform === 'xhs') {
    const creators = (spec.kol || spec.urls || []).filter(address => {
      const url = safeUrl(platform,address);
      return url && (platform === 'dy' ? /^\/user\/[\w-]+\/?$/ : /^\/user\/profile\/[\w-]+\/?$/).test(url.pathname);
    });
    const tags = (spec.tags || [spec.tag || 'A股复盘']).slice(0,2);
    const hot = tags.map(t => {
      const q = encodeURIComponent('#'+String(t).replace(/^#/,''));
      return platform === 'dy' ? 'https://www.douyin.com/search/'+q+'?type=video&sort_type=1' :
        'https://www.xiaohongshu.com/search_result?keyword='+q+'&type=51&sort=popularity_descending';
    });
    return {kol:creators, hot};
  }
  return {community:(spec.seeds || spec.urls || []).filter(address=>safeUrl(platform,address))};
}

function controlError(error) {
  return /(?:user.control|user.takeover|space.inactive|space.unassigned|not.owned|delegated.to.user)/i
    .test(String(error?.code || '')+' '+String(error?.message || ''));
}

function timedOut(error) {
  return /timeout|timed.out|unresponsive/i.test(String(error?.code)+' '+String(error?.message));
}

function checkDestination(platform, address) {
  const url = new URL(address);
  if ((platform === 'dy' && url.hostname === 'sso.douyin.com') ||
      (platform === 'em' && url.hostname === 'passport2.eastmoney.com') ||
      (platform === 'ths' && url.hostname === 'passport.10jqka.com.cn') ||
      (platform === 'xhs' && ['rednote.com','www.rednote.com'].includes(url.hostname) && url.pathname === '/login')) {
    throw Error('login_required');
  }
  if (!safeUrl(platform,address)) throw Error('off_platform');
  if (/^\/(?:passport\/login|login|signin)(?:\/|$)/i.test(url.pathname)) throw Error('login_required');
}

async function readPlatform(task, page, platform, spec, date) {
  const comments = [], seen = new Set(), tracks = [], trackStatus = {}, trackDetails = {};
  const requested = sources(platform,spec);
  let deadline, detail, truncated=false;
  const budget = max => {
    const left = deadline-Date.now();
    if (left < 1) throw Error('timeout');
    return Math.min(left,max);
  };
  let active = page;
  async function go(url, retry=true, navigationTimeout=8500) {
    if (!safeUrl(platform,url)) throw Error('off_platform');
    detail.stage='seed_navigation';
    try {
      await active.goto(url,{timeout:budget(navigationTimeout)});
    } catch (error) {
      if (!retry || controlError(error) || !timedOut(error) || deadline-Date.now()<4000) throw error;
      detail.navigationRetries++;
      await active.goto(url,{timeout:budget(14000)});
    }
    checkDestination(platform,await active.url());
    detail.stage='seed_loaded';
  }
  async function sample(track, include=true) {
    const payload = await active.evaluate(extractComments,{platform,date,track,now:Date.now()});
    if (['login_required','captcha_required'].includes(payload.status)) throw Error(payload.status);
    if (!include) return 0;
    detail.stage='comment_sample';
    for (const name of ['rows','dated','inWindow']) detail[name] = Math.max(detail[name], payload.counts?.[name] ?? 0);
    if(payload.truncated) truncated=true;
    for (const c of payload.comments) {
      const key = c.date+'|'+c.time+'|'+c.text;
      if (!seen.has(key)) { seen.add(key); comments.push(c); }
    }
    return payload.comments.length;
  }
  async function readWork(track) {
    const panel = platform === 'dy' ? '[data-e2e="video-player-comment"]' : '[aria-label="展开评论"]';
    if (track !== 'community') {
      await sample(track,false);
      detail.stage='work_date';
      try {
        await active.waitForFunction(datedReview,{platform,date,now:Date.now(),readyOnly:true},{timeout:budget(3500)});
      } catch (error) { if (controlError(error) || !timedOut(error)) throw error; }
      await sample(track,false);
      if (!await active.evaluate(datedReview,{platform,date,now:Date.now()})) return 0;
      if (track === 'hot') {
        detail.stage='hot_author';
        const authors = (spec.kol || []).concat(spec.hot_kol || []);
        if (!await active.evaluate(approvedHotAuthor,{platform,authors})) return 0;
      }
    }
    let count = await sample(track);
    if (!count) {
      const open = await active.evaluate(sel => {
        const items = Array.from(document.querySelectorAll(sel)).filter(e=>e.getClientRects().length);
        return items.length === 1 && !document.querySelector(
          '[data-e2e="comment-level-1"],.comment-item,.reply_item,.comment__item');
      },panel);
      if (open) await active.click(panel,{label:'查看作品评论',timeout:budget(2500)});
      try {
        await active.waitForFunction(()=>Boolean(document.querySelector(
          '.reply_item,.reply-item,.comment__item,.comment-item,.cmt-item,[data-e2e="comment-level-1"],[role="dialog"]'
        )),undefined,{timeout:budget(1800)});
      } catch (err) { if (controlError(err)) throw err; }
      count = await sample(track);
    }
    return count;
  }
  for (const [track, urls] of Object.entries(requested)) {
    let matched = 0, worksRead = 0, failed = false, expired = false;
    if (!urls.length) { trackStatus[track]='unconfigured'; continue; }
    deadline=Date.now()+(track === 'community' ? 36000 : 26000);
    detail=trackDetails[track]={stage:'configured', navigationRetries:0, links:0, works:0, rows:0, dated:0, inWindow:0};
    if(urls.length>3) truncated=true;
    const seeds = urls.slice(0,3);
    for (const [seedIndex, seed] of seeds.entries()) {
      try {
        active = page;
        // Give the next approved seed a chance before retrying a dead one.
        const finalSeed = seedIndex === seeds.length - 1;
        await go(seed, finalSeed, track === 'community' && finalSeed ? 20000 : 8500);
        if (track === 'community') {
          const direct = await readWork(track);
          if (direct) { matched+=direct; continue; }
        } else {
          // Check blocking UI without treating any feed-level commentary as a sample.
          await sample(track,false);
        }
        let links = await active.evaluate(discoverWorks,{platform,track});
        if (!links.length) {
          try {
            await active.waitForFunction(()=>Boolean(document.querySelector(
              '.note-item a[href],a[href*="/video/"],a[href*="/news,"],.timeline__item a[href],a[href*="pid_"]'
            )),undefined,{timeout:budget(1500)});
          } catch (err) { if (controlError(err)) throw err; }
          links = await active.evaluate(discoverWorks,{platform,track});
        }
        detail.links=Math.max(detail.links, links.length);
        if(links.length>=6)truncated=true;
        for (const [index,path] of links.entries()) {
          if (worksRead>=LIMIT_PER_TRACK || Date.now()>=deadline) { truncated=true; break; }
          let preserve=false;
          try {
            if (index) { active = page; await go(seed, false); }
            // Follow the displayed, allowlisted work link so site navigation stays inside Ego.
            detail.stage='work_navigation';
            const receipt = await active.click('loc=css:a[href*="'+path+'"] >> nth=0',{
              label:'打开复盘讨论',timeout:budget(2800)});
            if (receipt?.popups?.length) active=task.page(receipt.popups[0].label);
            checkDestination(platform,await active.url());
            const id = path.split('/').filter(Boolean).pop();
            await active.waitForFunction(({path,id}) => location.pathname === path ||
              location.pathname.endsWith('/'+id) || new URLSearchParams(location.search).get('modal_id') === id,
              {path,id},{timeout:budget(3200)});
            checkDestination(platform,await active.url());
            detail.works++;
            const found = await readWork(track);
            matched += found;
            if (found) worksRead++;
          } catch(err) {
            preserve=controlError(err)||['login_required','captcha_required'].includes(err.message);
            if (preserve) throw err;
            failed=true;
            if (timedOut(err)) expired=true;
          } finally {
            if (active !== page && !preserve) await active.close();
          }
        }
      } catch(err) {
        if (controlError(err)) throw err;
        if (['login_required','captcha_required'].includes(err.message)) {
          trackStatus[track] = err.message;
          if (matched) tracks.push(track);
          return {status:err.message,tracks,trackStatus,trackDetails,comments,truncated:true};
        }
        failed = true;
        if (timedOut(err)) expired=true;
      }
      if (Date.now() >= deadline) break;
      if (worksRead >= LIMIT_PER_TRACK && seed !== urls.at(-1)) { truncated=true; break; }
    }
    if (matched) tracks.push(track);
    if(failed||Date.now()>=deadline)truncated=true;
    trackStatus[track] = matched ? 'ok' : expired||Date.now()>=deadline ? 'timeout' : failed ? 'unavailable' : 'empty';
  }
  const values = Object.values(trackStatus);
  let status = 'empty';
  if (tracks.length === Object.keys(requested).length) status = 'ok';
  else if (tracks.length) status = 'partial';
  else if (values.includes('timeout')) status = 'timeout';
  else if (values.includes('unavailable')) status = 'unavailable';
  return {status,tracks,trackStatus,trackDetails,
    truncated:truncated||comments.length>MAX_COMMENTS*4,comments:comments.slice(0,MAX_COMMENTS*4)};
}

export async function readPlatforms(config) {
  if (!/^\d{4}-\d\d-\d\d$/.test(config.date)) throw Error('invalid_date');
  const result = Object.fromEntries(PLATFORMS.map(p=>[p,{status:'unavailable',tracks:[],comments:[]}]));
  const spaceName = '短线复盘只读采集 '+config.date;
  const existing = (await listTaskSpaces()).find(s=>s.name===spaceName);
  // A scheduled run never claims tabs left with an operator.
  if (existing) {
    for (const row of Object.values(result)) row.status='user_control';
    return result;
  }
  const task = await taskSpace(spaceName);
  const page = task.page('p1');
  for (const platform of PLATFORMS) {
    try {
      const row = await readPlatform(task,page,platform,config.platforms?.[platform] || {},config.date);
      result[platform] = row;
      if (['login_required','captcha_required'].includes(row.status)) {
        await task.handOff();
        return result;
      }
    } catch(err) {
      if (controlError(err)) {
        result[platform].status='user_control';
        return result;
      }
    }
  }
  await task.finish({keep:[]});
  return result;
}

export const readSentiment = readPlatforms;
