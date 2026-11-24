"""Aggregate dated, read-only comment samples; keep raw identities in memory only."""
from collections import Counter
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import tomllib
import unicodedata
from urllib.parse import urlsplit

from market_calendar import calendar_data, is_session
from short_term_merge import sanitize_short_term_text


MODULE = Path(__file__).resolve().parent
WHITELIST = MODULE.parents[1] / 'data/kol_whitelist.toml'
NAMES = {'em': '东方财富股吧', 'xq': '雪球社区', 'ths': '同花顺论股堂',
         'dy': '抖音评论区', 'xhs': '小红书评论区'}
DOMAINS = {'em': 'eastmoney.com', 'xq': 'xueqiu.com', 'ths': '10jqka.com.cn',
           'dy': 'douyin.com', 'xhs': 'xiaohongshu.com'}
SOCIAL = {'dy', 'xhs'}
TRACKS = {'forum': 'community', 'community': 'community', 'hot': 'hot',
          'whitelist': 'kol', 'kol': 'kol'}
CONTEXT = {'community': '社区讨论', 'hot': '复盘话题评论', 'kol': '白名单作品评论'}
PRIVATE = re.compile(r'https?\s*[:：]|www\.|[\w.+-]+\s*[@＠]\s*[\w.-]+\.[a-z]{2,}'
                     r'|\b[a-z0-9-]+\.(?:com|cn|net|org|io|xyz|top|me)\b'
                     r'|(?<!\d)(?:\+?86[-\s]*)?1[3-9](?:[\s-]?\d){9}(?!\d)'
                     r'|(?:\+\d{1,3}[-\s]?)?\(\d{3}\)[\s-]*\d{3}[-\s]*\d{4}'
                     r'|\b\d{17}[0-9x]\b', re.I)
PROMO = re.compile(r'加(?:我|微|薇|威|v|vx|v信|wx|群|q|扣)|[微薇威徵][信芯❤♥]'
                   r'|(?:微信|wechat|vx|v信|wx|qq|企鹅号|手机号|联系方式)[:号]?'
                   r'|进群|入群|带单|带你做|私信|私聊|主页.*(?:联系|有货)|二维码|扫码|免费领|开户链接'
                   r'|联系方式|点我头像|代客理财|扣扣|关注回关', re.I)
NOISE = re.compile(r'^(?:哈哈|呵呵|收到|打卡|签到|路过|围观|点赞|沙发|支持|关注|顶|好|赞|牛)+$')
BULL = re.compile('看涨|看多|多头|偏强|走强|上涨|突破|放量回升|承接较强|继续上行|企稳|不看空')
BEAR = re.compile('看跌|看空|空头|偏弱|走弱|下跌|跌破|缩量回落|承接较弱|继续下行|不看好|承压')
CJ = timezone(timedelta(hours=8))
SIGNATURE = 'dated-comments-v1'
MARK = 'RESEARCH_RADAR_EGO_V4 '
STATUS = {'ok', 'partial', 'empty', 'no_sample', 'timeout', 'login_required', 'captcha',
          'handoff', 'unavailable', 'skipped', 'error', 'user_control'}


def _empty(message, status=None):
    return dict(score=None, state='样本暂缺', summary=message, platforms=[], posts=[],
                coverage='missing', sampleCount=0,
                platformStatus=status or {p: 'unavailable' for p in NAMES})


def _validated_config():
    file = Path(os.environ.get('SHORT_TERM_KOL_WHITELIST_FILE') or WHITELIST)
    with file.open('rb') as stream:
        settings = tomllib.load(stream)['platforms']
    config = {}
    for platform in NAMES:
        opts = settings[platform]
        key = 'kol' if platform in SOCIAL else 'seeds'
        urls = opts.get(key, [])
        if not isinstance(urls, list) or len(urls) > 16:
            raise ValueError('invalid URLs')
        for url in urls:
            parsed = urlsplit(url)
            host = parsed.hostname or ''
            domain = DOMAINS[platform]
            if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port
                    or parsed.query or parsed.fragment or len(url) > 512 or
                    (host != domain and not host.endswith('.' + domain))):
                raise ValueError('expected public profile or community URL')
            if platform == 'dy' and not re.fullmatch(r'/user/[a-zA-Z0-9_-]+/?', parsed.path):
                raise ValueError('expected Douyin profile')
            if platform == 'xhs' and not re.fullmatch(r'/user/profile/[a-zA-Z0-9_-]+/?', parsed.path):
                raise ValueError('expected Xiaohongshu profile')
        config[platform] = {key: urls}
        if platform in SOCIAL:
            tags = opts.get('tags', ['A股复盘'])
            if not isinstance(tags, list) or not 1 <= len(tags) <= 3 or not all(
                    isinstance(tag, str) and re.fullmatch(r'[\w\u3400-\u9fff]{1,25}', tag) for tag in tags):
                raise ValueError('invalid topic')
            config[platform]['tags'] = tags
    return config


def _live(day, config):
    executable = os.environ.get('SHORT_TERM_EGO_BROWSER') or shutil.which('ego-browser')
    if not executable:
        raise FileNotFoundError('Ego unavailable')
    module = (MODULE / 'ego_reader.mjs').as_uri()
    with TemporaryDirectory(prefix='radar-ego-') as home:
        entry = Path(home) / 'read.mjs'
        # Ego executes in its own ESM scope without inheriting cwd or environment.
        # Only the public configuration is in the temp file. Captures remain in memory.
        entry.write_text('const {readSentiment}=await import(' + json.dumps(module) + ');\n'
            'const captured=await readSentiment(' + json.dumps(dict(date=day.isoformat(), platforms=config),
                ensure_ascii=False) + ');\nconsole.log(' + json.dumps(MARK) + '+JSON.stringify(captured));\n',
            encoding='utf-8')
        code = 'await import(' + repr(entry.as_uri()) + ')'
        result = subprocess.run([executable, 'nodejs', '-e', code], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=240, check=True)
    for raw in reversed(result.stdout.decode('utf-8', errors='replace').splitlines()):
        if raw.startswith(MARK) and len(raw) <= 2_000_000:
            return json.loads(raw[len(MARK):])
    raise ValueError('no browser capture')


def _clean_comment(item):
    value = item.get('text')
    if not isinstance(value, str) or len(value) > 2000:
        return None
    value = unicodedata.normalize('NFKC', value)
    value = ''.join(c for c in value if unicodedata.category(c) not in ('Cf', 'Cs', 'Cc') or c in '\r\n\t')
    value = ' '.join(value.split())
    compact = re.sub(r'[\W_]+', '', value)
    if PRIVATE.search(value) or PROMO.search(compact) or re.search(r'1[3-9]\d{9}', compact):
        return None
    if len(compact) < 6 or len(set(compact)) < 4 or NOISE.fullmatch(compact):
        return None
    for key in ('author', 'username', 'nickname'):
        name = item.get(key)
        if isinstance(name, str) and name.strip():
            value = value.replace(name, '匿名用户')
    value = re.sub(r'^(?:回复|回覆|转发自|引用)\s*[^:：，。！？]{1,35}[:：]\s*', '', value)
    value = sanitize_short_term_text(value)
    value = re.sub(r'匿名用户(?:\s*匿名用户)+', '匿名用户', value)
    if len(re.sub(r'[\W_]+', '', value.replace('匿名用户', ''))) < 6:
        return None
    return value[:180]


def _stance(quote):
    # Resolve explicit negations before counting terms such as 看空 and 看多.
    query = (quote.replace('不看空', '偏强').replace('不看跌', '偏强')
             .replace('不看多', '偏弱').replace('不看涨', '偏弱'))
    bull, bear = bool(BULL.search(query)), bool(BEAR.search(query))
    return 'flat' if bull == bear else 'bull' if bull else 'bear'


def _platform_samples(platform, capture, day):
    seen_ids, seen_text, samples = set(), set(), []
    counts = Counter()
    valid_tracks = {'kol', 'hot'} if platform in SOCIAL else {'community'}
    start = '18:00' if platform in SOCIAL else '15:00'
    comments = capture.get('comments')
    if not isinstance(comments, list):
        return samples, counts
    for item in comments[:300]:
        if not isinstance(item, dict):
            continue
        label = item.get('track')
        track = TRACKS.get(label) if isinstance(label, str) else None
        stamp = str(item.get('time', ''))
        if track not in valid_tracks or item.get('date') != day.isoformat() or not re.fullmatch(
                r'(?:[01]\d|2[0-3]):[0-5]\d', stamp) or not start <= stamp <= '20:15':
            continue
        quote = _clean_comment(item)
        if not quote:
            continue
        duplicate_key = re.sub(r'[\W_]+', '', quote).lower()
        ref = item.get('id')
        if not isinstance(ref, (str, int)):
            ref = None
        if duplicate_key in seen_text or (ref and ref in seen_ids):
            continue
        if ref:
            seen_ids.add(ref)
        seen_text.add(duplicate_key)
        direction = _stance(quote)
        counts[direction] += 1
        samples.append(dict(quote=quote, track=track, time=stamp, direction=direction,
                            likes=item.get('likes')))
    return samples, counts


def _prior(previous, day):
    if not isinstance(previous, dict):
        return {}
    prior = day - timedelta(days=1)
    exchange = calendar_data()['exchanges']['XSHG']
    while not is_session(exchange, prior):
        prior -= timedelta(days=1)
    if previous.get('date') != prior.isoformat():
        return {}
    return {row['id']: row for row in (previous.get('ego') or {}).get('platforms', [])
            if isinstance(row, dict) and row.get('id') in NAMES}


def collect_sentiment(day, *, skip=False, previous=None, captures=None):
    if skip:
        return _empty('已跳过本机舆情采集', {p: 'skipped' for p in NAMES})
    signature = {}
    if captures is None:
        if any(os.environ.get(k, '').lower() not in ('', '0', 'false') for k in ('CI', 'GITHUB_ACTIONS')):
            return _empty('当前运行环境仅处理离线样本')
        now = datetime.now(CJ)
        if now.date() != day or now.time() < time(20, 15):
            return _empty('实时采样仅在对应交易日 20:15 后执行')
        try:
            config = _validated_config()
            signature = {k: hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()[:16]
                         for k, v in config.items()}
            captures = _live(day, config)
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
            return _empty('本机 Ego 未返回本次样本')
    if not isinstance(captures, dict):
        return _empty('未取得平台样本')
    baseline = _prior(previous, day)
    platforms, posts, scores, details = [], [], [], []
    status = {}
    for platform, name in NAMES.items():
        cap = captures.get(platform) or {}
        raw_status = cap.get('status') if isinstance(cap, dict) else None
        if raw_status == 'captcha_required':
            raw_status = 'captcha'
        status[platform] = raw_status if isinstance(raw_status, str) and raw_status in STATUS else 'unavailable'
        if not isinstance(cap, dict) or raw_status not in ('ok', 'partial', 'captcha', 'login_required', 'timeout'):
            continue
        samples, counts = _platform_samples(platform, cap, day)
        total = len(samples)
        if not total:
            status[platform] = 'no_sample' if raw_status == 'ok' else raw_status
            continue
        bull = round(counts['bull'] * 100 / total, 1)
        bear = round(counts['bear'] * 100 / total, 1)
        tracks = sorted({s['track'] for s in samples})
        expected = ['hot', 'kol'] if platform in SOCIAL else ['community']
        complete = cap['status'] == 'ok' and tracks == expected
        if raw_status in ('ok', 'partial'):
            status[platform] = 'ok' if complete else 'partial'
        comparable = complete and not cap.get('truncated') and len(cap.get('comments', [])) < 300
        method = SIGNATURE + '-' + signature.get(platform, 'fixture')
        old = baseline.get(platform, {})
        previous_count = old.get('sampleCount')
        volume = '—'
        if (comparable and old.get('comparable') is True and old.get('sampleMethod') == method
                and old.get('tracks') == tracks and type(previous_count) is int and previous_count > 0):
            volume = f'{(total / previous_count - 1):+.0%}'
        platforms.append(dict(id=platform, name=name, kind='晚间作品评论' if platform in SOCIAL else '盘后社区评论',
            bull=bull, flat=round(100 - bull - bear, 1), bear=bear, sampleCount=total, volume=volume,
            note=f'有效评论 {total} 条。变化按同口径有效样本数计算。', hotTopic=' / '.join(CONTEXT[t] for t in tracks),
            tracks=tracks, coverage='complete' if complete else 'partial', comparable=comparable, sampleMethod=method))
        scores.append(100 * (counts['bull'] + .5 * counts['flat']) / total)
        details.append((platform, bull))
        for item in samples[:3]:
            direction, likes = item['direction'], item['likes']
            tag, css = {'bull': ('偏多', 'up-tag'), 'flat': ('中性或分歧', 'stale'),
                        'bear': ('偏空', 'down-tag')}[direction]
            like_text = f'{likes} 赞' if type(likes) is int and 0 <= likes <= 100_000_000 else '赞数暂缺'
            posts.append(dict(platform=platform, platName=name, pillClass=platform,
                kolContext=CONTEXT[item['track']], author='匿名用户', time=item['time'], likes=like_text,
                sentimentTag=tag, sentimentTone=css, quote=item['quote'], aiDiag='按评论方向词归类 · ' + tag))
    if not scores:
        return _empty('本次未取得符合时间和去噪条件的评论', status)
    score = round(sum(scores) / len(scores))
    social = [v for k, v in details if k in SOCIAL]
    forum = [v for k, v in details if k not in SOCIAL]
    spread = round(sum(social) / len(social) - sum(forum) / len(forum), 1) if social and forum else None
    complete = len(platforms) == 5 and all(p['coverage'] == 'complete' for p in platforms)
    count = sum(p['sampleCount'] for p in platforms)
    summary = f'有效评论 {count} 条，覆盖 {len(platforms)}/5 平台。'
    if not complete:
        summary += '部分覆盖。'
    if spread is not None:
        summary += f'短视频及图文圈相对社区的看多占比差为 {spread:+.1f} 个百分点。'
    return dict(score=score, state='样本偏多' if score > 60 else '样本偏空' if score < 40 else '样本分歧',
                summary=summary, sampleCount=count, platforms=platforms, posts=posts,
                circleSpread=spread, coverage='complete' if complete else 'partial', platformStatus=status)
