"""Exercise the shipped V3/V4 page and its seven effects in offline Chromium."""
import argparse
from datetime import datetime, timedelta
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from build_short_term_preview import SAMPLE, build, build_pages
from visual_acceptance import Handler, VIEWPORTS


def no_overflow(page, width):
    dimensions = page.evaluate("""() => [document.documentElement.scrollWidth,
        document.documentElement.clientWidth, document.body.scrollWidth, innerWidth]""")
    assert dimensions == [width] * 4, f'horizontal layout at {width}: {dimensions}'


def open_short(page, *, teaser=False):
    trigger = page.locator('#todayShortTeaser [data-open-short]') if teaser else page.locator('#navShort')
    trigger.click()
    expect(page.locator('#shortTermView')).to_be_visible()
    expect(page.locator('#longTermView')).to_be_hidden()


def short_interactions(page, data):
    pills = page.locator('[data-day-idx]')
    assert len(data['days']) == 10
    expect(pills).to_have_count(10)
    for i, day in enumerate(data['days']):
        pills.nth(i).click()
        expect(pills.nth(i)).to_have_class(re.compile(r'\bactive\b'))
        expect(page.locator('#shortTermView h1')).to_have_text(day['headline'])
        expect(page.locator('.sr-date-top')).to_contain_text(day['date'])
    pills.first.click()
    board = page.locator('[data-board="concept"]')
    board.click()
    expect(page.locator('.sr-duel-grid .card-t').first).to_contain_text('概念题材')
    thumb = board.locator('..').locator('.thumb')
    expect(thumb).to_have_css('width', re.compile(r'^[1-9][0-9.]*px$'))
    assert board.evaluate("""b => {const t=b.parentNode.querySelector('.thumb');
        return t.style.left === b.offsetLeft+'px' && t.style.width === b.offsetWidth+'px'}""")
    page.locator('[data-board="both"]').click()
    expect(page.locator('.card-t').filter(has_text='行业板块 · 涨幅')).to_have_count(1)
    expect(page.locator('.card-t').filter(has_text='概念题材 · 涨幅')).to_have_count(1)
    page.locator('[data-scope="radar"]').click()
    radar = data['days'][0]['stocks']['radar']['up'][0]['name']
    expect(page.locator('[data-scope="radar"]').locator('xpath=ancestor::section[1]')).to_contain_text(radar)
    page.locator('[data-scope="market"]').click()
    for platform in ('em', 'xq', 'ths', 'dy', 'xhs'):
        page.locator(f'[data-plat="{platform}"]').click()
        expected = [p for p in data['days'][0]['ego']['posts'] if p['platform'] == platform]
        assert expected
        expect(page.locator('.sr-ego-post')).to_have_count(len(expected))
        expect(page.locator(f'.sr-ego-post .sr-plat-pill.{platform}')).to_have_count(len(expected))
    page.locator('[data-plat="all"]').click()
    expect(page.locator('.sr-ego-post')).to_have_count(len(data['days'][0]['ego']['posts']))
    page.locator('[data-cat="star5"]').click()
    count = sum(event['stars'] == 5 for event in data['catalysts'])
    assert count > 0
    expect(page.locator('.sr-cat-card')).to_have_count(count)
    expect(page.locator('.sr-cat-card.is-s5')).to_have_count(count)


def focus_section(page, selector):
    # Place the section in the narrow observation band defined by ScrollSpy.
    page.locator(selector).first.evaluate("""e => window.scrollTo({top:
        scrollY + e.getBoundingClientRect().top - innerHeight * .29, behavior:'instant'})""")


def motion_checks(page, out):
    expect(page.locator('.sr-cat-card.is-s5').first).to_have_count(1)
    assert page.locator('.sr-cat-card.is-s5').first.evaluate(
        "e => getComputedStyle(e,'::before').animationName") == 'srScan'
    gauge = page.locator('.sr-gauge-needle').first
    gauge.scroll_into_view_if_needed()
    page.wait_for_function("""() => {const n=document.querySelector('.sr-gauge-needle');
        return n.style.transform.includes(n.dataset.deg+'deg') &&
        document.querySelector('.sr-gauge-arc').style.strokeDashoffset !== ''}""")
    count = gauge.locator('xpath=ancestor::*[contains(@class,"sr-reveal")][1]').locator('[data-count]').first
    expect(count).to_have_text(count.get_attribute('data-count'))
    assert page.locator('.sr-gauge-halo').first.evaluate("e => getComputedStyle(e).animationName") != 'none'
    row = page.locator('.sr-rank-row').first
    # The UI dismisses tooltips on scroll. Stop at the row before placing
    # the pointer, just as a reader does after navigating down the page.
    focus_section(page, '.sr-rank-row')
    page.mouse.move(2, 2)
    page.evaluate("new Promise(ok => requestAnimationFrame(() => requestAnimationFrame(ok)))")
    row.hover()
    expect(page.locator('#srTip.on')).to_have_text(row.get_attribute('data-sr-tip'))
    assert row.evaluate("""e => {const c=e.closest('.sr-glow');
        return !!(c.style.getPropertyValue('--mx') && c.style.getPropertyValue('--my'))}""")
    assert row.evaluate("""e => ['::before','::after'].every(s=>
        getComputedStyle(e.closest('.sr-glow'),s).backgroundImage.includes('radial-gradient'))""")
    assert row.locator('svg path[fill="url(#sr-g-up)"]').is_visible()
    assert page.locator('.sr-spark.down svg path[fill="url(#sr-g-down)"]').count() > 0
    page.screenshot(path=out / '1440-dark-rank-hover.png')
    rail = page.locator('.sr-rail-nav a[href="#srTlCycle"]')
    rail.click()
    expect(page.locator('#srTlCycle .sr-flash')).to_have_count(1)
    focus_section(page, '#srTlLhb')
    expect(page.locator('.sr-rail-nav a[href="#srTlLhb"]')).to_have_class(re.compile(r'\bactive\b'))
    page.wait_for_function("""() => Number(document.querySelector('.sr-tl-stream').style
        .getPropertyValue('--tl-fill')) > .08 && !!document.querySelector('.sr-tl-stage.is-lit') &&
        Number(document.querySelector('#srReadProgress').style.getPropertyValue('--sr-scroll')) > 0""")
    expect(page.locator('#srReadProgress')).to_have_css('height', '2px')
    expect(page.locator('#srTlLhb')).to_have_class(re.compile(r'\bin\b'))
    page.screenshot(path=out / '1440-dark-timeline.png')


def search_returns(page, data):
    page.keyboard.press('Control+k')
    expect(page.locator('#palette')).to_be_visible()
    company = data['companies'][0]
    page.locator('#pq').fill(company['name'])
    page.locator('#pq').press('Enter')
    expect(page.locator('#longTermView')).to_be_visible()
    expect(page.locator('#shortTermView')).to_be_hidden()
    expect(page.locator('#drawer')).to_have_attribute('aria-hidden', 'false')
    expect(page.locator('#drawer')).to_contain_text(company['name'])
    page.keyboard.press('Escape')


def verify_layout(page, base, width, data, out):
    page.goto(base + '/short/index.html')
    expect(page.locator('#longTermView')).to_be_visible()
    expect(page.locator('#shortTermView')).to_be_hidden()
    assert page.locator('#today #todayShortTeaser').count() == 1
    assert page.locator('#foot #disclaimer').count() == page.locator('#disclaimer').count() == 1
    assert page.locator('#longTermView #foot, #shortTermView #foot').count() == 0
    no_overflow(page, width)
    open_short(page, teaser=True)
    for theme in ('dark', 'light'):
        html = page.locator('html')
        if html.get_attribute('data-theme') != theme:
            page.locator('#themeBtn').click()
        expect(html).to_have_attribute('data-theme', theme)
        page.evaluate("scrollTo({top:0,behavior:'instant'})")
        expect(page.locator('.sr-date-strip')).to_have_class(re.compile(r'\bin\b'))
        expect(page.locator('.sr-date-strip')).to_have_css('opacity', '1')
        no_overflow(page, width)
        page.screenshot(path=out / f'{width}-{theme}-short.png')
        convention = html.get_attribute('data-conv')
        up = page.locator('.sr-rank-pct.up').first
        color = up.evaluate('e => getComputedStyle(e).color')
        page.locator('#convBtn').click()
        expect(html).not_to_have_attribute('data-conv', convention)
        expect(up).not_to_have_css('color', color)
        page.locator('#convBtn').click()
        expect(html).to_have_attribute('data-conv', convention)
    page.locator('#themeBtn').click()
    short_interactions(page, data['shortTerm'])
    no_overflow(page, width)
    if width == 1440:
        motion_checks(page, out)
    search_returns(page, data)
    open_short(page)
    home = page.locator('#nav a[data-sec="overview"]')
    (home if home.is_visible() else page.locator('.brand')).click()
    expect(page.locator('#longTermView')).to_be_visible()
    expect(page.locator('#shortTermView')).to_be_hidden()


def degraded_and_reduced(page, base, out):
    page.emulate_media(reduced_motion='reduce')
    page.goto(base + '/legacy/index.html')
    open_short(page)
    expect(page.locator('#shortTermView')).to_contain_text('短线复盘数据暂未生成')
    page.screenshot(path=out / '390-dark-no-data.png')
    page.goto(base + '/stale/index.html')
    open_short(page)
    expect(page.locator('#shortTermView')).to_contain_text(re.compile('沿用|过期|历史快照'))
    expect(page.locator('.sr-date-strip')).to_have_css('transition-duration', '0s')
    expect(page.locator('.sr-gauge-halo').first).to_have_css('animation-name', 'none')
    assert page.locator('.sr-reveal:not(.in)').count() == 0
    assert page.locator('#shortTermView [data-count]').evaluate_all(
        "nodes => nodes.every(n=>Number(n.textContent)===Number(n.dataset.count))")
    page.screenshot(path=out / '390-dark-stale-reduced-motion.png')
    no_overflow(page, 390)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='Screenshot directory')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as tmp, sync_playwright() as pw:
        directory = Path(tmp)
        build_pages(SAMPLE, directory)
        data = json.loads((directory / 'short/DATA.json').read_bytes())
        later = datetime.fromisoformat(data['shortTerm']['generatedAt']) + timedelta(days=8)
        stale = build.read_short_term(later, path=SAMPLE, environ={})
        assert stale['meta']['isStale']
        build.render({**data, 'shortTerm': stale}, directory / 'stale')
        with ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=tmp)) as server:
            Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_port}'
            browser = pw.chromium.launch()
            try:
                for _, width, height in VIEWPORTS:
                    ctx = browser.new_context(viewport={'width': width, 'height': height},
                                              color_scheme='dark', locale='zh-CN')
                    try:
                        errors = []
                        def offline(route):
                            if urlsplit(route.request.url).netloc == urlsplit(base).netloc:
                                route.continue_()
                            else:
                                errors.append('external request ' + urlsplit(route.request.url).netloc)
                                route.abort()
                        ctx.route('**/*', offline)
                        page = ctx.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.set_default_timeout(7000)
                        verify_layout(page, base, width, data, args.out)
                        if width == 390:
                            degraded_and_reduced(page, base, args.out)
                        assert not errors, errors
                        print(f'PASS {width}x{height}, dark/light and interactions', flush=True)
                    finally:
                        ctx.close()
            finally:
                server.shutdown()
                browser.close()


if __name__ == '__main__':
    main()

