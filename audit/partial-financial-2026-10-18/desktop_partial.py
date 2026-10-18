"""Actual desktop Chromium checks for scoped labels and ranking exclusion."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE=Path(__file__).resolve().parent;OUT=HERE/'screenshots';OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1,reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8765/after/index.html');page.wait_for_selector('#mapTiles .tile')
    for cid in ('KBL','DZSK'):
        page.evaluate("id=>document.querySelector('[data-co=\"'+id+'\"]').click()",cid)
        page.wait_for_timeout(150)
        text=page.locator('#drawer').inner_text()
        assert '部分披露 · 不评分' in text
        if cid=='KBL':assert '2026H1累计' in text and '半年累计' in text and '+209%' in text and '30.7%' in text
        if cid=='DZSK':assert '2026Q3初步推算' in text and '+87.8%' in text and '+157%' in text
        assert page.locator('#drawer').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
        page.screenshot(path=str(OUT/(cid.lower()+'-partial.png')))
        if cid=='DZSK':
            page.locator('#drawer .dw-sec[data-tip]').hover();page.wait_for_timeout(80)
            assert '9M快报−H1' in page.locator('#tip').inner_text()
            box=page.locator('#tip').bounding_box();assert box['y']>=0 and box['y']+box['height']<=1000
            page.screenshot(path=str(OUT/'dzsk-scope-tooltip.png'))
        page.locator('#dwClose').click()
    page.locator('#viewSeg button[data-v="table"]').click()
    ranking=[]
    for metric,lastn in (('revg',2),('earng',5)):
        for direction in range(2):
            page.locator('#tbl th[data-sort="'+metric+'"]').click()
            ids=page.locator('#tbl tbody tr').evaluate_all('(rows)=>rows.map(r=>r.dataset.co)')
            assert {'KBL','DZSK'}<=set(ids[-lastn:]),ids
            column=page.locator('#tbl thead th').evaluate_all('(cols,k)=>cols.findIndex(c=>c.dataset.sort===k)',metric)
            for cid in ('KBL','DZSK'):
                row=page.locator('#tbl tbody tr[data-co="'+cid+'"]')
                assert row.locator('td').nth(column).inner_text()=='—'
                assert '不评分' in row.inner_text()
            ranking.append({'metric':metric,'sortDirectionIndex':direction,'lastIds':ids[-lastn:]})
    page.locator('#tbl tbody tr[data-co="KBL"]').scroll_into_view_if_needed()
    page.screenshot(path=str(OUT/'partial-excluded-from-ranking.png'))
    page.locator('#viewSeg button[data-v="map"]').click()
    page.locator('#metricSeg button[data-v="revg"]').click()
    colors=[page.locator('#mapTiles [data-co="'+cid+'"]').evaluate('(el)=>el.style.backgroundColor') for cid in ('KBL','DZSK')]
    assert colors==['rgb(42, 46, 57)']*2,colors
    layout=page.evaluate("""()=>({sections:[...document.querySelectorAll('main > section')].map(e=>e.id),
        topCards:document.querySelectorAll('.bento > article').length,companies:DATA.companies.length,
        cssBytes:document.querySelector('style').textContent.length,overflow:document.documentElement.scrollWidth>innerWidth})""")
    old=json.loads((HERE.parent/'truthfulness-2026-10-18/desktop-finality-receipt.json').read_text())['results'][1]['layout']
    assert layout==old,(layout,old)
    assert not errors,errors
    browser.close()
receipt={'checkedAt':dt.datetime.now(dt.UTC).isoformat(),'browser':'system Chromium with installed Playwright','viewport':{'width':1440,'height':1000},'pageErrors':errors,'layout':layout,'rankingChecks':ranking,'partialRevenueHeatmapColors':colors,'screenshots':{f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in OUT.glob('*.png')}}
(HERE/'desktop-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False,indent=2))
