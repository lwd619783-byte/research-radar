import assert from 'node:assert/strict';
import {test} from 'node:test';
import {discoverWorks, datedReview, extractComments, readPlatforms}
  from '../../../../tools/short_term_collector/ego_reader.mjs';

const date = '2026-11-24';
const platforms = {
  em: {seeds: ['https://guba.eastmoney.com/list,zssh000001.html']},
  xq: {seeds: ['https://xueqiu.com/S/SH000001']},
  ths: {seeds: ['https://t.10jqka.com.cn/']},
  dy: {kol: ['https://www.douyin.com/user/offline'], tags: ['A股复盘']},
  xhs: {kol: ['https://www.xiaohongshu.com/user/profile/offline'], tags: ['A股复盘']},
};

class FakePage {
  constructor({fail, challenge, clock}) {
    this.fail = fail;
    this.challenge = challenge;
    this.clock = clock;
    this.address = 'about:blank';
    this.navigations = new Map();
  }

  async goto(address, {timeout}) {
    const calls = this.navigations.get(address) || [];
    this.navigations.set(address, calls);
    calls.push(timeout);
    if (this.fail(address, calls.length)) {
      this.clock.value += timeout;
      throw Object.assign(new Error('Navigation timed out'), {code: 'EGO_NAVIGATION_TIMEOUT'});
    }
    this.address = address;
  }

  async url() { return this.address; }

  async evaluate(fn, args) {
    if (fn === extractComments) {
      if (this.challenge?.platform === args.platform) {
        return {status: this.challenge.status, comments: []};
      }
      return {status: 'ok', counts: {rows: 1, dated: 1, inWindow: 1},
        comments: [{text: '离线复盘评论 ' + args.track, track: args.track, date, time: '19:20'}]};
    }
    if (fn === discoverWorks) {
      return args.platform === 'dy' ? ['/video/123456'] : ['/explore/1234567890abcdef'];
    }
    if (fn === datedReview) return true;
    assert.fail('Unexpected evaluation in navigation replay');
  }

  async click(selector) {
    const path = selector.match(/a\[href\*="([^"]+)"\]/)?.[1];
    assert.ok(path, 'Only the selected synthetic work may be opened');
    this.address = new URL(path, this.address).href;
    return {};
  }

  async waitForFunction() { return true; }
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
  for (const [seed, calls] of page.navigations) assert.deepEqual(calls, [8500, 14000], seed);
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
