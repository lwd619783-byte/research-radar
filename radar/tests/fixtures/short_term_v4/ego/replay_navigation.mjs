import assert from 'node:assert/strict';
import {test} from 'node:test';
import {runInNewContext} from 'node:vm';
import {approvedHotAuthor, discoverWorks, datedReview, extractComments, readPlatforms}
  from '../../../../tools/short_term_collector/ego_reader.mjs';

const date = '2026-11-24';
const xhsWorks = ['/explore/1234567890abcdef','/explore/abcdef1234567890'];
const platforms = {
  em: {seeds: ['https://guba.eastmoney.com/list,zssh000001.html']},
  xq: {seeds: ['https://xueqiu.com/S/SH000001']},
  ths: {seeds: ['https://t.10jqka.com.cn/']},
  dy: {kol: ['https://www.douyin.com/user/offline'], tags: ['A股复盘']},
  xhs: {kol: ['https://www.xiaohongshu.com/user/profile/offline'], tags: ['A股复盘']},
};

class FakePage {
  constructor({fail, challenge, clock, latency = () => 0, forumWork = null,
    delayedForum = false, delayedHot = false, delayedCommentPlatform = null, stalledLoad = false,
    xhsReloadDelay = null}) {
    this.fail = fail;
    this.challenge = challenge;
    this.clock = clock;
    this.latency = latency;
    this.forumWork = forumWork;
    this.forumReady = !delayedForum;
    this.delayedHot = delayedHot;
    this.delayedCommentPlatform = delayedCommentPlatform;
    this.commentsReady = false;
    this.stalledLoad = stalledLoad;
    this.hotReady = !delayedHot;
    this.xhsReloadDelay = xhsReloadDelay;
    this.xhsReloadReady = false;
    this.opened = [];
    this.address = 'about:blank';
    this.navigations = new Map();
  }

  async goto(address, {timeout,waitUntil}) {
    const calls = this.navigations.get(address) || [];
    this.navigations.set(address, calls);
    calls.push(timeout);
    const duration = this.latency(address);
    if (this.fail(address, calls.length) || duration > timeout) {
      this.clock.value += timeout;
      throw Object.assign(new Error('Navigation timed out'), {code: 'EGO_NAVIGATION_TIMEOUT'});
    }
    this.clock.value += duration;
    this.address = address;
    if (this.stalledLoad && waitUntil !== 'commit') {
      this.clock.value += timeout-duration;
      throw Object.assign(new Error('Navigation timed out after document commit'), {
        code: 'EGO_NAVIGATION_TIMEOUT', committed: true,
      });
    }
  }

  async url() { return this.address; }

  async evaluate(fn, args) {
    if (fn === extractComments) {
      if (this.challenge?.platform === args.platform) {
        return {status: this.challenge.status, comments: []};
      }
      if (args.platform === 'em' && this.forumWork && !this.address.endsWith(this.forumWork)) {
        return {status: 'ok', comments: []};
      }
      if (args.platform === this.delayedCommentPlatform && !this.commentsReady) {
        return {status: 'ok', comments: []};
      }
      return {status: 'ok', counts: {rows: 1, dated: 1, inWindow: 1},
        comments: [{text: '离线复盘评论 ' + args.track, track: args.track, date, time: '19:20'}]};
    }
    if (fn === discoverWorks) {
      if (args.platform === 'xhs' && args.track === 'hot' && this.xhsReloadDelay !== null) {
        if (!args.targetPath) return xhsWorks;
        if (args.targetPath === xhsWorks[1]) return this.xhsReloadReady ? 2 : -1;
        return 0;
      }
      if (args.targetPath) return 0;
      if (args.platform === 'em' && this.forumWork) return this.forumReady ? [this.forumWork] : [];
      if (args.platform === 'xq' && this.delayedCommentPlatform === 'xq') return ['/123456/789012'];
      if (args.platform === 'dy' && args.track === 'hot' && !this.hotReady) return [];
      return args.platform === 'dy' ? ['/video/123456'] : [xhsWorks[0]];
    }
    if (fn === datedReview) return this.xhsReloadDelay === null || !this.address.endsWith(xhsWorks[0]);
    if (fn === approvedHotAuthor) return args.authors.length > 0;
    if ((this.forumWork || this.delayedCommentPlatform) && args === '[aria-label="展开评论"]') return false;
    assert.fail('Unexpected evaluation in navigation replay');
  }

  async click(selector) {
    const path = selector.match(/a\[href\*="([^"]+)"\]/)?.[1];
    assert.ok(path, 'Only the selected synthetic work may be opened');
    if (this.xhsReloadDelay !== null && path === xhsWorks[1]) {
      assert.ok(this.xhsReloadReady);
      assert.ok(selector.endsWith('nth=2'));
    }
    this.opened.push(path);
    this.address = new URL(path, this.address).href;
    return {};
  }

  async waitForFunction(fn,args,opts) {
    if (fn === discoverWorks && args.targetPath === xhsWorks[1] && this.xhsReloadDelay !== null) {
      assert.equal(args.readyOnly,true);
      assert.ok(opts.timeout <= 6500);
      if (this.xhsReloadDelay > opts.timeout) {
        this.clock.value += opts.timeout;
        throw Error('Matching work link timed out');
      }
      this.clock.value += this.xhsReloadDelay;
      this.xhsReloadReady = true;
    }
    if (!this.forumReady && fn === discoverWorks && args.platform === 'em') {
      assert.equal(args.readyOnly,true);
      assert.ok(opts.timeout >= 17000 && opts.timeout <= 22000);
      this.clock.value += 17000;
      this.forumReady = true;
    }
    if (this.delayedHot && fn === discoverWorks && args.platform === 'dy' && args.track === 'hot') {
      assert.equal(args.readyOnly,true);
      assert.ok(opts.timeout >= 4500);
      this.clock.value += 4500;
      this.hotReady = true;
    }
    const delayedWork = this.delayedCommentPlatform === 'xq' ? '/123456/789012' : this.forumWork;
    if (this.delayedCommentPlatform && args === undefined && this.address.endsWith(delayedWork)) {
      assert.ok(opts.timeout >= 4500);
      this.clock.value += 4500;
      this.commentsReady = true;
    }
    return true;
  }
}

async function replay(options) {
  const clock = {value: Date.parse(date + 'T20:30:00+08:00')};
  const page = new FakePage({...options, clock});
  const task = {
    handoffs: 0, finishes: 0,
    page(label) { assert.equal(label, 'p1'); return page; },
    async handOff() { this.handoffs++; },
    async finish(args) { assert.deepEqual(args, {keep: []}); this.finishes++; },
  };
  const originals = {clock: Date.now, spaces: globalThis.listTaskSpaces, task: globalThis.taskSpace, fetch: globalThis.fetch};
  try {
    Date.now = () => clock.value;
    globalThis.listTaskSpaces = async () => [];
    globalThis.taskSpace = async () => task;
    globalThis.fetch = async () => assert.fail('Offline navigation replay attempted a network request');
    const result = await readPlatforms({date, platforms});
    return {result, page, task};
  } finally {
    Date.now = originals.clock;
    globalThis.listTaskSpaces = originals.spaces;
    globalThis.taskSpace = originals.task;
    globalThis.fetch = originals.fetch;
  }
}

test('all seven tracks retry the same seed with bounded time and survive an earlier platform timeout', async () => {
  const {result, page, task} = await replay({
    fail: (address, attempt) => attempt === 1 || address === platforms.em.seeds[0],
  });
  assert.equal(page.navigations.size, 7);
  const community = new Set([...platforms.em.seeds, ...platforms.xq.seeds, ...platforms.ths.seeds]);
  for (const [seed, calls] of page.navigations) assert.deepEqual(calls, [community.has(seed) ? 20000 : 8500, 14000], seed);
  assert.equal(result.em.status, 'timeout');
  assert.equal(result.em.trackDetails.community.stage, 'seed_navigation');
  for (const [platform, report] of Object.entries(result)) {
    for (const detail of Object.values(report.trackDetails)) assert.equal(detail.navigationRetries, 1);
    if (platform !== 'em') {
      assert.equal(report.status, 'ok', platform);
      assert.ok(report.comments.length > 0, platform);
    }
  }
  assert.equal(task.handoffs, 0);
  assert.equal(task.finishes, 1);
});

test('a slow community entrance can finish one navigation and reach comments', async () => {
  const seed = platforms.em.seeds[0];
  const {result, page} = await replay({fail: () => false, latency: address => address === seed ? 17500 : 0});
  assert.deepEqual(page.navigations.get(seed), [20000]);
  assert.equal(result.em.status, 'ok');
  assert.equal(result.em.trackDetails.community.navigationRetries, 0);
  assert.equal(result.em.trackDetails.community.inWindow, 1);
});

test('a social search waits for matching work cards within its track deadline', async () => {
  const {result} = await replay({fail: () => false, delayedHot:true});
  assert.equal(result.dy.trackStatus.hot,'ok');
  assert.equal(result.dy.trackDetails.hot.links,1);
  assert.ok(result.dy.comments.some(comment=>comment.track === 'hot'));
});

test('a reloaded XHS search waits for the previously selected card and uses its visible link', async () => {
  const {result, page} = await replay({fail: () => false, xhsReloadDelay:4300});
  const hot = result.xhs.trackDetails.hot;
  assert.equal(hot.works,2);
  assert.equal(hot.workDateRejected,1);
  assert.equal(hot.inWindow,1);
  assert.equal(hot.workLinkTimeouts,0);
  assert.ok(page.opened.includes(xhsWorks[1]));
});

test('a missing XHS card is never opened and retains the previous work rejection', async () => {
  const {result, page} = await replay({fail: () => false, xhsReloadDelay:9000});
  const hot = result.xhs.trackDetails.hot;
  assert.equal(result.xhs.trackStatus.hot,'timeout');
  assert.equal(hot.stage,'work_link');
  assert.equal(hot.works,1);
  assert.equal(hot.workDateRejected,1);
  assert.equal(hot.workLinkTimeouts,1);
  assert.ok(!page.opened.includes(xhsWorks[1]));
});

test('a selected social path prefers a visible first-party work over hidden and misleading matches', () => {
  const host = 'https://www.xiaohongshu.com';
  const path = xhsWorks[1];
  const card = {innerText:'A股复盘',querySelector:()=>null};
  const anchor = (href,visible=true) => ({href,getClientRects:()=>visible?[1]:[],
    closest: selector => selector.startsWith('[hidden]') ? null : card, querySelector:()=>null});
  const anchors = [anchor(host+path,false),anchor('https://example.invalid'+path),
    anchor(host+'/redirect?target='+path),anchor(host+path+'?synthetic=1')];
  const result = runInNewContext(`(${discoverWorks.toString()})(args)`, {
    URL,location:new URL(host),args:{platform:'xhs',track:'hot',targetPath:path},
    document:{querySelectorAll: selector => { assert.equal(selector,'a[href*="'+path+'"]'); return anchors; }},
  });
  assert.equal(result,3);
});

test('a discovered public community article can open with its own navigation budget', async () => {
  const forumWork = '/news,zssh000001,123456.html';
  const destination = new URL(forumWork, platforms.em.seeds[0]).href;
  const {result, page} = await replay({fail: () => false, forumWork,
    latency: address => address === destination ? 7000 : 0});
  assert.deepEqual(page.navigations.get(destination), [15000]);
  assert.equal(result.em.status, 'ok');
  assert.equal(result.em.trackDetails.community.works, 1);
  assert.equal(result.em.comments.length, 1);
});

test('a committed document can provide links and comments while embedded resources stall', async () => {
  const {result, page} = await replay({fail: () => false, stalledLoad:true, delayedForum:true,
    forumWork:'/news,zssh000001,123456.html'});
  assert.equal(page.navigations.get(platforms.em.seeds[0]).length, 1);
  assert.equal(result.em.trackDetails.community.works, 1);
  assert.equal(result.em.trackDetails.community.inWindow, 1);
  assert.equal(result.dy.trackDetails.hot.inWindow, 1);
  assert.equal(result.xhs.trackDetails.kol.inWindow, 1);
});

for (const platform of ['xq','em']) {
  test('a selected ' + platform + ' discussion waits for delayed comment rows', async () => {
    const {result} = await replay({fail: () => false, delayedCommentPlatform:platform,
      forumWork:platform === 'em' ? '/news,zssh000001,123456.html' : null});
    assert.equal(result[platform].trackDetails.community.works, 1);
    assert.equal(result[platform].trackDetails.community.inWindow, 1);
  });
}

test('stock bar reply counts prioritize readable discussions without discarding unknown rows', () => {
  const counts = [null, '0', '3', '0', '2', '0', '0', '0', '1'];
  const origin = 'https://guba.eastmoney.com';
  const stockBarPath = i => `/news,zssh000001,${i + 1}.html`;
  const anchors = counts.map((count, i) => ({
    href: origin + stockBarPath(i), getClientRects: () => [1],
    closest: selector => selector === 'tr.listitem' && count !== null
      ? {querySelector: name => name === '.reply' ? {textContent: count} : null} : null,
  }));
  const selected = runInNewContext(`(${discoverWorks.toString()})({platform:'em',track:'community'})`, {
    URL, location: new URL(origin), document: {querySelectorAll: () => anchors},
  });
  assert.deepEqual(Array.from(selected), [2, 4, 8, 0, 1, 3].map(stockBarPath));
});

for (const status of ['login_required', 'captcha_required']) {
  test(status + ' hands off without losing the preceding sample or visiting later platforms', async () => {
    const {result, page, task} = await replay({fail: () => false, challenge: {platform: 'xq', status}});
    assert.equal(result.em.status, 'ok');
    assert.equal(result.em.comments[0].time, '19:20');
    assert.equal(result.xq.status, status);
    assert.equal(result.xq.trackStatus.community, status);
    assert.deepEqual([...page.navigations.keys()], [platforms.em.seeds[0], platforms.xq.seeds[0]]);
    assert.equal(result.ths.status, 'unavailable');
    assert.equal(task.handoffs, 1);
    assert.equal(task.finishes, 0);
  });
}
