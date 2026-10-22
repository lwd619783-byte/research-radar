"""Chromium acceptance of offline V3 fixtures; no production or external requests."""
from __future__ import annotations

import argparse
import datetime as dt
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DISCLAIMER = ('研究内容由 AI 依据公开资料撰写，程序自动检查格式、日期与来源，未经人工审核；'
              '行情由定时任务更新。仅供研究参考，不构成投资建议。')
OLD_UI = ['核验', '核实', '核对', '待复核', '待核', '原评分', '原标记', '人工评分']
VIEWPORTS = [('desk', 1440, 900), ('tab', 1180, 900), ('mobile', 390, 844)]
REQUIRED_SCREENSHOTS = {f'ov_{size}_{theme}_{part}.png'
                        for size, _, _ in VIEWPORTS for theme in ('dark', 'light')
                        for part in ('top', 'full')} | {
                        f'state_{name}.png' for name in ('W03', 'W06', 'D01', 'T01', 'R12')}
POSITIONS = {
    1440: {'#heroTitle': (225, 276), '#today': (200, 442), '#kpis': (464, 516),
           '#pulse': (532, 552), '#topCard': (578, None)},
    1180: {'#today': (391, 535), '#kpis': (557, 609), '#pulse': (625, 645)},
    390: {'#heroTitle': (211, 244), '#heroProv': (256, 276), '#today': (387, None)},
}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
        else:
            super().do_GET()


def check(result, condition, message):
    result['checks'] += 1
    if not condition:
        result['errors'].append(message)


def rect(page, selector):
    node = page.locator(selector)
    if node.count() != 1:
        return None
    return node.bounding_box()


def geometry(page, result, width, height):
    sizes = page.evaluate('''() => ({scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth, body: document.body.scrollWidth})''')
    check(result, sizes['scroll'] == sizes['client'] == width,
          f'horizontal overflow: {sizes}')
    result['positions'] = {}
    for selector, (top, bottom) in POSITIONS[width].items():
        box = rect(page, selector)
        result['positions'][selector] = box
        check(result, box is not None, f'{selector} must exist once')
        if box:
            check(result, abs(box['y'] - top) <= 24,
                  f'{selector} top {box["y"]:.2f}; expected {top} ±24')
            if bottom is not None:
                actual = box['y'] + box['height']
                check(result, abs(actual - bottom) <= 24,
                      f'{selector} bottom {actual:.2f}; expected {bottom} ±24')
    required = {1440: ['#heroTitle', '#today', '#kpis', '#pulse'],
                1180: ['#pulse'], 390: ['#heroTitle', '#heroProv']}[width]
    for selector in required:
        box = rect(page, selector)
        check(result, box is not None and box['y'] >= 0 and
              box['y'] + box['height'] <= height and box['x'] >= 0 and
              box['x'] + box['width'] <= width,
              f'{selector} must be wholly inside the first viewport')
    main, today = rect(page, '.hero-main'), rect(page, '#today')
    if main and today and width == 1440:
        check(result, max(main['y'], today['y']) < min(main['y'] + main['height'], today['y'] + today['height']) and
              today['x'] >= main['x'] + main['width'], 'Desktop hero and daily must share a row')
        top = rect(page, '#topCard')
        check(result, top is not None and top['y'] < height, '#topCard must peek into first screen')
        count = page.locator('.st').evaluate_all('''nodes => nodes.filter(node => {
            const r = node.getBoundingClientRect(), s = getComputedStyle(node);
            return r.width && r.height && r.bottom > 0 && r.top < innerHeight &&
                r.right > 0 && r.left < innerWidth && s.visibility !== 'hidden';
        }).length''')
        check(result, count <= 3, f'First viewport has {count} status labels; maximum 3')
    if main and today and width == 1180:
        check(result, today['y'] >= main['y'] + main['height'], 'Tablet daily must be below hero')
    pulse = page.locator('#pulse')
    check(result, pulse.count() == 1 and pulse.get_attribute('role') == 'status',
          'Pulse must expose role=status')


def scan_dom(page, result, banned):
    found = page.evaluate('''({banned, old, disclaimer}) => {
        const normalize = s => s.normalize('NFKC').replace(/\\s/g, '');
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const all = [], ui = []; let node;
        while ((node = walker.nextNode())) {
            const p = node.parentElement;
            if (!p || p.closest('script,style,noscript')) continue;
            all.push(node.textContent);
            if (!p.closest('[data-src="notion"]')) ui.push(node.textContent);
        }
        for (const el of document.querySelectorAll('*')) {
            for (const key of ['data-tip','title','aria-label','placeholder','alt']) {
                if (!el.hasAttribute(key)) continue;
                all.push(el.getAttribute(key));
                if (!el.closest('[data-src="notion"]')) ui.push(el.getAttribute(key));
            }
        }
        const normalized = normalize(all.join(' ')), interfaceText = ui.join(' ');
        return {banned: banned.filter(x => normalized.includes(normalize(x))),
            old: old.filter(x => interfaceText.includes(x)),
            disclaimers: document.body.innerText.split(disclaimer).length - 1,
            disclaimerId: document.querySelector('#disclaimer')?.textContent.trim(),
            mockNotes: document.querySelectorAll('.mock-note').length};
    }''', {'banned': banned, 'old': OLD_UI, 'disclaimer': DISCLAIMER})
    check(result, not found['banned'], f"banned_words_in_output: {found['banned']}")
    check(result, not found['old'], f"Legacy interface wording: {found['old']}")
    check(result, found['disclaimers'] == 1 and found['disclaimerId'] == DISCLAIMER,
          'Full disclaimer must appear exactly once in #disclaimer')
    check(result, found['mockNotes'] == 0, 'No mock-note elements')
    external_links(page, result)
    check(result, page.locator('#today').evaluate(
        '(node) => !!node.closest(\'[data-src="notion"]\')'),
        'Today content must be marked data-src=notion')


def external_links(page, result):
    unsafe = page.locator('a[href]').evaluate_all('''nodes => nodes.flatMap(node => {
        const raw = node.getAttribute('href');
        if (raw.startsWith('#')) return [];
        let url; try {url = new URL(raw, location.href)} catch {return [{href: raw, reason: 'invalid URL'}]}
        if (url.origin === location.origin && ['http:', 'https:'].includes(url.protocol)) return [];
        const rel = new Set((node.getAttribute('rel') || '').split(/\\s+/));
        const ok = ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password &&
            node.target === '_blank' && rel.has('noopener') && rel.has('noreferrer');
        return ok ? [] : [{href: raw, target: node.target, rel: node.getAttribute('rel')}];
    })''')
    check(result, not unsafe, f'Unsafe external anchors (including hidden ones): {unsafe}')


def keyboard(page, result):
    # Walk the actual Tab order instead of programmatically focusing the labels.
    labels = page.locator('.st').evaluate_all('''nodes => nodes.flatMap((node, i) => {
        const r = node.getBoundingClientRect();
        if (!r.width || !r.height || getComputedStyle(node).visibility === 'hidden') return [];
        node.dataset.acceptanceLabel = String(i);
        return [{id: String(i), tab: node.tabIndex, tip: node.dataset.tip,
            aria: node.getAttribute('aria-label')}];
    })''')
    check(result, bool(labels), 'There must be status labels to exercise')
    for label in labels:
        check(result, label['tab'] == 0 and bool(label.get('tip')) and
              label.get('tip', '') in (label.get('aria') or ''),
              f'Status label {label["id"]} requires tabindex=0 and the complete tip in aria-label')
    remaining = {label['id'] for label in labels}
    page.locator('body').evaluate('(body) => {body.tabIndex = -1; body.focus()}')
    budget = page.locator('a[href],button,input,select,textarea,[tabindex]').count() + 12
    for _ in range(budget):
        page.keyboard.press('Tab')
        active = page.evaluate('''() => ({id: document.activeElement?.dataset.acceptanceLabel,
            tip: document.activeElement?.dataset.tip})''')
        if active.get('id') not in remaining:
            continue
        remaining.remove(active['id'])
        tip = page.locator('#tip')
        check(result, tip.is_visible() and 'on' in (tip.get_attribute('class') or '').split()
              and tip.inner_text().strip() == active['tip'].strip(),
              f'Status label {active["id"]} must reveal its tooltip on Tab focus')
        if not remaining:
            break
    check(result, not remaining, f'Status labels absent from Tab order: {sorted(remaining)}')
    trigger = page.locator('button[data-reason-kind]').first
    check(result, trigger.count() == 1, 'A reason button must exist')
    if trigger.count():
        trigger.click()
        drawer = page.locator('#drawer')
        check(result, drawer.get_attribute('aria-hidden') == 'false', 'Reason drawer must open')
        check(result, page.locator('#reasonBody').evaluate(
            '(node) => !!node.closest(\'[data-src="notion"]\')'),
            'Reason content must be marked data-src=notion')
        external_links(page, result)
        check(result, drawer.evaluate('(node) => node.contains(document.activeElement)'),
              'Opening drawer must move focus inside')
        focusables = drawer.locator('a[href],button,[tabindex="0"]').count()
        for _ in range(focusables + 2):
            page.keyboard.press('Tab')
            check(result, drawer.evaluate('(node) => node.contains(document.activeElement)'),
                  'Tab focus must stay inside the reason drawer')
        page.keyboard.press('Shift+Tab')
        check(result, drawer.evaluate('(node) => node.contains(document.activeElement)'),
              'Reverse Tab focus must stay inside the reason drawer')
        page.keyboard.press('Escape')
        check(result, drawer.get_attribute('aria-hidden') == 'true', 'Escape must close drawer')
        check(result, trigger.evaluate('(node) => document.activeElement === node'),
              'Escape must return focus to the reason button')


def freeze_script(clock):
    milliseconds = int(dt.datetime.fromisoformat(clock).timestamp() * 1000)
    return f'''(() => {{const RealDate = Date; const fixed = {milliseconds};
        class FixedDate extends RealDate {{constructor(...args) {{super(...(args.length ? args : [fixed]))}}
            static now() {{return fixed}}}}
        window.Date = FixedDate;
    }})()'''


def settle(page):
    page.evaluate('() => document.fonts.ready')
    # Real animation time remains usable while Date.now is deterministic.
    page.wait_for_timeout(350)


def screenshots(page, out, name, *, full=True):
    page.evaluate('() => scrollTo(0, 0)')
    if full:
        page.screenshot(path=str(out / f'{name}_top.png'), animations='disabled')
    # Trigger the existing IntersectionObservers naturally for the full page.
    page.evaluate('''async () => {
        for (let y = 0; y < document.documentElement.scrollHeight; y += innerHeight * .75) {
            scrollTo(0, y); await new Promise(requestAnimationFrame);
        }
        scrollTo(0, 0); await new Promise(requestAnimationFrame);
    }''')
    settle(page)
    filename = f'{name}_full.png' if full else f'{name}.png'
    page.screenshot(path=str(out / filename), full_page=True, animations='disabled')


def run(pages: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((pages / 'manifest.json').read_text('utf-8'))
    banned = json.loads((ROOT / 'radar/data/notion_schema.json').read_text('utf-8'))['banned_words']
    report = {'kind': 'offline-visual-acceptance', 'publishable': False,
              'fixtureManifest': manifest, 'results': []}
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(pages)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()

            def visit(name, width=1440, height=900, theme='dark', js=True, legacy=False,
                      metadata=None, operations=None, version=None, company_patch=None):
                result = {'name': name, 'checks': 0, 'errors': [], 'consoleErrors': [], 'pageErrors': []}
                report['results'].append(result)
                fixture = name if name in manifest['pages'] else 'baseline'
                context = browser.new_context(viewport={'width': width, 'height': height},
                    device_scale_factor=1, locale='zh-CN', timezone_id='Asia/Shanghai',
                    color_scheme=theme, reduced_motion='reduce', java_script_enabled=js)
                context.add_init_script(freeze_script(manifest['pages'][fixture]['fixedClock']))
                context.add_init_script(f"localStorage.setItem('ar-theme', '{theme}')")
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on('console', lambda message: result['consoleErrors'].append(message.text)
                        if message.type == 'error' else None)
                page.on('pageerror', lambda error: result['pageErrors'].append(str(error)))
                navigation = {'documents': 0, 'versions': 0}
                result['requests'] = navigation

                def route(request):
                    url = urlparse(request.request.url)
                    if f'{url.scheme}://{url.netloc}' != origin:
                        result['errors'].append(f'External browser request forbidden: {url.scheme}://{url.hostname}')
                        request.abort()
                    elif url.path == '/version.json' and version is not None:
                        navigation['versions'] += 1
                        request.fulfill(status=200, content_type='application/json',
                                        body=json.dumps(version))
                    elif url.path.endswith('/index.html') and (legacy or metadata or operations or company_patch):
                        navigation['documents'] += 1
                        html = (pages / fixture / 'index.html').read_text('utf-8')
                        data_path = pages / 'legacy-DATA.json' if legacy else pages / fixture / 'DATA.json'
                        value = json.loads(data_path.read_text('utf-8'))
                        if metadata:
                            value['meta'].update(metadata)
                        if company_patch:
                            value['companies'][0].update(company_patch)
                        data = json.dumps(value, ensure_ascii=False).replace('</', '<\\/')
                        html, count = re.subn(r'(<script>const DATA=).*?(;</script>)',
                            lambda match: match[1] + data + match[2], html, count=1, flags=re.S)
                        if count != 1:
                            raise RuntimeError('Could not inject browser-only metadata')
                        if operations:
                            value = json.dumps(operations, ensure_ascii=False).replace('</', '<\\/')
                            html, count = re.subn(r'(const OPERATIONS=).*?(;</script>)',
                                lambda match: match[1] + value + match[2], html, count=1, flags=re.S)
                            if count != 1:
                                raise RuntimeError('Could not inject browser-only operations')
                        request.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
                    else:
                        request.continue_()

                context.route('**/*', route)
                page.goto(f'{origin}/{fixture}/index.html', wait_until='networkidle')
                settle(page)
                return context, page, result

            for label, width, height in VIEWPORTS:
                for theme in ('dark', 'light'):
                    name = f'ov_{label}_{theme}'
                    context, page, result = visit(name, width, height, theme)
                    try:
                        check(result, page.locator('html').get_attribute('data-theme') == theme,
                              'Theme must be applied')
                        geometry(page, result, width, height)
                        scan_dom(page, result, banned)
                        screenshots(page, out, name)
                        if label == 'desk' and theme == 'dark':
                            keyboard(page, result)
                    except Exception as error:
                        result['errors'].append(f'{type(error).__name__}: {error}')
                    finally:
                        context.close()
            expected = {'W03': ('#heroProv', '自动生成'), 'W06': ('#heroTitle', '本周主线待更新'),
                        'D01': ('#today', '自动生成'), 'T01': ('#pulse', '研究数据未更新'),
                        'R12': ('body', '数据冲突')}
            for name, (selector, text) in expected.items():
                context, page, result = visit(name)
                try:
                    check(result, text in page.locator(selector).inner_text(),
                          f'{name} must show {text} in {selector}')
                    if name == 'T01':
                        check(result, page.locator('#pulse.warn .dot, #pulse .dot.warn').count() == 1,
                              'Last-good research pulse must use a yellow warning dot')
                    scan_dom(page, result, banned)
                    screenshots(page, out, f'state_{name}', full=False)
                except Exception as error:
                    result['errors'].append(f'{type(error).__name__}: {error}')
                finally:
                    context.close()
            schedule = {'nextRunAt': '2026-10-22T08:45:00+08:00', 'lateAfterMinutes': 60,
                        'cronUtc': ['45 0 * * 1-5', '15 4 * * 1-5', '15 10 * * 1-5']}
            clean = {'notion': {'fallbackTables': [], 'quarantined': []},
                     'stale': [], 'missing': [], 'schedule': schedule,
                     'changesToday': {'reports': 0, 'calendar': 0, 'scores': 0}}
            ops = {'schemaVersion': 1, 'state': 'current', 'dataSHA256': 'a' * 64,
                   'sourceSHA': 'a' * 40, 'runId': '1', 'generatedAt': manifest['fixedClock']}
            version = {**ops, 'dataSHA256': 'b' * 64}
            for state in ('ok', 'warn', 'bad', 'new-version'):
                metadata = dict(clean)
                if state == 'warn':
                    metadata['notion'] = {'fallbackTables': [{'table': 'industries',
                        'code': 'notion_timeout', 'lastGoodFetchedAt': manifest['fixedClock']}],
                        'quarantined': []}
                if state == 'bad':
                    metadata['schedule'] = {**schedule, 'nextRunAt': '2026-10-21T16:00:00+08:00'}
                context, page, result = visit(f'pulse-{state}', metadata=metadata,
                    operations=ops if state == 'new-version' else None,
                    version=version if state == 'new-version' else None)
                try:
                    pulse = page.locator('#pulse')
                    expected_state = 'ok' if state == 'new-version' else state
                    check(result, pulse.evaluate('(node, state) => node.classList.contains(state)', expected_state),
                          f'Pulse must be {expected_state}')
                    text = pulse.inner_text()
                    if state == 'ok':
                        check(result, '下次' in text and '财报 0' in text and
                              '财报日确认 0' in text and '评分 0' in text,
                              'OK pulse must show next schedule and all three zero change counts')
                    elif state == 'warn':
                        check(result, '沿用上次版本' in text and '今日变化' not in text,
                              'Warning pulse must describe fallback and omit today changes')
                    elif state == 'bad':
                        check(result, '本次更新未完成' in text and '下次' in text and '今日变化' not in text,
                              'Late pulse must describe incomplete update and next schedule')
                    else:
                        check(result, '有新数据' in text and page.locator('#refreshSnapshot').is_visible(),
                              'Changed version must offer refresh')
                        before = result['requests']['documents']
                        with page.expect_navigation(wait_until='networkidle'):
                            page.locator('#refreshSnapshot').click()
                        check(result, result['requests']['documents'] == before + 1,
                              'Refresh button must reload the current snapshot')
                        check(result, result['requests']['versions'] >= 2,
                              'Reload must fetch the version again')
                    external_links(page, result)
                    if state in ('warn', 'bad'):
                        pulse.screenshot(path=str(out / f'pulse-{state}.png'), animations='disabled')
                except Exception as error:
                    result['errors'].append(f'{type(error).__name__}: {error}')
                finally:
                    context.close()
            company = json.loads((pages / 'baseline/DATA.json').read_text('utf-8'))['companies'][0]
            context, page, result = visit('overdue-calendar', company_patch={'next': '2026-10-20'})
            try:
                marker = f'[data-co="{company["id"]}"]'
                item = page.locator('#cal ' + marker)
                check(result, item.count() == 1, 'Past earnings date must remain in the complete calendar')
                if item.count():
                    column = item.locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " cal-col ")][1]')
                    check(result, '已过1天' in column.inner_text().replace(' ', '') and
                          '待更新' in column.inner_text(),
                          'Past earnings date must visibly state elapsed days and pending update')
                check(result, page.locator('#soonCard ' + marker).count() == 0,
                      'Past earnings date must not enter the next-two-weeks card')
                external_links(page, result)
            except Exception as error:
                result['errors'].append(f'{type(error).__name__}: {error}')
            finally:
                context.close()
            context, page, result = visit('legacy', legacy=True)
            try:
                check(result, '旧版数据，无研判信息' in page.locator('#heroProv').inner_text(),
                      'Legacy weekly data must visibly remain stale')
                check(result, page.locator('#today').inner_text().count('今日要点待更新') == 2,
                      'Legacy daily must show two pending rows')
                pulse = page.locator('#pulse').inner_text()
                check(result, '研究数据未更新' not in pulse and '下次' not in pulse and '迟到' not in pulse,
                      'Legacy pulse must not infer a research failure or schedule')
                check(result, '研究数据：仓库文件' in page.locator('#foot').text_content(),
                      'Legacy footer must identify repository research data')
                check(result, page.locator('.st').filter(has_text='待更新').count() > 0,
                      'Legacy judgments must remain visibly stale')
                external_links(page, result)
            except Exception as error:
                result['errors'].append(f'{type(error).__name__}: {error}')
            finally:
                context.close()
            context, page, result = visit('no-javascript', js=False)
            try:
                for selector in ('#heroTitle', '#heroProv', '#today', '#kpis', '#pulse', '#disclaimer'):
                    check(result, bool(page.locator(selector).inner_text().strip()),
                          f'SSR {selector} must have real content without JavaScript')
                counts = page.locator('#kpis [data-count]').evaluate_all(
                    'nodes => nodes.map(n => ({text:n.textContent.trim(), value:n.dataset.count}))')
                check(result, bool(counts) and all(item['text'] == item['value'] for item in counts),
                      'SSR KPI text must contain final values before JavaScript')
                scan_dom(page, result, banned)
            except Exception as error:
                result['errors'].append(f'{type(error).__name__}: {error}')
            finally:
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    for result in report['results']:
        check(result, not result['consoleErrors'], f"Console errors: {result['consoleErrors']}")
        check(result, not result['pageErrors'], f"Page errors: {result['pageErrors']}")
    report['screenshots'] = sorted(path.name for path in out.glob('*.png'))
    report['requiredScreenshots'] = sorted(REQUIRED_SCREENSHOTS)
    report['missingScreenshots'] = sorted(REQUIRED_SCREENSHOTS - set(report['screenshots']))
    report['passed'] = not report['missingScreenshots'] and all(not r['errors'] for r in report['results'])
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    report = run(args.pages.resolve(), args.out.resolve())
    for result in report['results']:
        print(f"{result['name']}: {result['checks']} checks; {len(result['errors'])} errors")
        for error in result['errors']:
            print('  ' + error)
    print(f"Screenshots: {len(report['screenshots'])}; required missing={report['missingScreenshots']}; passed={report['passed']}")
    raise SystemExit(0 if report['passed'] else 2)


if __name__ == '__main__':
    main()
