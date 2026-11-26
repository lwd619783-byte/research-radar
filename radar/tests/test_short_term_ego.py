"""Offline V4 comment aggregation. Run this file with --html for real DOM replay."""
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

RADAR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RADAR / 'scripts'), str(RADAR / 'tools')]
from short_term_collector import ego_sentiment as ego
from output_scan import UI_WORDS
from short_term_merge import contract

FIX = RADAR / 'tests/fixtures/short_term_v4/ego'
DAY = date(2026, 11, 24)


def captures():
    return json.loads((FIX / 'captures.json').read_bytes())


class SentimentTests(unittest.TestCase):
    def test_all_platform_json_and_metric_sample_share(self):
        raw = captures()
        raw['xq'].update(trackStatus={'community': 'ok'},
                         trackDetails={'community': {'stage': 'comment_sample', 'rows': 8}})
        data = ego.collect_sentiment(DAY, captures=raw)
        self.assertEqual(data['platformDiagnostics'], {'xq': {'community': {
            'status': 'ok', 'stage': 'comment_sample', 'rows': 8}}})
        self.assertEqual((data['coverage'], data['sampleCount']), ('complete', 7))
        self.assertEqual(len(data['platforms']), 5)
        # Per-platform scores are 100, 50, 100, 25 and 75; all five are equally weighted.
        self.assertEqual(data['score'], 70)
        self.assertEqual(data['circleSpread'], -41.7)
        self.assertTrue(all(row['volume'] == '—' for row in data['platforms']))
        self.assertTrue(all(row['author'] == '匿名用户' for row in data['posts']))
        self.assertTrue(all(row['bull']+row['bear']+row['flat']==100 for row in data['platforms']))

    def test_zero_sample_track_diagnostics_allow_only_reported_counts_and_enums(self):
        private = 'https://example.test/profile/@private'
        raw = {
            'em': {'status': 'timeout', 'trackStatus': {'community': 'timeout', private: 'ok'},
                   'trackDetails': {'community': {'stage': 'seed_navigation', 'navigationRetries': 1,
                        'links': 0, 'rows': 0, 'works': False, 'inWindow': 10**20, 'dated': -1, 'url': private},
                        'hot': {'stage': 'hot_author'}}},
            'xhs': {'status': 'empty', 'trackStatus': {'kol': 'unconfigured', 'hot': private},
                    'trackDetails': {'hot': {'stage': private, 'navigationRetries': True, 'links': '0'}}},
            'dy': {'trackStatus': [], 'trackDetails': {'kol': [private]}},
            private: {'trackStatus': {'community': 'ok'}}}
        data = ego.collect_sentiment(DAY, captures=raw)
        self.assertEqual(data['sampleCount'], 0)
        self.assertIsNone(data['score'])
        self.assertEqual(data['platformDiagnostics'], {
            'em': {'community': {'status': 'timeout', 'stage': 'seed_navigation', 'navigationRetries': 1,
                                 'links': 0, 'rows': 0}},
            'xhs': {'kol': {'status': 'unconfigured'}}})
        self.assertNotIn(private, json.dumps(data))
        self.assertEqual(ego.collect_sentiment(DAY, skip=True)['platformDiagnostics'], {})

    def test_before_writing_scrub_identifiers_and_all_scan_words(self):
        words = list(contract()['ego_sanitization']['banned_word_mask_map']) + list(UI_WORDS)
        muted = ego._clean_comment({'text': '回复 某个用户: @网名，今天盘后讨论 ' + '、'.join(words)})
        self.assertIsInstance(muted, str)
        self.assertTrue(all(term not in muted for term in words))
        self.assertNotIn('某个用户', muted)
        self.assertNotIn('网名', muted)
        self.assertIn('匿名用户', muted)
        self.assertNotIn('真实昵称', ego._clean_comment({'text':'真实昵称表达了对板块的谨慎看法。','author':'真实昵称'}))
        for dirty in ('盘后讨论，获利联系v－信 demo9', '复盘交流群，ＶＸ：abc789',
                      '盘后交流一三号，请打 138 1234 5678', '下午观点，联系 foo@example.com',
                      '讨论区详细内容 www.test.cn', '完整盘面 https://test.com/u/3',
                      '今天进\u200b群看指数', '哈哈哈哈', '打卡打卡打卡'):
            self.assertIsNone(ego._clean_comment({'text': dirty}), dirty)

    def test_unknown_timestamp_stale_future_and_repeat_drop(self):
        raw = captures()
        row = raw['dy']['comments'][0]
        raw['dy']['comments'] += [{**row, 'id': str(i), 'text': '另一条有意义的盘后观察', **extra}
                                 for i, extra in enumerate(({'date':None}, {'time':'17:59'},
                                                            {'time':'20:16'}, {'track':'unknown'}))]
        raw['dy']['comments'] += [row, {**row, 'id':'else'}]
        result = ego.collect_sentiment(DAY, captures=raw)
        self.assertEqual(next(p for p in result['platforms'] if p['id']=='dy')['sampleCount'], 2)

    def test_same_previous_session_and_sampling_method_only(self):
        raw = captures()
        old = ego.collect_sentiment(DAY, captures=raw)
        previous = {'date':'2026-11-23', 'ego':old}
        raw['em']['comments'].append(dict(text='午后承接较强，交易量也有所回升。',
            date=str(DAY), time='19:42', track='forum'))
        def volume():
            return ego.collect_sentiment(DAY, previous=previous, captures=raw)['platforms'][0]['volume']
        self.assertEqual(volume(), '+100%')
        raw['em']['truncated'] = True
        self.assertEqual(volume(), '—')
        del raw['em']['truncated']
        previous['date'] = '2026-11-20'
        self.assertEqual(volume(), '—')
        previous['date'] = '2026-11-23'
        old['platforms'][0]['sampleMethod'] = 'different'
        self.assertEqual(volume(), '—')

    def test_single_track_one_source_failure_and_empty_are_explicit(self):
        raw = captures()
        raw['xhs']['comments'] = [r for r in raw['xhs']['comments'] if r['track']=='hot']
        raw['dy'] = {'status':'captcha_required','comments':[]}
        result = ego.collect_sentiment(DAY, captures=raw)
        self.assertEqual(result['platformStatus']['dy'], 'captcha')
        self.assertEqual(result['platformStatus']['xhs'], 'partial')
        self.assertEqual(result['coverage'], 'partial')
        self.assertIsNotNone(result['score'])
        failure = ego.collect_sentiment(DAY, captures={'dy':{'status':'login_required'},
            'xhs':{'status':'arbitrary upstream text not safe'}})
        self.assertIsNone(failure['score'])
        self.assertEqual(failure['platformStatus']['dy'], 'login_required')
        self.assertNotIn('arbitrary', str(failure))

    def test_skip_or_ci_never_launches_ego(self):
        with patch.object(ego, '_live', side_effect=AssertionError('browser contacted')):
            self.assertIsNone(ego.collect_sentiment(DAY, skip=True, captures=captures())['score'])
            with patch.dict(os.environ, {'GITHUB_ACTIONS':'true'}, clear=True):
                self.assertIsNone(ego.collect_sentiment(DAY)['score'])

    def test_counterpoint_uses_actual_breadth_and_adequate_anonymous_samples(self):
        rows = [dict(text=f'今天继续看多，承接力度观察样本 {i}', date=str(DAY), time='19:00', track='community')
                for i in range(5)]
        dataset = {'em': {'status': 'ok', 'comments': rows}}
        compared = ego.collect_sentiment(DAY, captures=dataset, breadth={'up': 100, 'down': 300})
        self.assertIn('75% 下跌，两者方向背离', compared['posts'][0]['aiDiag'])
        self.assertIn('待核', ego.collect_sentiment(DAY, captures=dataset)['posts'][0]['aiDiag'])
        dataset['em']['comments'].pop()
        small = ego.collect_sentiment(DAY, captures=dataset, breadth={'up': 100, 'down': 300})
        self.assertIn('待核', small['posts'][0]['aiDiag'])

    def test_bundled_config_and_safe_esm_entry(self):
        with patch.dict(os.environ, {}, clear=True):
            config = ego._validated_config()
        self.assertEqual(set(config), set(ego.NAMES))
        def fake_run(command, **kw):
            self.assertEqual(command[:3], ['ego-browser', 'nodejs', '-e'])
            self.assertTrue(command[3].startswith("await import('file:///"))
            import urllib.request
            runner = Path(urllib.request.url2pathname(command[3][len("await import('file:"):-2]))
            script = runner.read_text('utf-8')
            self.assertIn('readSentiment', script)
            self.assertIn('ego_reader.mjs', script)
            self.assertNotIn('process.env', script)
            self.assertEqual(kw['stdout'], subprocess.PIPE)
            self.assertEqual(kw['stderr'], subprocess.STDOUT)
            stream = 'Ego diagnostic\r\n' + ego.MARK + '{"em":{"status":"ok"}}\r\n'
            return subprocess.CompletedProcess(command, 0, stream.encode())
        with patch.dict(os.environ, {'SHORT_TERM_EGO_BROWSER':'ego-browser'}), patch.object(subprocess, 'run', side_effect=fake_run):
            self.assertEqual(ego._live(DAY, config), {'em':{'status':'ok'}})


def replay_html():
    """Execute the shipped extractComments function in real Chromium, entirely offline."""
    from playwright.sync_api import sync_playwright
    reader = (RADAR / 'tools/short_term_collector/ego_reader.mjs').as_uri()
    program = (f'import {{extractComments,discoverWorks,approvedHotAuthor}} from {json.dumps(reader)};'
               'process.stdout.write(JSON.stringify([extractComments,discoverWorks,approvedHotAuthor].map(f=>f.toString())))')
    extractor, discovery, author_check = json.loads(subprocess.check_output(
        ['node', '--input-type=module', '-e', program], encoding='utf-8'))
    raw = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.route('**/*', lambda route: route.abort())
        for platform in ego.NAMES:
            page.set_content((FIX / f'{platform}.html').read_text('utf-8'))
            result = page.evaluate('(' + extractor + ')', dict(platform=platform, date=str(DAY),
                now='2026-11-24T20:30:00+08:00', track='hot' if platform in ego.SOCIAL else 'community'))
            assert result['status'] == 'ok', (platform,result['status'])
            assert len(result['comments']) == 2, (platform,'same-day source dates')
            assert all('测试昵称乙' not in r['text'] and r['date']==str(DAY) for r in result['comments'])
            raw[platform] = result
        page.set_content('''<div class="comment-item"><div class="comment-content">有效正文但发生在窗口外</div>
          <time datetime="2026-11-24T20:16:00+08:00">2分钟前</time></div>''')
        result = page.evaluate('(' + extractor + ')', dict(platform='xhs', date=str(DAY),
            now='2026-11-24T20:17:00+08:00', track='hot'))
        assert result['comments'] == [] and result['counts'] == {'rows':1,'dated':1,'inWindow':0}
        page.set_content('''
          <div class="reply_item"><div class="reply_title_span">盘后评论内容位于已验证窗口</div>
            <span class="pubtime">发表于 11-24 19:17:11</span></div>
          <div class="reply_item"><div class="reply_title_span">晚间评论在截止时间之后</div>
            <span class="pubtime">发表于 11-24 21:28:06</span></div>''')
        result = page.evaluate('(' + extractor + ')', dict(platform='em', date=str(DAY),
            now='2026-11-24T23:40:00+08:00', track='community'))
        assert result['counts'] == {'rows':2,'dated':2,'inWindow':1}
        assert [comment['time'] for comment in result['comments']] == ['19:17']
        url = 'https://xueqiu.com/S/SH000001'
        page.route(url, lambda route: route.fulfill(content_type='text/html', body='''
            <a href="https://www.xueqiu.com/123/456">收盘讨论</a>
            <a href="https://example.com/987/654">外站链接</a>
            <a href="http://xueqiu.com/456/789">无 HTTPS</a>'''))
        page.goto(url)
        assert page.evaluate('(' + discovery + ')', dict(platform='xq',track='community')) == ['/123/456']
        media_url = 'https://www.douyin.com/video/42'
        page.route(media_url, lambda route: route.fulfill(content_type='text/html', body='''
            <div data-e2e="video-author-name"><a href="/user/ACTUAL">作品作者</a></div>
            <a href="/user/OTHER">相关推荐</a>'''))
        page.goto(media_url)
        observed = page.evaluate('(' + author_check + ')', dict(platform='dy', authors=['https://www.douyin.com/user/ACTUAL']))
        unrelated = page.evaluate('(' + author_check + ')', dict(platform='dy', authors=['https://www.douyin.com/user/OTHER']))
        assert observed and not unrelated
        browser.close()
    result = ego.collect_sentiment(DAY, captures=raw)
    assert len(result['platforms']) == len(result['posts']) == result['sampleCount'] == 5
    assert all(p['likes']=='12 赞' for p in result['posts'])
    assert all('demo12345' not in p['quote'] for p in result['posts'])
    print('PASS: five native HTML DOMs -> 10 same-day comments -> 5 anonymous clean samples')


if __name__ == '__main__':
    if sys.argv[1:] == ['--html']:
        replay_html()
    else:
        unittest.main()
