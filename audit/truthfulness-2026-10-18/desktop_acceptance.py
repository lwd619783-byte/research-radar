"""Real Chromium desktop screenshots and DOM assertions; no image fabrication."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE=Path(__file__).resolve().parent
OUT=Path('/tmp/radar-desktop-review')
SHOTS=HERE/'screenshots-finality';SHOTS.mkdir(exist_ok=True)
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    for version in ('before','after'):
        page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1,reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:8765/'+version+'/index.html')
        page.wait_for_selector('#mapTiles .tile')
        for sec in ('radar','choke','leaders','calendar','foot'):
            page.locator('#'+sec).scroll_into_view_if_needed();page.wait_for_timeout(120)
        page.evaluate('window.scrollTo(0,0)');page.wait_for_timeout(300)
        page.screenshot(path=str(SHOTS/(version+'-desktop.png')),full_page=True)
        layout=page.evaluate("""() => ({sections:[...document.querySelectorAll('main > section')].map(e=>e.id),
            topCards:document.querySelectorAll('.bento > article').length, companies:DATA.companies.length,
            cssBytes:document.querySelector('style').textContent.length,
            overflow:document.documentElement.scrollWidth>innerWidth})""")
        for cid in ('CXMT','LITE','SU','KBL','DZSK','ASMPT','TSM'):
            page.evaluate("id=>document.querySelector('[data-co=\"'+id+'\"]').click()",cid)
            page.wait_for_timeout(150)
            text=page.locator('#drawer').inner_text()
            if version=='after':
                assert '业绩快讯 · 待核实' in text if '业绩快讯' in text else True
                if cid=='CXMT':
                    assert '短历史 · 实际54日' in text,text
                    assert '2年·不足' in text and '52周数据不足' in text
                    assert '扭亏·利润同比不适用' in text
                if cid=='LITE': assert '一次性' in text and 'PE(TTM) 缺失' in text
                if cid=='SU': assert '仅收入' in text
                if cid=='KBL': assert '财务待核实 · 半年累计' in text
                if cid=='DZSK': assert '财务待核实 · 初步结果' in text
                if cid=='ASMPT': assert '持续经营收入/毛利' in text and '含终止经营归母净利' in text
                if cid=='TSM': assert 'TWD' in text and '$' in text
            if cid in ('CXMT','LITE','SU','ASMPT'):
                page.screenshot(path=str(SHOTS/(version+'-'+cid.lower()+'.png')))
            page.locator('#dwClose').click()
        if version=='after':
            page.evaluate("document.querySelector('[data-co=\"CXMT\"]').scrollIntoView()")
            page.locator('#mapTiles [data-co="CXMT"]').hover()
            page.wait_for_timeout(100)
            assert '短历史 · 实际 54 个交易日' in page.locator('#tip').inner_text()
            page.screenshot(path=str(SHOTS/'after-cxmt-tooltip.png'))
        assert not errors,errors
        assert not layout['overflow'],layout
        results.append(dict(version=version,layout=layout,pageErrors=errors,urlKind='localhost-http',realFetchedMarket=True))
        page.close()
    browser.close()
assert results[0]['layout']==results[1]['layout'],results
receipt=dict(checkedAt=dt.datetime.now(dt.UTC).isoformat(),viewport={'width':1440,'height':1000},
             browser='system Chromium via installed Playwright',results=results,
             screenshots={f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in SHOTS.glob('*.png')})
(HERE/'desktop-finality-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False,indent=2))
